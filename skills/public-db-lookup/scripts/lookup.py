#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.34.2"]
# ///
"""GET endpoints of public life-science databases and print compact JSON envelopes.

Single mode performs one bounded GET. Batch mode (--tasks) reads a JSON array
of query tasks, runs each through the same request/pacing/retry/redaction
pipeline, and writes one per-task record plus an overall summary to the file
named by --output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, quote_plus

import requests

try:
    import fcntl  # POSIX only; the lock is skipped where it does not exist.
except ModuleNotFoundError:  # Windows
    fcntl = None  # type: ignore[assignment]

BASE_URLS = {
    "uniprot": "https://rest.uniprot.org",
    "ncbi-entrez": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
    "ncbi-datasets": "https://api.ncbi.nlm.nih.gov/datasets/v2",
    "mgnify": "https://www.ebi.ac.uk/metagenomics/api/v2",
    "interpro": "https://www.ebi.ac.uk/interpro/api",
    "alphafold": "https://alphafold.ebi.ac.uk/api",
    "string": "https://string-db.org/api",
    "ena": "https://www.ebi.ac.uk/ena/portal/api",
}
NCBI_SERVICES = {"ncbi-entrez", "ncbi-datasets"}
# The key and the tool name come from the environment. A contact address never
# does: it is sent only when the user passes --email.
NCBI_ENV_PARAMS = (("api_key", "NCBI_API_KEY"), ("tool", "NCBI_TOOL"))
# Values of these request parameters are removed from every printed URL, error
# and response body.
HIDDEN_PARAMS = frozenset({"api_key", "email"})
# Never accept a credential from the command line or an embedded query string;
# it would be echoed back in the emitted url and land in shell history.
CREDENTIAL_PARAMS = frozenset({"api_key", "apikey", "key", "token", "access_token", "password", "secret"})
RECORD_KEYS = ("results", "data", "collection", "records", "items", "hits", "reports", "esearchresult.idlist")
USER_AGENT = "omics-skills-public-db-lookup (+https://github.com/fmschulz/omics-skills)"
MAX_STRING = 240
TEXT_HEAD = 800
RETRY_SLEEPS = (1, 2, 4)
# Documented request spacing per service (references/services.md). NCBI allows
# 3/s without a key; STRING asks for one second between calls.
MIN_INTERVALS = {"ncbi-entrez": 0.34, "ncbi-datasets": 0.2, "string": 1.0, "ena": 0.02}
EXIT_CODES = {"invalid_input": 2}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", choices=sorted(BASE_URLS), help="required for a single lookup; batch mode takes the service from each task")
    parser.add_argument("--path", help="endpoint path relative to the service base URL, or a full URL under that base")
    parser.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--record-path", help="dotted path to the list of records (inferred when omitted)")
    parser.add_argument("--max-items", type=int, default=5)
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--format", choices=("auto", "json", "text"), default="auto")
    parser.add_argument("--save-raw", type=Path, help="write the full response body to this path (single lookup only)")
    parser.add_argument(
        "--tasks",
        type=Path,
        help=(
            "batch mode: a JSON file holding an array of tasks, each with service, path "
            "and params (and optional record_path, max_items). Requires --output."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="batch mode: write one record per task plus an overall summary to this JSON file",
    )
    parser.add_argument(
        "--email",
        help=(
            "Contact address for NCBI (NCBI services only). Pass it only when the user "
            "gave an address for this purpose; no environment variable supplies it."
        ),
    )
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        / "omics-skills"
        / "public-db-lookup",
        help="Where the cross-invocation rate-limit timestamps live.",
    )
    return parser.parse_args(argv)


def build_request(args: argparse.Namespace, env: dict[str, str]) -> tuple[str, list[tuple[str, str]], dict[str, str]]:
    """Return (url, params, headers); raise ValueError on invalid input."""
    if args.max_items < 1 or args.max_depth < 1:
        raise ValueError("--max-items and --max-depth must be at least 1")
    if args.service not in BASE_URLS:
        raise ValueError(f"unknown service {args.service!r}; choose one of: {', '.join(sorted(BASE_URLS))}")
    base = BASE_URLS[args.service]
    if "://" in args.path:
        if not args.path.startswith(base + "/"):
            raise ValueError(f"full URLs must start with {base}/")
        url = args.path
    else:
        url = f"{base}/{args.path.lstrip('/')}"
    # Split any query string off the path so embedded parameters go through the
    # same credential filter as --param. Left in the URL, a key rode straight
    # into the emitted `url` field.
    url, _, path_query = url.partition("?")
    # A list of pairs, not a dict: repeated parameters are legitimate (Entrez
    # ELink takes several `id=` values and pairs them with its outputs).
    params: list[tuple[str, str]] = list(parse_qsl(path_query, keep_blank_values=True))
    for item in args.param:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise ValueError(f"--param expects KEY=VALUE, got {item!r}")
        params.append((key, value))
    for key, _value in params:
        name = key.lower().replace("-", "_")
        if name in CREDENTIAL_PARAMS:
            raise ValueError(f"pass {key!r} through the environment, not the URL or --param")
        if name == "email":
            raise ValueError(
                "pass a contact address with --email, not in the URL or --param"
            )
    if args.service in NCBI_SERVICES:
        supplied = {key for key, _ in params}
        for key, env_name in NCBI_ENV_PARAMS:
            if env.get(env_name) and key not in supplied:
                params.append((key, env[env_name]))
        if args.email:
            params.append(("email", args.email))
    elif args.email:
        raise ValueError("--email applies to the NCBI services only")
    headers = {"User-Agent": USER_AGENT}
    if args.format != "text":
        headers["Accept"] = "application/json"
    return url, params, headers


def retry_delay(retry_after: str | None, attempt: int) -> float:
    try:
        return max(float(retry_after), 0.0)
    except (TypeError, ValueError):
        return RETRY_SLEEPS[attempt]


def pace_across_processes(service: str, min_interval: float, state_dir: Path) -> None:
    """Space requests to `service` across CLI invocations.

    This script performs one lookup per run, so an in-process pacer would only
    space retries while an agent calling it in a loop still hammers the service.
    The last-request timestamp therefore lives on disk, under a lock, the same
    way crossref-lookup's measure_impact.py paces OpenAlex.
    """
    if min_interval <= 0:
        return
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / f"{service}.last-request"
        if fcntl is not None:
            lock_file = (state_dir / f"{service}.lock").open("a+", encoding="utf-8")
        else:  # no cross-process locks on this platform
            lock_file = None
        try:
            if lock_file is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                last = float(state_path.read_text().strip())
            except (OSError, ValueError):
                last = None
            if last is not None:
                time.sleep(max(0.0, min_interval - (time.time() - last)))
            state_path.write_text(f"{time.time():.6f}\n", encoding="utf-8")
            if lock_file is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            if lock_file is not None:
                lock_file.close()
    except (OSError, ValueError):
        # A read-only or unavailable state directory must not block a lookup.
        # ValueError covers paths the platform refuses to construct at all
        # (for example an embedded NUL on Windows).
        time.sleep(min_interval)


def fetch(
    session: Any,
    url: str,
    params: list[tuple[str, str]],
    headers: dict[str, str],
    timeout: float,
    pace: Callable[[], None] = lambda: None,
) -> Any:
    """GET with up to three retries on 429 and 5xx; return the last response.

    `pace` runs before EVERY request, retries included. Pacing only the first
    one let a retry follow it immediately and break the documented rate."""
    for attempt in range(len(RETRY_SLEEPS) + 1):
        pace()
        response = session.get(url, params=params, headers=headers, timeout=timeout)
        if response.status_code != 429 and response.status_code < 500:
            return response
        if attempt < len(RETRY_SLEEPS):
            time.sleep(retry_delay(response.headers.get("Retry-After"), attempt))
    return response


def compact(value: Any, max_items: int, max_depth: int, depth: int = 0) -> Any:
    if isinstance(value, str):
        return value if len(value) <= MAX_STRING else value[:MAX_STRING] + "..."
    if isinstance(value, dict):
        if depth >= max_depth:
            return "..."
        keys = list(value)
        out = {key: compact(value[key], max_items, max_depth, depth + 1) for key in keys[:max_items]}
        if len(keys) > max_items:
            out["_truncated_keys"] = len(keys) - max_items
        return out
    if isinstance(value, list):
        if depth >= max_depth:
            return "..."
        out = [compact(item, max_items, max_depth, depth + 1) for item in value[:max_items]]
        if len(value) > max_items:
            out.append(f"... (+{len(value) - max_items} more)")
        return out
    return value


def get_path(payload: Any, path: str) -> Any:
    for key in path.split("."):
        if not isinstance(payload, dict) or key not in payload:
            return None
        payload = payload[key]
    return payload


def find_records(payload: Any, record_path: str | None) -> tuple[str | None, list[Any] | None, list[str]]:
    if record_path:
        records = get_path(payload, record_path)
        if isinstance(records, list):
            return record_path, records, []
        return None, None, [f"--record-path {record_path!r} did not resolve to a list; returning summary"]
    if isinstance(payload, list):
        return None, payload, []
    for key in RECORD_KEYS:
        records = get_path(payload, key)
        if isinstance(records, list):
            return key, records, []
    return None, None, []


def available_count(payload: Any, record_path: str | None, records: list[Any]) -> int:  # noqa: ANN401  # decoded JSON of any shape
    """Return the number of matches the service reports, else the list length.

    An esearch response holds one page of ids in `idlist`; the hit total is in
    `esearchresult.count`. Other list responses may carry an integer total as a
    top-level `count` (MGnify v2 does).
    """
    if record_path == "esearchresult.idlist":
        try:
            return int(get_path(payload, "esearchresult.count"))
        except (TypeError, ValueError):
            pass
    total = payload.get("count") if isinstance(payload, dict) else None
    if isinstance(total, int) and not isinstance(total, bool) and total >= len(records):
        return total
    return len(records)


def redact(text: str, secrets: list[str]) -> str:
    """Replace every secret value in ``text``, also in its URL-encoded forms."""
    for secret in secrets:
        forms = (secret, quote(secret, safe=""), quote_plus(secret))
        for form in forms:
            text = text.replace(form, "REDACTED")
    return text


def redact_payload(value: Any, secrets: list[str]) -> Any:  # noqa: ANN401  # decoded JSON of any shape
    """Redact decoded strings. A raw-text pass misses an escaped secret such as
    "\u0053YNTHETIC", which json.loads turns back into the real value."""
    if not secrets:
        return value
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, dict):
        return {
            redact_payload(k, secrets): redact_payload(v, secrets)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_payload(item, secrets) for item in value]
    return value


def failure_envelope(source: str, code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "source": source, "error": {"code": code, "message": message}}


def emit(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if payload["ok"]:
        return 0
    return EXIT_CODES.get(payload["error"]["code"], 1)


def fail(source: str, code: str, message: str) -> int:
    return emit(failure_envelope(source, code, message))


def fallback_display_url(service: str, path: str) -> str | None:
    """Best-effort redacted URL for a task whose request could not be built.

    Credential-bearing query parameters (the ones build_request rejects) and
    hidden values are dropped rather than echoed, so a failed task still names
    the endpoint it aimed at without leaking the rejected secret.
    """
    base = BASE_URLS.get(service)
    if base is None:
        return None
    head, _, path_query = path.partition("?")
    if "://" in head:
        url = head
    else:
        url = f"{base}/{head.lstrip('/')}"
    shown = [
        (key, value)
        for key, value in parse_qsl(path_query, keep_blank_values=True)
        if key.lower().replace("-", "_") not in CREDENTIAL_PARAMS
        and key.lower() not in HIDDEN_PARAMS
    ]
    if shown:
        url = str(requests.Request("GET", url, params=shown).prepare().url)
    return url


def run_query(
    args: argparse.Namespace,
    session: Any,
    env: dict[str, str],
) -> dict[str, Any]:
    """Run one lookup and return the envelope without printing it.

    Both the single-shot CLI and batch mode go through this function so request
    construction, cross-process pacing, retries and secret redaction exist in
    exactly one place.
    """
    source = args.service
    try:
        url, params, headers = build_request(args, env)
    except ValueError as error:
        return failure_envelope(source, "invalid_input", str(error))
    secrets = [value for key, value in params if key in HIDDEN_PARAMS and value]
    shown = [(key, value) for key, value in params if key not in HIDDEN_PARAMS]
    display_url = str(requests.Request("GET", url, params=shown).prepare().url)

    try:
        min_interval = MIN_INTERVALS.get(args.service, 0.0)
        response = fetch(
            session, url, params, headers, args.timeout,
            pace=lambda: pace_across_processes(args.service, min_interval, args.state_dir),
        )
    except requests.RequestException as error:
        return failure_envelope(source, "network_error", redact(str(error), secrets))
    content_type = str(
        {k.lower(): v for k, v in response.headers.items()}.get("content-type", "")
    )
    if "charset" not in content_type.lower():
        # requests decodes text/* without a charset as ISO-8859-1, which garbles
        # the UTF-8 these services send (ENA searchFields).
        response.encoding = "utf-8"
    # Redact before anything is parsed or printed: a service that echoes the
    # request (NCBI error bodies do) would otherwise leak the key on success too.
    text = redact(response.text, secrets)
    if not 200 <= response.status_code < 300:
        head = text[:200]
        return failure_envelope(
            source, "http_error", f"HTTP {response.status_code} from {display_url}: {head}"
        )

    raw_output_path = None
    if args.save_raw:
        try:
            args.save_raw.write_text(text, encoding="utf-8")
        except OSError as error:
            return failure_envelope(source, "invalid_input", f"cannot write --save-raw: {error}")
        raw_output_path = str(args.save_raw)

    result: dict[str, Any] = {
        "ok": True,
        "source": source,
        "url": display_url,
        "status_code": response.status_code,
    }
    looks_json = "json" in content_type.lower() or text.lstrip()[:1] in ("{", "[")
    if args.format == "text" or (args.format == "auto" and not looks_json):
        result["text_head"] = text[:TEXT_HEAD]
        result["text_head_truncated"] = len(text) > TEXT_HEAD
        result["warnings"] = []
    else:
        try:
            payload = json.loads(text)
        except ValueError as error:
            return failure_envelope(
                source, "invalid_response", f"response is not valid JSON: {error}"
            )
        # Redact again after decoding: "\u0053YNTHETIC" survives a raw-text pass.
        payload = redact_payload(payload, secrets)
        # Several services report failures as HTTP 200 with an error envelope.
        # Reporting ok:true for those turned a rejected query into an empty
        # but confident answer.
        service_error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(payload, dict) and isinstance(payload.get("esearchresult"), dict):
            service_error = service_error or payload["esearchresult"].get("ERROR")
        if service_error:
            return failure_envelope(
                source, "service_error", f"{display_url} returned an error: {service_error}"
            )
        record_path, records, warnings = find_records(payload, args.record_path)
        if records is not None:
            result["record_path"] = record_path
            result["record_count_returned"] = min(len(records), args.max_items)
            available = available_count(payload, record_path, records)
            result["record_count_available"] = available
            result["truncated"] = available > result["record_count_returned"]
            result["records"] = [compact(item, args.max_items, args.max_depth) for item in records[: args.max_items]]
        else:
            result["summary"] = compact(payload, args.max_items, args.max_depth)
            result["top_keys"] = list(payload)[:50] if isinstance(payload, dict) else []
        result["warnings"] = warnings
    result["raw_output_path"] = raw_output_path
    return result


class TaskFileError(ValueError):
    """The batch task file cannot be parsed or fails the structural contract."""


TASK_KEYS = frozenset({"service", "path", "params", "record_path", "max_items"})


def load_tasks(path: Path) -> list[dict[str, Any]]:
    """Load and structurally validate the JSON task array."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TaskFileError(f"cannot read task file {path}: {error}") from error
    if not isinstance(document, list):
        raise TaskFileError("task file must contain a JSON array of task objects")
    tasks: list[dict[str, Any]] = []
    for index, task in enumerate(document):
        where = f"task[{index}]"
        if not isinstance(task, dict):
            raise TaskFileError(f"{where} must be an object")
        unknown = sorted(set(task) - TASK_KEYS)
        if unknown:
            raise TaskFileError(f"{where} has unknown key(s): {', '.join(unknown)}")
        if not isinstance(task.get("service"), str) or not task["service"].strip():
            raise TaskFileError(f"{where} needs a string 'service'")
        if not isinstance(task.get("path"), str) or not task["path"].strip():
            raise TaskFileError(f"{where} needs a string 'path'")
        params = task.get("params", [])
        if not isinstance(params, list) or not all(
            isinstance(pair, list)
            and len(pair) == 2
            and all(isinstance(part, str) for part in pair)
            for pair in params
        ):
            raise TaskFileError(f"{where} 'params' must be an array of [key, value] string pairs")
        if "record_path" in task and not isinstance(task["record_path"], str):
            raise TaskFileError(f"{where} 'record_path' must be a string")
        if "max_items" in task and (
            isinstance(task["max_items"], bool) or not isinstance(task["max_items"], int)
        ):
            raise TaskFileError(f"{where} 'max_items' must be an integer")
        tasks.append(task)
    return tasks


