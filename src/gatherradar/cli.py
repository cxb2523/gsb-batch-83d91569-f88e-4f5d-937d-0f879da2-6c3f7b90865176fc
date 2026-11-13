from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable, Sequence

from .collectors.base import CollectorError, SourceNotFoundError
from .collectors.instagram import DEFAULT_LIMIT, InstagramCollector
from .collectors.instagram_auth import InstagramAuthError, create_session_from_cookie
from .collectors.instagram_browser import authenticate_browser_profile, browser_profile_path
from .collectors.instagram_instaloader import InstaloaderPostFetcher
from .domain import DiscoveryType, EvidenceKind, SourceType
from .extraction import DiscoveryStatus
from .orchestration.collection_run import RunSummary, run_instagram_collection
from .orchestration.discovery_run import DiscoveryRunSummary, run_instagram_discovery
from .orchestration.evidence_discovery_run import (
    EvidenceDiscoveryRunSummary, run_instagram_evidence_discovery,
)
from .orchestration.evidence_run import EvidenceRunSummary, run_instagram_evidence
from .orchestration.website_run import run_website_collection, run_website_discovery
from .ocr import OcrError
from .storage.jsonl import StorageError

TRANSPORT_BROWSER = "browser"
TRANSPORT_INSTALOADER = "instaloader"

_RESULT_LABELS = {
    DiscoveryType.EVENT: "Event",
    DiscoveryType.PLACE: "Place",
    DiscoveryType.OTHER: "Other",
}


