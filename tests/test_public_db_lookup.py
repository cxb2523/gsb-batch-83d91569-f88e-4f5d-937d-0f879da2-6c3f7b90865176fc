from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests

QUOTE = "\N{RIGHT SINGLE QUOTATION MARK}"
REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "skills" / "public-db-lookup" / "scripts" / "lookup.py"
SPEC = importlib.util.spec_from_file_location("public_db_lookup", MODULE_PATH)
public_db_lookup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = public_db_lookup
SPEC.loader.exec_module(public_db_lookup)


def response(status_code: int, body: object = None, headers: dict[str, str] | None = None) -> Mock:
    text = body if isinstance(body, str) else json.dumps(body if body is not None else [])
    return Mock(status_code=status_code, text=text, headers={"content-type": "application/json", **(headers or {})})


def run(argv: list[str], session: Mock, env: dict[str, str] | None = None) -> tuple[int, dict]:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = public_db_lookup.main(argv, session=session, env=env or {})
    return code, json.loads(stdout.getvalue())


class PublicDbLookupTests(unittest.TestCase):
    def test_compaction_bounds_records_and_reports_totals(self) -> None:
        session = Mock()
        session.get = Mock(return_value=response(200, {"results": [{"id": i} for i in range(7)]}))
        code, envelope = run(["--service", "uniprot", "--path", "uniprotkb/search", "--max-items", "3"], session)
        self.assertEqual(code, 0)
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["record_path"], "results")
        self.assertEqual(len(envelope["records"]), 3)
        self.assertEqual(envelope["record_count_returned"], 3)
        self.assertEqual(envelope["record_count_available"], 7)
        self.assertTrue(envelope["truncated"])

    def test_text_without_a_charset_is_decoded_as_utf8(self) -> None:
        """requests decodes text/* without a charset as ISO-8859-1, which garbles
        UTF-8 text (ENA searchFields serves text/plain with no charset)."""
        real = requests.Response()
        real.status_code = 200
        real._content = f"field\tdescription\nname\tit{QUOTE}s\n".encode()
        real.headers["Content-Type"] = "text/plain"
        # The HTTP adapter sets this the same way when it builds a response.
        real.encoding = requests.utils.get_encoding_from_headers(real.headers)
        session = Mock()
        session.get = Mock(return_value=real)
        with tempfile.TemporaryDirectory() as tmp:
            saved = Path(tmp) / "raw.txt"
            code, envelope = run(
                [
                    "--service",
                    "ena",
                    "--path",
                    "searchFields",
                    "--format",
                    "text",
                    "--save-raw",
                    str(saved),
                ],
                session,
            )
            self.assertEqual(code, 0)
            self.assertIn(f"it{QUOTE}s", envelope["text_head"])
            self.assertIn(f"it{QUOTE}s", saved.read_text(encoding="utf-8"))

    def test_esearch_reports_the_hit_count_not_the_idlist_length(self) -> None:
        body = {
            "esearchresult": {
                "count": "11018",
                "retmax": "20",
                "idlist": [str(i) for i in range(20)],
            }
        }
        session = Mock()
        session.get = Mock(return_value=response(200, body))
        code, envelope = run(
            ["--service", "ncbi-entrez", "--path", "esearch.fcgi", "--max-items", "5"],
            session,
        )
        self.assertEqual(code, 0)
        self.assertEqual(envelope["record_path"], "esearchresult.idlist")
        self.assertEqual(envelope["record_count_returned"], 5)
        self.assertEqual(envelope["record_count_available"], 11018)
        self.assertTrue(envelope["truncated"])

    def test_mgnify_uses_api_v2_and_its_items_key(self) -> None:
        """MGnify API v1 is deprecated; v2 list responses put records under `items`."""
        session = Mock()
        session.get = Mock(
            return_value=response(
                200, {"count": 644, "items": [{"accession": "MGYS00001031"}]}
            )
        )
        code, envelope = run(["--service", "mgnify", "--path", "studies/"], session)
        self.assertEqual(code, 0)
        self.assertTrue(
            session.get.call_args.args[0].startswith(
                "https://www.ebi.ac.uk/metagenomics/api/v2/"
            )
        )
        self.assertEqual(envelope["record_path"], "items")

    def test_a_list_response_with_a_total_reports_it_as_available(self) -> None:
        """MGnify v2 lists carry the total as `count`; the page holds fewer records."""
        body = {
            "count": 644,
            "items": [{"accession": f"MGYS{i:08d}"} for i in range(25)],
        }
        session = Mock()
        session.get = Mock(return_value=response(200, body))
        code, envelope = run(
            ["--service", "mgnify", "--path", "studies/", "--max-items", "5"], session
        )
        self.assertEqual(code, 0)
        self.assertEqual(envelope["record_count_returned"], 5)
        self.assertEqual(envelope["record_count_available"], 644)
        self.assertTrue(envelope["truncated"])

    def test_a_list_response_without_a_total_reports_the_page_length(self) -> None:
        body = {"results": [{"id": i} for i in range(7)], "count": "not a number"}
        session = Mock()
        session.get = Mock(return_value=response(200, body))
        _code, envelope = run(
            ["--service", "uniprot", "--path", "uniprotkb/search", "--max-items", "3"],
            session,
        )
        self.assertEqual(envelope["record_count_available"], 7)

    def test_retries_after_429_and_succeeds(self) -> None:
        session = Mock()
        session.get = Mock(side_effect=[response(429, "slow down", {"Retry-After": "0"}), response(200, [{"a": 1}])])
        code, envelope = run(["--service", "alphafold", "--path", "prediction/P04637"], session)
        self.assertEqual(code, 0)
        self.assertTrue(envelope["ok"])
        self.assertEqual(session.get.call_count, 2)

    def test_rejects_foreign_urls_and_cli_api_keys(self) -> None:
        session = Mock()
        env = {"NCBI_API_KEY": "topsecretkey"}
        code, envelope = run(["--service", "ncbi-entrez", "--path", "https://example.invalid/esearch.fcgi"], session, env)
        self.assertEqual((code, envelope["error"]["code"]), (2, "invalid_input"))
        code, envelope = run(["--service", "ncbi-entrez", "--path", "esearch.fcgi", "--param", "api_key=x"], session, env)
        self.assertEqual((code, envelope["error"]["code"]), (2, "invalid_input"))
        session.get.assert_not_called()

    def test_404_is_http_error_with_exit_1(self) -> None:
        session = Mock()
        session.get = Mock(return_value=response(404, "not found"))
        code, envelope = run(["--service", "uniprot", "--path", "uniprotkb/NOPE"], session)
        self.assertEqual(code, 1)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "http_error")

    def test_request_construction_for_every_service(self) -> None:
        env = {"NCBI_API_KEY": "topsecretkey"}
        for service, base in public_db_lookup.BASE_URLS.items():
            with self.subTest(service=service):
                args = public_db_lookup.parse_args(["--service", service, "--path", "some/path"])
                url, params, headers = public_db_lookup.build_request(args, env)
                self.assertTrue(url.startswith(base + "/"), url)
                self.assertEqual(headers["User-Agent"], public_db_lookup.USER_AGENT)
                if service in public_db_lookup.NCBI_SERVICES:
                    self.assertIn(("api_key", "topsecretkey"), params)
                    session = Mock()
                    session.get = Mock(return_value=response(200, []))
                    _, envelope = run(["--service", service, "--path", "some/path"], session, env)
                    self.assertIn(("api_key", "topsecretkey"), session.get.call_args.kwargs["params"])
                    self.assertNotIn("topsecretkey", envelope["url"])
                    self.assertNotIn("topsecretkey", json.dumps(envelope))
                else:
                    self.assertNotIn("api_key", params)