def task_to_args(
    task: dict[str, Any],
    defaults: argparse.Namespace,
) -> argparse.Namespace:
    """Project one task object onto the same Namespace the single CLI builds."""
    return argparse.Namespace(
        service=task["service"],
        path=task["path"],
        # Re-encode the pairs as KEY=VALUE so build_request's parsing and
        # credential filter are reused verbatim; '=' inside a value survives
        # because the parser partitions on the first one.
        param=[f"{key}={value}" for key, value in task.get("params", [])],
        record_path=task.get("record_path"),
        max_items=task.get("max_items", defaults.max_items),
        max_depth=defaults.max_depth,
        format=defaults.format,
        save_raw=None,
        email=defaults.email,
        timeout=defaults.timeout,
        state_dir=defaults.state_dir,
    )


def summarize_record(index: int, task: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    """Project one envelope onto the stable per-record batch contract."""
    return {
        "task": index,
        "service": envelope.get("source", task.get("service")),
        # build_request rejects embedded credentials before a URL exists; the
        # fallback rebuilds one with those parameters dropped.
        "url": envelope.get("url") or fallback_display_url(task["service"], task["path"]),
        "status": "ok" if envelope.get("ok") else "failed",
        "record_count_returned": envelope.get("record_count_returned"),
        "record_count_available": envelope.get("record_count_available"),
        "truncated": envelope.get("truncated"),
        "error": envelope.get("error"),
        "envelope": envelope,
    }


def run_batch(
    args: argparse.Namespace,
    session: Any,
    env: dict[str, str],
) -> int:
    """Execute every task, continuing past per-task failures; write one report.

    Returns 0 when all tasks succeeded, 1 when at least one failed, 2 when the
    task file itself is unusable.
    """
    try:
        tasks = load_tasks(args.tasks)
    except TaskFileError as error:
        print(json.dumps({"ok": False, "error": {"code": "invalid_input", "message": str(error)}}, indent=2))
        return EXIT_CODES["invalid_input"]

    records: list[dict[str, Any]] = []
    for index, task in enumerate(tasks):
        envelope = run_query(task_to_args(task, args), session, env)
        records.append(summarize_record(index, task, envelope))

    failures = [record for record in records if record["status"] == "failed"]
    report = {
        "ok": not failures,
        "mode": "batch",
        "task_file": str(args.tasks),
        "task_count": len(tasks),
        "success_count": len(records) - len(failures),
        "failure_count": len(failures),
        "results": records,
    }
    try:
        # Write atomically: a crash mid-run must not leave a half-written
        # report that looks complete.
        tmp_path = args.output.with_name(args.output.name + ".tmp")
        tmp_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(args.output)
    except OSError as error:
        print(json.dumps({"ok": False, "error": {"code": "invalid_input", "message": f"cannot write --output: {error}"}}, indent=2))
        return 1
    print(
        f"batch complete: {report['success_count']}/{report['task_count']} task(s) succeeded, "
        f"{report['failure_count']} failed; report written to {args.output}",
        file=sys.stderr,
    )
    return 1 if failures else 0


def main(argv: list[str] | None = None, session: Any = None, env: dict[str, str] | None = None) -> int:
    args = parse_args(argv)
    env = os.environ if env is None else env
    if args.tasks is not None:
        if args.output is None:
            return fail("batch", "invalid_input", "--tasks requires --output PATH for the JSON report")
        if args.save_raw is not None:
            return fail("batch", "invalid_input", "--save-raw is not available in batch mode")
        return run_batch(args, session or requests.Session(), env)
    if args.output is not None:
        return fail(args.service or "single", "invalid_input", "--output requires --tasks PATH")
    if args.service is None or args.path is None:
        return fail(args.service or "single", "invalid_input", "single lookups require --service and --path")
    return emit(run_query(args, session or requests.Session(), env))


if __name__ == "__main__":
    sys.exit(main())