def _use_utf8_output() -> None:
    """Let the terminal print Persian source wording instead of failing on it.

    A Windows console still defaults to a legacy code page, which cannot encode the
    captions this tool reports. Replacing unencodable characters is better than
    losing a run to an encoding error, and a redirected stream is left alone.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            continue


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gatherradar",
        description="Collect public event content from approved GatherRadar sources, "
        "and classify what was collected.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    collect = subcommands.add_parser("collect", help="Run a collection for one source.")
    collect_kinds = collect.add_subparsers(dest="source_type", required=True)

    instagram = collect_kinds.add_parser("instagram", help="Collect one Instagram source.")
    instagram.add_argument("source_id", help="Source id from config/sources.yaml")
    instagram.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum recent posts to fetch (default: {DEFAULT_LIMIT})",
    )
    instagram.add_argument(
        "--config",
        default="config/sources.yaml",
        help="Path to the source registry (default: config/sources.yaml)",
    )
    instagram.add_argument(
        "--data-dir",
        default="data",
        help="Root directory for local runtime data (default: data)",
    )
    instagram.add_argument(
        "--transport",
        choices=(TRANSPORT_BROWSER, TRANSPORT_INSTALOADER),
        default=TRANSPORT_BROWSER,
        help="Collection transport (default: browser). 'instaloader' is the legacy "
        "transport, kept only while the browser transport is validated.",
    )

    extract = subcommands.add_parser(
        "extract",
        help="Classify already-collected items for one source. Reads local storage only.",
        description="Classify already-collected raw items as events, places, or neither. "
        "This reads only what collection already stored: it opens no browser, contacts "
        "no source, needs no API key, and writes nothing.",
    )
    extract_kinds = extract.add_subparsers(dest="source_type", required=True)

    for kinds, verb in ((collect_kinds, 'Collect'), (extract_kinds, 'Classify stored')):
        website = kinds.add_parser('website', help=f'{verb} items for one website source.')
        website.add_argument('source_id', help='Source id from config/sources.yaml')
        website.add_argument('--limit', type=int, default=5,
                             help='Maximum items (1–30); listing order for collection, storage order for extraction.')
        website.add_argument('--config', default='config/sources.yaml')
        website.add_argument('--data-dir', default='data')
        if kinds is extract_kinds:
            website.add_argument('--normalize', action='store_true', help='Review deterministic normalization offline.')

    extract_instagram = extract_kinds.add_parser(
        "instagram",
        help="Classify stored Instagram items for one source.",
        description="Classify the most recently stored Instagram observations for one "
        "source. Nothing is collected and nothing is persisted.",
    )
    extract_instagram.add_argument("source_id", help="Source id from config/sources.yaml")
    extract_instagram.add_argument('--normalize', action='store_true', help='Review deterministic normalization offline.')
    extract_instagram.add_argument(
        '--evidence', action='store_true',
        help='Group already-stored local evidence offline; no collection or OCR.',
    )
    extract_instagram.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum stored items to analyze, newest first (default: {DEFAULT_LIMIT})",
    )
    extract_instagram.add_argument(
        "--config",
        default="config/sources.yaml",
        help="Path to the source registry (default: config/sources.yaml)",
    )
    extract_instagram.add_argument(
        "--data-dir",
        default="data",
        help="Root directory for local runtime data (default: data)",
    )

    evidence = subcommands.add_parser(
        'evidence', help='Acquire local visual evidence for stored source items.'
    )
    evidence_kinds = evidence.add_subparsers(dest='source_type', required=True)
    evidence_instagram = evidence_kinds.add_parser(
        'instagram', help='Capture and OCR media for stored Instagram items.'
    )
    evidence_instagram.add_argument('source_id', help='Source id from config/sources.yaml')
    evidence_instagram.add_argument('--limit', type=int, default=DEFAULT_LIMIT)
    evidence_instagram.add_argument('--config', default='config/sources.yaml')
    evidence_instagram.add_argument('--data-dir', default='data')
    evidence_instagram.add_argument('--max-carousel-slides', type=int, default=20)
    evidence_instagram.add_argument('--max-reel-frames', type=int, default=6)

    diagnose = subcommands.add_parser('diagnose', help='Read-only structural diagnostics of retained local data.')
    diagnose_kinds = diagnose.add_subparsers(dest='diagnose_kind', required=True)
    sessions = diagnose_kinds.add_parser('jabama-sessions', help='Value-free report of Jabama embedded session schemas.')
    sessions.add_argument('--data-dir', default='data')
    sessions.add_argument('--html', action='append', default=[],
                          help='A browser-saved public Jabama detail page to describe; repeatable.')
    sessions.add_argument('--output', help='Write the JSON report here instead of printing it.')
    timeslots = diagnose_kinds.add_parser(
        'jabama-timeslots', help='Booleans and counts relating saved Jabama sessions to their timeslots.')
    timeslots.add_argument('--html', action='append', required=True,
                           help='A browser-saved public Jabama detail page; repeatable.')
    timeslots.add_argument('--output', help='Write the JSON report here instead of printing it.')

    acceptance = subcommands.add_parser(
        'acceptance', help='Validate one finished run directory and write one review bundle; no collection.')
    acceptance.add_argument('--run-dir', required=True, help='Directory holding state.sqlite3, GatherRadar.xlsx, exports/.')
    acceptance.add_argument('--data-dir', default='data')
    acceptance.add_argument('--config', default='config/sources.yaml')
    acceptance.add_argument('--cases', default='scripts/acceptance_cases.json')
    acceptance.add_argument('--test-log', help='Test output to include as test-summary.txt.')
    acceptance.add_argument('--include-media', action='store_true',
                            help='Copy selected stored media of tracked cases into the bundle (bounded).')
    acceptance.add_argument('--max-media', type=int, default=40)
    acceptance.add_argument('--include', action='append', default=[],
                            help='Extra .txt/.json/.log file to add to the bundle; repeatable.')

    telegram = subcommands.add_parser('telegram', help='Owner-only Telegram bot (long polling, local).')
    telegram_actions = telegram.add_subparsers(dest='telegram_action', required=True)
    telegram_run = telegram_actions.add_parser(
        'run', help='Start the bot; reads GATHERRADAR_TELEGRAM_BOT_TOKEN and GATHERRADAR_TELEGRAM_OWNER_ID.')
    telegram_run.add_argument('--config', default='config/sources.yaml')
    telegram_run.add_argument('--data-dir', default='data')

    sources_cmd = subcommands.add_parser(
        'sources', help='Show the effective source registry (base YAML + local overlay); read-only.')
    sources_actions = sources_cmd.add_subparsers(dest='sources_action', required=True)
    sources_list = sources_actions.add_parser('list', help='List sources with state and origin.')
    sources_list.add_argument('--config', default='config/sources.yaml')
    sources_list.add_argument('--all', action='store_true', help='Include archived sources.')

    ocr = subcommands.add_parser('ocr', help='Check local OCR engines; read-only, no collection.')
    ocr_kinds = ocr.add_subparsers(dest='ocr_action', required=True)
    ocr_check = ocr_kinds.add_parser('check', help='Validate each configured engine and optionally read one image.')
    ocr_check.add_argument('--image', help='A local image to recognize with every available engine.')
    ocr_check.add_argument('--engines', help='Comma-separated engines (default: GATHERRADAR_OCR_ENGINES or '
                                             'tesseract,easyocr,windows).')

    auth = subcommands.add_parser(
        "auth", help="Create and verify an authenticated session for a source type."
    )
    auth_kinds = auth.add_subparsers(dest="auth_type", required=True)

    auth_instagram = auth_kinds.add_parser(
        "instagram",
        help="Open Chrome with the GatherRadar browser profile and log in to Instagram manually.",
    )
    auth_instagram.add_argument(
        "--data-dir",
        default="data",
        help="Root directory for local runtime data (default: data)",
    )
    auth_instagram.add_argument(
        "--legacy-cookie",
        action="store_true",
        help="Use the legacy Instaloader Cookie-header import instead of the browser profile.",
    )

    canonical = subcommands.add_parser('canonicalize', help='Review canonical events across local sources, offline and write-free.')
    selection = canonical.add_mutually_exclusive_group(required=True)
    selection.add_argument('--source', action='append', dest='sources', help='Source ID; repeat to compare sources.')
    selection.add_argument('--all-enabled', action='store_true', help='Analyze enabled sources with local data only.')
    canonical.add_argument('--limit', type=int, default=5, help='Maximum local raw items per source (1–30).')
    canonical.add_argument('--config', default='config/sources.yaml')
    canonical.add_argument('--data-dir', default='data')
    canonical.add_argument('--instagram-evidence', action='store_true', help='Use stored Stage 5 evidence, with caption fallback. No OCR.')

    from .sheets.cli import add_commands
    add_commands(subcommands, auth_kinds)
    from .review.cli import add_commands as add_local_commands
    add_local_commands(subcommands)
    return parser


def format_summary(summary: RunSummary) -> str:
    source = summary.source
    lines = [
        "GatherRadar collection run",
        "",
        f"Run id: {summary.run_id}",
        f"Source: {source.name}",
        f"Username: @{source.username}" if source.source_type is SourceType.INSTAGRAM else f"URL: {source.url}",
        "",
        f"Observed: {summary.observed}",
        f"New: {summary.new}",
        f"Changed: {summary.changed}",
        f"Existing: {summary.already_existing}",
        f"Failed: {summary.failed}",
    ]

    if summary.failure_reasons:
        lines.append("")
        lines.append("Skipped items:")
        lines.extend(f"  - {reason}" for reason in summary.failure_reasons)
    if getattr(summary, 'warnings', ()):
        lines.extend(('Warnings:', *(f'  - {reason}' for reason in summary.warnings)))

    lines.append("")
    lines.append("Saved:")
    lines.append(str(summary.output_path))
    return "\n".join(lines)


EXTRACT_FIELDS = (
    ("title", "title"),
    ("category", "category"),
    ("source_date_text", "source_date_text"),
    ("venue_name", "venue_name"),
    ("address", "address"),
    ("city", "city"),
    ("event_format", "event_format"),
    ("price_text", "price_text"),
    ("opening_hours_text", "opening_hours_text"),
    ("registration_url", "registration_url"),
    ("summary", "summary"),
    ("language", "language"),
)


def _format_outcome(position: int, outcome) -> list[str]:
    lines = [f"[{position}] {outcome.raw_item_id}"]

    if outcome.status is DiscoveryStatus.SKIPPED:
        lines.append(f"    Result: Skipped ({outcome.reason})")
        return lines
    if outcome.status is not DiscoveryStatus.DISCOVERED:
        lines.append(f"    Result: Failed ({outcome.status.value}) — {outcome.reason}")
        return lines

    evidence = outcome.evidence
    lines.append(f"    Result: {_RESULT_LABELS[outcome.discovery_type]}")
    if evidence is not None:
        lines.append(
            f"    Scores: event {evidence.event_score} / place {evidence.place_score} "
            f"/ negative {evidence.negative_score}"
        )
        lines.append(f"    Reason: {evidence.reason}")
        lines.append(f"    Signals: {', '.join(evidence.matched_signals) or '-'}")
        lines.append(f"    Negative: {', '.join(evidence.negative_signals) or '-'}")

    candidate = outcome.candidate
    if candidate is not None:
        lines.append("    Fields:")
        for name, label in EXTRACT_FIELDS:
            value = getattr(candidate, name, None)
            if value is not None:
                lines.append(f"      {label}: {value}")
        lines.append(f"      evidence_url: {candidate.evidence_url}")
    return lines


def format_discovery_summary(summary: DiscoveryRunSummary) -> str:
    """The run report: what each item was, why, and what was read from it."""
    source = summary.source
    lines = [
        "GatherRadar discovery run",
        "",
        f"Run id: {summary.run_id}",
        f"Source: {source.name if source else '-'}",
        f"Provider: {summary.provider_name} (deterministic rules, no AI and no network access)",
        f"Read: {summary.input_path}",
    ]

    if not summary.outcomes:
        lines.append("")
        lines.append("No stored items to analyze. Collect first with:")
        lines.append(f"  python -m gatherradar collect instagram {source.id if source else '<source_id>'}")

    for position, outcome in enumerate(summary.outcomes, start=1):
        lines.append("")
        lines.extend(_format_outcome(position, outcome))

    if summary.malformed:
        lines.append("")
        lines.append("Unreadable stored lines:")
        lines.extend(f"  - {reason}" for reason in summary.malformed)

    lines.extend(
        [
            "",
            f"Observed: {summary.observed}",
            f"Events: {summary.events}",
            f"Places: {summary.places}",
            f"Other: {summary.other}",
            f"Skipped: {summary.skipped}",
            f"Failed: {summary.failed}",
            "",
            "Nothing was persisted: candidates are a transient boundary, and "
            "normalization is a separate step.",
        ]
    )
    return "\n".join(lines)


def run_extract_instagram(args: argparse.Namespace) -> int:
    try:
        runner = run_instagram_evidence_discovery if args.evidence else run_instagram_discovery
        summary = runner(
            args.source_id,
            config_path=args.config,
            data_dir=args.data_dir,
            limit=args.limit,
        )
    except (SourceNotFoundError, StorageError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"error: source registry not found: {exc}", file=sys.stderr)
        return 1

    print(format_evidence_discovery_summary(summary) if args.evidence else format_discovery_summary(summary))
    if args.normalize:
        print(_normalized_review(summary))
    return 0


def _normalized_review(summary: DiscoveryRunSummary) -> str:
    # Lazy import keeps default discovery independent of normalization execution.
    from .normalization.review import format_normalization
    from .orchestration.normalization_run import run_normalization

    return format_normalization(run_normalization(
        summary.outcomes, {item.id: item for item in summary.raw_items},
        {summary.source.id: summary.source} if summary.source is not None else {},
        unit_texts={unit.unit_id: unit.text for item in summary.items for unit in item.units}
        if isinstance(summary, EvidenceDiscoveryRunSummary) else None,
    ))


def _fragment_label(fragment) -> str:
    if fragment.kind is EvidenceKind.CAROUSEL_SLIDE_OCR:
        return f'slide {fragment.slide_index}'
    if fragment.kind is EvidenceKind.REEL_FRAME_OCR:
        return f'frame {fragment.frame_timestamp_ms}ms'
    return fragment.kind.value


def format_evidence_discovery_summary(summary: EvidenceDiscoveryRunSummary) -> str:
    lines = [
        'GatherRadar evidence-aware discovery run', '', f'Run id: {summary.run_id}',
        f'Source: {summary.source.name if summary.source else "-"}',
        f'Grouping: {summary.grouping_strategy}',
        f'Provider: {summary.provider_name} (deterministic rules, no AI and no network access)',
    ]
    if not summary.items:
        lines.extend(('', 'No stored items to analyze.'))
    for position, item in enumerate(summary.items, 1):
        lines.extend(('', f'[{position}] {item.raw_item_id}', f'    DiscoveryUnits: {len(item.units)}'))
        if item.reason:
            lines.append(f'    Result: {"Failed" if item.failed else "Skipped"} ({item.reason})')
        if item.ignored_fragments:
            lines.append(f'    Nonsemantic fragments ignored: {item.ignored_fragments}')
        for number, (unit, outcome) in enumerate(zip(item.units, item.outcomes), 1):
            labels = [_fragment_label(fragment) for fragment in unit.fragments]
            lines.append(f'    Unit {number} ({unit.unit_id[:17]}): {" + ".join(labels)}')
            notes = dict(unit.notes)
            for fragment in unit.collapsed:
                # Grouping explanation only: the fragment joined as provenance, not text.
                lines.append(f'      Collapsed {_fragment_label(fragment)}: {notes.get(fragment.fragment_id, "-")}')
            lines.extend('    ' + line for line in _format_outcome(number, outcome)[1:])
    if summary.malformed:
        lines.extend(('', 'Unreadable stored lines:', *(f'  - {reason}' for reason in summary.malformed)))
    lines.extend((
        '', f'Raw items: {summary.observed}', f'DiscoveryUnits: {summary.unit_count}',
        f'Events: {summary.events}', f'Places: {summary.places}', f'Other: {summary.other}',
        f'Skipped units: {summary.skipped}',
        f'Items without units: {sum(not item.units and not item.failed for item in summary.items)}',
        f'Failed: {summary.failed}', '',
        'Nothing was persisted: candidates are transient; normalization is a separate step.',
    ))
    return '\n'.join(lines)


def format_evidence_summary(summary: EvidenceRunSummary) -> str:
    lines = [
        'GatherRadar media evidence run', '', f'Run id: {summary.run_id}',
        f'Source: {summary.source.name}', f'Raw items: {summary.raw_items}', '',
        f'Image assets: {summary.image_assets}',
        f'Carousel slides: {summary.carousel_slides}',
        f'Failed/unconfirmed carousel positions: {summary.capture_failed_slides}',
        f'Reel frames: {summary.reel_frames}', '',
        f'OCR succeeded: {summary.ocr_succeeded}', f'OCR empty: {summary.ocr_empty}',
        f'OCR failed: {summary.ocr_failed}', '',
        f'New evidence: {summary.new_evidence}',
        f'Existing evidence: {summary.existing_evidence}', f'Saved: {summary.output_path}',
    ]
    if summary.failures:
        lines.extend(('', 'Failures:', *(f'  - {reason}' for reason in summary.failures)))
    if summary.malformed:
        lines.extend(('', 'Unreadable stored lines:', *(f'  - {reason}' for reason in summary.malformed)))
    lines.extend(('', 'No semantic candidates were persisted.'))
    return '\n'.join(lines)


def run_evidence_instagram(args: argparse.Namespace) -> int:
    try:
        summary = run_instagram_evidence(
            args.source_id, config_path=args.config, data_dir=args.data_dir,
            limit=args.limit, max_carousel_slides=args.max_carousel_slides,
            max_reel_frames=args.max_reel_frames,
        )
    except (CollectorError, OcrError, StorageError, ValueError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f'error: source registry not found: {exc}', file=sys.stderr)
        return 1
    print(format_evidence_summary(summary))
    return 0


def format_auth_success(username: str) -> str:
    return "\n".join(
        [
            f"Authenticated as @{username}",
            "Session saved successfully.",
        ]
    )


def format_browser_auth_success() -> str:
    return "\n".join(
        [
            "Instagram browser session verified.",
            "Persistent profile saved.",
        ]
    )


def _wait_for_browser_login() -> None:
    print()
    print("Log in to Instagram in the opened Chrome window.")
    print("When the Instagram home page is visible, return here and press Enter.")
    input()
    print("Verifying session...")


def run_auth_instagram_browser(
    *, data_dir: str, wait_for_user: Callable[[], None] | None = None
) -> int:
    wait = wait_for_user if wait_for_user is not None else _wait_for_browser_login
    print("GatherRadar Instagram authentication")
    print()
    print("Opening Chrome with the GatherRadar browser profile:")
    print(browser_profile_path(data_dir))

    try:
        authenticate_browser_profile(data_dir=data_dir, wait_for_user=wait)
    except CollectorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("error: Instagram authentication was cancelled.", file=sys.stderr)
        return 1

    print()
    print(format_browser_auth_success())
    return 0


def _prompt_for_cookie() -> str:
    # getpass keeps the pasted Cookie header out of the terminal echo and, unlike a
    # CLI argument, out of shell history.
    return getpass.getpass("Paste Instagram Cookie header: ")


def run_auth_instagram_cookie(
    *, data_dir: str, cookie_prompt: Callable[[], str] | None = None
) -> int:
    prompt = cookie_prompt if cookie_prompt is not None else _prompt_for_cookie
    print("GatherRadar Instagram authentication (legacy cookie import)")
    cookie_header = prompt()

    print()
    print("Verifying session...")
    try:
        username, _session_path = create_session_from_cookie(cookie_header, data_dir=data_dir)
    except InstagramAuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print()
    print(format_auth_success(username))
    return 0


def run_ocr_check(args) -> int:
    """Report each engine's availability and, with --image, each engine's own reading."""
    from .ocr import OcrUnavailableError, build_ocr_provider
    engines = tuple(e.strip().lower() for e in args.engines.split(',') if e.strip()) if args.engines else None
    try:
        provider = build_ocr_provider(engines)
    except ValueError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    members = getattr(provider, 'providers', (provider,))
    usable = []
    for member in members:
        try:
            member.validate()
        except OcrUnavailableError as exc:
            print(f'{member.name}: unavailable — {exc}')
            continue
        usable.append(member)
        print(f'{member.name}: available ({member.version}; {member.config})')
    if args.image:
        for member in usable:
            result = member.recognize(args.image)
            print(f'--- {member.name}: {result.status.value}'
                  + (f' ({result.failure_reason})' if result.failure_reason else ''))
            if result.text:
                print(result.text)
    return 0 if usable else 1


def run_sources_list(args: argparse.Namespace) -> int:
    from .source_registry import SourceRegistry, overlay_path
    try:
        entries = SourceRegistry(args.config).entries()
    except ValueError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    overlay = overlay_path(args.config)
    print(f'Base: {args.config}')
    print(f'Overlay: {overlay if overlay is not None else "disabled"}'
          + ('' if overlay is None or overlay.exists() else ' (not created yet)'))
    for entry in entries:
        source = entry.source
        if source.archived and not args.all:
            continue
        state = ('archived' if source.archived else 'enabled' if source.enabled
                 else f'disabled ({source.disabled_reason or "config"})')
        print(f'{source.id}\t{source.source_type.value}\t{state}\t{entry.origin}\t{source.url}')
    runnable = [e.source.id for e in entries if e.source.enabled]
    print(f'All-enabled crawl would include {len(runnable)} source(s).')
    return 0


def run_telegram(args: argparse.Namespace) -> int:
    try:
        from .telegram_bot.lock import AlreadyRunningError
        from .telegram_bot.runner import StartupError, run_bot
        from .telegram_bot.settings import SettingsError, TelegramSettings
    except ImportError:
        print('error: python-telegram-bot is not installed. Run: python -m pip install -e .', file=sys.stderr)
        return 2
    try:
        settings = TelegramSettings.from_env()
    except SettingsError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    try:
        return run_bot(settings, config_path=args.config, data_dir=args.data_dir)
    except AlreadyRunningError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 3
    except StartupError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 4
    except ValueError:
        print('error: config/sources.yaml could not be read.', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    _cookie_prompt: Callable[[], str] | None = None,
    _wait_for_user: Callable[[], None] | None = None,
) -> int:
    _use_utf8_output()
    args = build_parser().parse_args(argv)

    if args.command in {'refresh', 'export', 'review', 'status'}:
        from .review.cli import run
        return run(args)

    if args.command == 'sheets' or (args.command == 'auth' and args.auth_type == 'google'):
        from .sheets.cli import run
        return run(args)

    if args.command == 'ocr':
        return run_ocr_check(args)

    if args.command == 'telegram':
        return run_telegram(args)

    if args.command == 'sources':
        return run_sources_list(args)

    if args.command == 'acceptance':
        from pathlib import Path
        from .orchestration.acceptance import build_bundle
        if not (Path(args.run_dir) / 'state.sqlite3').exists():
            print('error: --run-dir has no state.sqlite3 from a finished run', file=sys.stderr)
            return 2
        archive, report = build_bundle(
            Path(args.run_dir), data_dir=Path(args.data_dir), config_path=Path(args.config),
            cases_path=Path(args.cases), test_log=Path(args.test_log) if args.test_log else None,
            include_media=args.include_media, max_media=max(0, min(args.max_media, 200)),
            extra_files=tuple(Path(p) for p in args.include))
        workbook = report['workbook']
        print(f"Run: {report['run']['run_id']} status={report['run']['status']}")
        print('Workbook: ' + ('valid' if workbook.get('ok') else 'PROBLEMS: ' + ', '.join(
            name for name, ok in workbook.get('checks', {}).items() if not ok) if workbook.get('exists')
            else 'MISSING'))
        print(f"Rows: main={workbook.get('main_rows', 0)} schedule_review={workbook.get('schedule_review_rows', 0)}")
        statuses = [e['status'] for case in report['cases'] for e in case['entries']]
        print('Cases: ' + '; '.join(f'{name}={count}' for name, count in sorted(
            {s: statuses.count(s) for s in statuses}.items())))
        print(f'Review bundle: {archive}')
        return 0 if workbook.get('ok') else 1

    if args.command == 'diagnose':
        import json
        from pathlib import Path
        from .orchestration.session_schema_report import build_relationship_report, build_report
        value = (build_relationship_report(args.html) if args.diagnose_kind == 'jabama-timeslots'
                 else build_report(args.data_dir, args.html))
        report = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        if args.output:
            output = Path(args.output)
            if output.suffix.lower() != '.json' or output.exists() and output.is_dir():
                print('error: --output must be a .json file path', file=sys.stderr)
                return 2
            output.write_text(report + '\n', encoding='utf-8')
            print(f'report written: {output}')
        else:
            print(report)
        return 0

    if args.command == "auth":
        if args.legacy_cookie:
            return run_auth_instagram_cookie(data_dir=args.data_dir, cookie_prompt=_cookie_prompt)
        return run_auth_instagram_browser(data_dir=args.data_dir, wait_for_user=_wait_for_user)

    if args.limit < 1:
        print("error: --limit must be a positive integer", file=sys.stderr)
        return 2

    if args.command == 'canonicalize':
        from .deduplication.review import format_canonical_review
        from .orchestration.canonicalization_run import run_canonical_review
        try:
            review = run_canonical_review(args.sources or (), all_enabled=args.all_enabled,
                config_path=args.config, data_dir=args.data_dir, limit=args.limit,
                instagram_evidence=args.instagram_evidence)
        except (ValueError, OSError):
            print('error: invalid canonical review selection, limit, or registry', file=sys.stderr)
            return 1
        print(format_canonical_review(review))
        return 1 if (review.result.rejected or any(s.path_used == 'source_failed'
                     or any(d.startswith('discovery_failed:') for d in s.diagnostics) for s in review.sources)
                     or any(d.code in {'matching_failed', 'canonicalization_failed'} for d in review.result.diagnostics)) else 0

    if args.source_type == 'website':
        try:
            runner = run_website_discovery if args.command == 'extract' else run_website_collection
            summary = runner(args.source_id, config_path=args.config, data_dir=args.data_dir, limit=args.limit)
        except (CollectorError, StorageError, ValueError, OSError) as exc:
            print(f'error: {exc}', file=sys.stderr)
            return 1
        print(format_evidence_discovery_summary(summary) if args.command == 'extract' else format_summary(summary))
        if args.command == 'extract' and args.normalize:
            print(_normalized_review(summary))
        return 0

    if args.command == 'evidence':
        if args.max_carousel_slides < 1 or args.max_reel_frames < 1:
            print('error: media capture limits must be positive integers', file=sys.stderr)
            return 2
        return run_evidence_instagram(args)

    if args.command == "extract":
        return run_extract_instagram(args)

    collector = None
    if args.transport == TRANSPORT_INSTALOADER:
        collector = InstagramCollector(fetch_posts=InstaloaderPostFetcher(data_dir=args.data_dir))

    try:
        summary = run_instagram_collection(
            args.source_id,
            config_path=args.config,
            data_dir=args.data_dir,
            limit=args.limit,
            collector=collector,
        )
    except (CollectorError, StorageError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"error: source registry not found: {exc}", file=sys.stderr)
        return 1

    print(format_summary(summary))
    return 0