class ContactAddressTests(unittest.TestCase):
    """A contact address is sent only when the user passes --email, and it never
    comes back out in the envelope, the displayed URL or an error."""

    ADDRESS = "you@example.org"

    def ncbi(self, session: Mock, *extra: str, env: dict[str, str] | None = None):
        argv = ["--service", "ncbi-entrez", "--path", "esearch.fcgi", *extra]
        return run(argv, session, env if env is not None else {})

    def test_an_ambient_ncbi_email_is_not_sent(self) -> None:
        session = Mock()
        session.get = Mock(return_value=response(200, []))
        env = {"NCBI_EMAIL": self.ADDRESS, "NCBI_API_KEY": "k", "NCBI_TOOL": "my-tool"}
        _, envelope = self.ncbi(session, env=env)
        sent = dict(session.get.call_args.kwargs["params"])
        self.assertNotIn("email", sent)
        self.assertEqual(sent["api_key"], "k")
        self.assertEqual(sent["tool"], "my-tool")
        self.assertNotIn(self.ADDRESS, json.dumps(envelope))

    def test_the_email_flag_is_sent_and_kept_out_of_the_output(self) -> None:
        session = Mock()
        echo = {"results": [{"echo": f"contact {self.ADDRESS}"}]}
        session.get = Mock(return_value=response(200, echo))
        code, envelope = self.ncbi(session, "--email", self.ADDRESS)
        self.assertEqual(code, 0)
        self.assertIn(("email", self.ADDRESS), session.get.call_args.kwargs["params"])
        self.assertNotIn(self.ADDRESS, json.dumps(envelope))
        self.assertNotIn("email=", envelope["url"])

    def test_http_errors_do_not_echo_the_address(self) -> None:
        session = Mock()
        session.get = Mock(
            return_value=response(400, f"bad request from {self.ADDRESS}")
        )
        code, envelope = self.ncbi(session, "--email", self.ADDRESS)
        self.assertEqual((code, envelope["error"]["code"]), (1, "http_error"))
        self.assertNotIn(self.ADDRESS, json.dumps(envelope))

    def test_network_errors_do_not_echo_the_address(self) -> None:
        session = Mock()
        session.get = Mock(
            side_effect=requests.ConnectionError(f"failed: email={self.ADDRESS}")
        )
        code, envelope = self.ncbi(session, "--email", self.ADDRESS)
        self.assertEqual((code, envelope["error"]["code"]), (1, "network_error"))
        self.assertNotIn(self.ADDRESS, json.dumps(envelope))

    def test_network_errors_do_not_echo_the_url_encoded_address_or_key(self) -> None:
        key = "FAKE/KEY+VALUE"
        url = (
            requests.Request(
                "GET",
                "https://example.org",
                params={"email": self.ADDRESS, "api_key": key},
            )
            .prepare()
            .url
        )
        session = Mock()
        session.get = Mock(side_effect=requests.ConnectionError(f"failed: {url}"))
        code, envelope = self.ncbi(
            session, "--email", self.ADDRESS, env={"NCBI_API_KEY": key}
        )
        self.assertEqual((code, envelope["error"]["code"]), (1, "network_error"))
        shown = json.dumps(envelope)
        for leaked in ("you%40example.org", "FAKE%2FKEY%2BVALUE", "FAKE%2FKEY%2bVALUE"):
            self.assertNotIn(leaked, shown)

    def test_the_address_and_the_key_stay_out_of_a_service_error(self) -> None:
        session = Mock()
        body = {"esearchresult": {"ERROR": f"unknown {self.ADDRESS} and topsecretkey"}}
        session.get = Mock(return_value=response(200, body))
        _, envelope = self.ncbi(
            session, "--email", self.ADDRESS, env={"NCBI_API_KEY": "topsecretkey"}
        )
        self.assertEqual(envelope["error"]["code"], "service_error")
        self.assertNotIn(self.ADDRESS, json.dumps(envelope))
        self.assertNotIn("topsecretkey", json.dumps(envelope))

    def test_the_email_flag_is_for_ncbi_only(self) -> None:
        session = Mock()
        code, envelope = run(
            [
                "--service",
                "uniprot",
                "--path",
                "uniprotkb/P04637",
                "--email",
                self.ADDRESS,
            ],
            session,
        )
        self.assertEqual((code, envelope["error"]["code"]), (2, "invalid_input"))
        session.get.assert_not_called()

    def test_an_address_in_param_or_path_points_to_the_flag(self) -> None:
        session = Mock()
        for argv in (
            ["--param", f"email={self.ADDRESS}"],
            ["--path", f"esearch.fcgi?email={self.ADDRESS}"],
        ):
            with self.subTest(argv=argv):
                full = ["--service", "ncbi-entrez", "--path", "esearch.fcgi", *argv]
                code, envelope = run(full, session)
                self.assertEqual(
                    (code, envelope["error"]["code"]), (2, "invalid_input")
                )
                self.assertIn("--email", envelope["error"]["message"])
        session.get.assert_not_called()


class CredentialHandlingTests(unittest.TestCase):
    """A key embedded in --path bypassed the --param filter and rode straight
    into the emitted `url` field; successful bodies were never redacted."""

    def test_credentials_are_rejected_wherever_they_are_supplied(self) -> None:
        import argparse

        for path, param in (
            ("esearch.fcgi?db=protein&api_key=SYNTHETIC", []),
            ("esearch.fcgi?token=SYNTHETIC", []),
            ("esearch.fcgi?access-token=SYNTHETIC", []),
            ("esearch.fcgi", ["api_key=SYNTHETIC"]),
        ):
            with self.subTest(path=path, param=param):
                args = argparse.Namespace(
                    service="ncbi-entrez",
                    path=path,
                    param=list(param),
                    max_items=5,
                    max_depth=3,
                    format="auto",
                    email=None,
                )
                with self.assertRaisesRegex(ValueError, "through the environment"):
                    public_db_lookup.build_request(args, {})

    def test_ordinary_query_parameters_in_the_path_still_work(self) -> None:
        import argparse

        args = argparse.Namespace(
            service="ncbi-entrez",
            path="esearch.fcgi?db=protein&term=p53",
            param=[],
            max_items=5,
            max_depth=3,
            format="auto",
            email=None,
        )
        url, params, _ = public_db_lookup.build_request(args, {})
        self.assertTrue(url.endswith("/esearch.fcgi"))
        self.assertEqual(params, [("db", "protein"), ("term", "p53")])

    def test_api_key_is_redacted_from_a_successful_response_body(self) -> None:
        session = Mock()
        session.get = Mock(return_value=response(200, {"results": [{"echo": "api_key=SYNTHETIC"}]}))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = public_db_lookup.main(
                ["--service", "ncbi-entrez", "--path", "esearch.fcgi"],
                session=session,
                env={"NCBI_API_KEY": "SYNTHETIC"},
            )
        self.assertEqual(code, 0)
        self.assertNotIn("SYNTHETIC", stdout.getvalue())
        self.assertIn("REDACTED", stdout.getvalue())

    def test_http_200_error_envelope_is_not_a_successful_empty_result(self) -> None:
        """Several services report failures as HTTP 200 with an error body;
        reporting ok:true turned a rejected query into a confident answer."""
        for body in ({"error": "Invalid db name"}, {"esearchresult": {"ERROR": "Invalid db name"}}):
            with self.subTest(body=body):
                session = Mock()
                session.get = Mock(return_value=response(200, body))
                code, envelope = run(["--service", "ncbi-entrez", "--path", "esearch.fcgi"], session)
                self.assertEqual(code, 1)
                self.assertFalse(envelope["ok"])
                self.assertEqual(envelope["error"]["code"], "service_error")

    def test_repeated_query_parameters_are_preserved(self) -> None:
        """Entrez ELink takes several `id=` values and pairs them with its
        outputs; collapsing them into a dict dropped all but the last."""
        import argparse

        args = argparse.Namespace(
            service="ncbi-entrez",
            path="elink.fcgi?dbfrom=protein&db=gene&id=15718680&id=157427902",
            param=[],
            max_items=5,
            max_depth=3,
            format="auto",
            email=None,
        )
        _, params, _ = public_db_lookup.build_request(args, {})
        self.assertEqual(
            [value for key, value in params if key == "id"],
            ["15718680", "157427902"],
        )


    def test_rate_limit_state_is_shared_across_invocations(self) -> None:
        """One lookup per run means an in-process pacer would only space
        retries while a caller in a loop still hammers the service."""
        import tempfile
        import time

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            started = time.monotonic()
            for _ in range(3):
                public_db_lookup.pace_across_processes("string", 0.3, state)
            elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 0.55)

    def test_an_unwritable_state_directory_falls_back_to_a_plain_sleep(self) -> None:
        """With interval 0.0 the function returns before touching the directory,
        so the fallback was never exercised. An embedded NUL makes the path
        invalid on every platform (Linux rejects /proc paths too, but Windows
        happily creates them)."""
        import time

        started = time.monotonic()
        public_db_lookup.pace_across_processes("string", 0.2, Path("bad\0path/x"))
        self.assertGreaterEqual(time.monotonic() - started, 0.19)


def write_tasks(directory: Path, tasks: object, name: str = "tasks.json") -> Path:
    path = directory / name
    path.write_text(json.dumps(tasks), encoding="utf-8")
    return path


def run_batch(directory: Path, session: Mock, tasks: object, env: dict[str, str] | None = None) -> tuple[int, dict, str, str]:
    task_path = write_tasks(directory, tasks)
    output_path = directory / "report.json"
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = public_db_lookup.main(
            ["--tasks", str(task_path), "--output", str(output_path)],
            session=session,
            env=env or {},
        )
    report = json.loads(output_path.read_text(encoding="utf-8"))
    return code, report, stdout.getvalue(), stderr.getvalue()


class BatchModeTests(unittest.TestCase):
    """Batch mode reuses the single-lookup pipeline for every task and writes
    one report; a failing task never aborts the remaining ones."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_all_tasks_succeed_and_the_report_keeps_the_contract(self) -> None:
        bodies = [
            {"results": [{"id": i} for i in range(3)]},
            [{"accession": "MGYS00001031"}, {"accession": "MGYS00001032"}],
        ]
        session = Mock()
        session.get = Mock(side_effect=[response(200, bodies[0]), response(200, bodies[1])])
        tasks = [
            {
                "service": "uniprot",
                "path": "uniprotkb/search",
                "params": [["query", "p53"], ["size", "3"]],
                "record_path": "results",
                "max_items": 3,
            },
            {
                "service": "mgnify",
                "path": "studies/",
                "params": [["page_size", "2"]],
            },
        ]
        code, report, _stdout, stderr = run_batch(self.tmp, session, tasks)
        self.assertEqual(code, 0)
        self.assertTrue(report["ok"])
        self.assertEqual(report["mode"], "batch")
        self.assertEqual((report["task_count"], report["success_count"], report["failure_count"]), (2, 2, 0))
        self.assertEqual(session.get.call_count, 2)
        self.assertIn("2/2", stderr)
        for index, record in enumerate(report["results"]):
            self.assertEqual(record["task"], index)
            self.assertEqual(record["status"], "ok")
            self.assertIn("record_count_returned", record)
            self.assertIn("record_count_available", record)
            self.assertIn("truncated", record)
            self.assertIsNone(record["error"])
            self.assertTrue(record["url"].startswith("https://"))
            self.assertTrue(record["envelope"]["ok"])
        self.assertEqual(report["results"][0]["service"], "uniprot")
        self.assertEqual(report["results"][0]["record_count_available"], 3)
        self.assertFalse(report["results"][0]["truncated"])
        # The task params really reached the wire.
        sent = dict(session.get.call_args_list[0].kwargs["params"])
        self.assertEqual(sent["query"], "p53")
        self.assertEqual(sent["size"], "3")

    def test_one_failing_task_is_recorded_but_the_others_still_run(self) -> None:
        session = Mock()
        session.get = Mock(
            side_effect=[
                response(200, {"results": [{"id": 1}]}),
                response(404, "not found"),
                response(200, {"error": "Invalid db name"}),
                response(200, [{"id": 9}]),
            ]
        )
        tasks = [
            {"service": "uniprot", "path": "uniprotkb/search"},
            {"service": "uniprot", "path": "uniprotkb/NOPE"},
            {"service": "ncbi-entrez", "path": "esearch.fcgi"},
            {"service": "alphafold", "path": "prediction/P04637"},
        ]
        code, report, _stdout, _stderr = run_batch(self.tmp, session, tasks)
        self.assertEqual(code, 1)
        self.assertFalse(report["ok"])
        self.assertEqual((report["success_count"], report["failure_count"]), (2, 2))
        self.assertEqual(session.get.call_count, 4)
        statuses = [record["status"] for record in report["results"]]
        self.assertEqual(statuses, ["ok", "failed", "failed", "ok"])
        http_failure, service_failure = report["results"][1], report["results"][2]
        self.assertEqual(http_failure["error"]["code"], "http_error")
        self.assertEqual(service_failure["error"]["code"], "service_error")
        # A failed record still names the service and the redacted URL.
        self.assertEqual(http_failure["service"], "uniprot")
        self.assertIn("uniprotkb/NOPE", http_failure["url"])
        for field in ("record_count_returned", "record_count_available", "truncated"):
            self.assertIsNone(http_failure[field])

    def test_a_network_error_fails_one_task_without_stopping_the_batch(self) -> None:
        session = Mock()
        session.get = Mock(
            side_effect=[
                requests.ConnectionError("boom"),
                response(200, [{"id": 1}]),
            ]
        )
        tasks = [
            {"service": "uniprot", "path": "uniprotkb/A"},
            {"service": "uniprot", "path": "uniprotkb/B"},
        ]
        code, report, _stdout, _stderr = run_batch(self.tmp, session, tasks)
        self.assertEqual(code, 1)
        self.assertEqual(report["results"][0]["error"]["code"], "network_error")
        self.assertEqual(report["results"][1]["status"], "ok")

    def test_credentials_in_params_or_path_fail_the_task_and_never_leak(self) -> None:
        secret = "BATCH-SECRET-VALUE"
        address = "batch@example.org"
        session = Mock()
        session.get = Mock(return_value=response(200, {"results": []}))
        tasks = [
            {
                "service": "ncbi-entrez",
                "path": "esearch.fcgi",
                "params": [["api_key", secret]],
            },
            {
                "service": "ncbi-entrez",
                "path": f"esearch.fcgi?token={secret}",
                "params": [],
            },
            {
                "service": "ncbi-entrez",
                "path": "esearch.fcgi",
                "params": [["email", address]],
            },
            {
                "service": "ncbi-entrez",
                "path": "esearch.fcgi",
                "params": [["db", "taxonomy"], ["term", "Escherichia"]],
            },
        ]
        code, report, _stdout, _stderr = run_batch(
            self.tmp, session, tasks, env={"NCBI_API_KEY": "ambient-key"}
        )
        self.assertEqual(code, 1)
        self.assertEqual(report["failure_count"], 3)
        self.assertEqual(report["success_count"], 1)
        # The three rejected tasks never produced a request.
        self.assertEqual(session.get.call_count, 1)
        raw_report = json.dumps(report)
        self.assertNotIn(secret, raw_report)
        self.assertNotIn(address, raw_report)
        for record in report["results"][:3]:
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["error"]["code"], "invalid_input")
        # The rejected task still carries a redacted URL pointing at the endpoint.
        self.assertTrue(report["results"][0]["url"].endswith("/esearch.fcgi"))
        self.assertNotIn("api_key", report["results"][0]["url"])
        # The surviving task kept its ordinary parameters.
        sent = dict(session.get.call_args.kwargs["params"])
        self.assertEqual(sent["db"], "taxonomy")
        self.assertEqual(sent["api_key"], "ambient-key")

    def test_esearch_total_hits_drive_record_count_available_and_truncated(self) -> None:
        body = {
            "esearchresult": {
                "count": "11018",
                "retmax": "20",
                "idlist": [str(i) for i in range(20)],
            }
        }
        session = Mock()
        session.get = Mock(return_value=response(200, body))
        tasks = [
            {
                "service": "ncbi-entrez",
                "path": "esearch.fcgi",
                "params": [["db", "taxonomy"], ["term", "Escherichia"], ["retmode", "json"]],
                "record_path": "esearchresult.idlist",
                "max_items": 5,
            }
        ]
        code, report, _stdout, _stderr = run_batch(self.tmp, session, tasks)
        self.assertEqual(code, 0)
        record = report["results"][0]
        self.assertEqual(record["record_count_returned"], 5)
        self.assertEqual(record["record_count_available"], 11018)
        self.assertTrue(record["truncated"])

    def test_duplicate_params_are_preserved_through_the_batch_pipeline(self) -> None:
        session = Mock()
        session.get = Mock(return_value=response(200, []))
        tasks = [
            {
                "service": "ncbi-entrez",
                "path": "elink.fcgi",
                "params": [
                    ["dbfrom", "protein"],
                    ["id", "15718680"],
                    ["id", "157427902"],
                ],
            }
        ]
        code, report, _stdout, _stderr = run_batch(self.tmp, session, tasks)
        self.assertEqual(code, 0)
        sent = session.get.call_args.kwargs["params"]
        self.assertEqual([value for key, value in sent if key == "id"], ["15718680", "157427902"])

    def test_an_empty_task_array_is_a_successful_noop(self) -> None:
        session = Mock()
        code, report, _stdout, _stderr = run_batch(self.tmp, session, [])
        self.assertEqual(code, 0)
        self.assertTrue(report["ok"])
        self.assertEqual((report["task_count"], report["success_count"], report["failure_count"]), (0, 0, 0))
        self.assertEqual(report["results"], [])
        session.get.assert_not_called()

    def test_unparseable_and_structurally_invalid_task_files_exit_2(self) -> None:
        session = Mock()
        output_path = self.tmp / "report.json"
        bad_cases = [
            ("not json at all", "tasks-bad-json.json"),
            ({"not": "an array"}, "tasks-object.json"),
            ([{"service": "uniprot"}], "tasks-missing-path.json"),
            ([{"service": "uniprot", "path": "x", "params": {"db": "taxonomy"}}], "tasks-params-object.json"),
            ([{"service": "uniprot", "path": "x", "params": [["db", 7]]}], "tasks-nonstring-param.json"),
            ([{"service": "uniprot", "path": "x", "max_items": "5"}], "tasks-max-items-string.json"),
            ([{"service": "uniprot", "path": "x", "bogus": 1}], "tasks-unknown-key.json"),
            ([{"service": "uniprot", "path": "x", "record_path": 5}], "tasks-record-path-int.json"),
        ]
        for raw, name in bad_cases:
            task_path = self.tmp / name
            task_path.write_text(raw if isinstance(raw, str) else json.dumps(raw), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = public_db_lookup.main(
                    ["--tasks", str(task_path), "--output", str(output_path)],
                    session=session,
                    env={},
                )
            with self.subTest(name=name):
                self.assertEqual(code, 2)
                envelope = json.loads(stdout.getvalue())
                self.assertEqual(envelope["error"]["code"], "invalid_input")
        session.get.assert_not_called()
        self.assertFalse(output_path.exists())

    def test_an_unknown_service_is_a_per_task_failure_not_a_file_error(self) -> None:
        session = Mock()
        session.get = Mock(return_value=response(200, []))
        tasks = [
            {"service": "no-such-service", "path": "x"},
            {"service": "uniprot", "path": "uniprotkb/P04637"},
        ]
        code, report, _stdout, _stderr = run_batch(self.tmp, session, tasks)
        self.assertEqual(code, 1)
        self.assertEqual(report["results"][0]["error"]["code"], "invalid_input")
        self.assertEqual(report["results"][1]["status"], "ok")
        self.assertEqual(session.get.call_count, 1)

    def test_batch_mode_requires_output_and_rejects_save_raw(self) -> None:
        task_path = write_tasks(self.tmp, [])
        session = Mock()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = public_db_lookup.main(["--tasks", str(task_path)], session=session, env={})
        self.assertEqual(code, 2)
        self.assertIn("--output", json.loads(stdout.getvalue())["error"]["message"])
        raw_path = self.tmp / "raw.txt"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = public_db_lookup.main(
                ["--tasks", str(task_path), "--output", str(self.tmp / "r.json"), "--save-raw", str(raw_path)],
                session=session,
                env={},
            )
        self.assertEqual(code, 2)
        session.get.assert_not_called()

    def test_the_batch_report_is_redacted_when_a_response_echoes_a_secret(self) -> None:
        secret = "SYNTHETIC-BATCH-KEY"
        session = Mock()
        session.get = Mock(return_value=response(200, {"results": [{"echo": f"key={secret}"}]}))
        tasks = [
            {
                "service": "ncbi-entrez",
                "path": "esearch.fcgi",
                "params": [["db", "taxonomy"]],
            }
        ]
        _code, report, _stdout, _stderr = run_batch(
            self.tmp, session, tasks, env={"NCBI_API_KEY": secret}
        )
        raw_report = json.dumps(report)
        self.assertNotIn(secret, raw_report)
        self.assertIn("REDACTED", raw_report)
        self.assertNotIn(secret, report["results"][0]["url"])


if __name__ == "__main__":
    unittest.main()
