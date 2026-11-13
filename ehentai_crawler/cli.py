"""Command line. The six options of the 2019 version keep their names and meaning;
the settings flags are generated from :class:`~ehentai_crawler.settings.Settings`."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from tqdm.contrib.logging import logging_redirect_tqdm

from . import __version__
from .crawl import crawl_galleries, crawl_list, crawl_single, resolve_gallery_url
from .db import Database
from .errors import BannedError, CrawlerError, SettingsError
from .fetch import Fetcher, open_fetcher
from .settings import (
    CONFIG_ENV,
    DEFAULT_CONFIG_PATH,
    ENV_PREFIX,
    Settings,
    cli_flag,
    converter,
    env_name,
    load_settings,
    parse_bool,
    setting_fields,
    setting_types,
)

log = logging.getLogger("ehentai_crawler")

PROG = "ehentai-crawler"
#: Same log line format as the 2019 version.
LOG_FORMAT = "%(asctime)s - %(levelname)s : %(message)s"
EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130
#: The 2019 version called exit(-1) when it got banned while crawling galleries (255 on POSIX).
EXIT_BANNED = 255

DESCRIPTION = (
    "EHentai Crawler: build the gallery list first (-c), then crawl tags only (-to) "
    "or tags and images (-p) for every gallery in it. -cu downloads one gallery by URL, "
    "-ds merges a database crawled on another machine. Run with no options to see this help."
)
EPILOG = (
    f"Settings are read from, later wins: built-in defaults, {DEFAULT_CONFIG_PATH} (or --config / "
    f"{CONFIG_ENV}), environment variables {ENV_PREFIX}<KEY>, then the flags above. "
    f"The ExHentai cookies are only read from the settings file or from {ENV_PREFIX}IPB_MEMBER_ID "
    f"and {ENV_PREFIX}IPB_PASS_HASH, never from flags. Be gentle with the site: the defaults wait "
    "1-2 s between requests to it."
)

ACTION_DESTS = ("crawl_list", "update_crawl_list", "crawl_each_page", "crawl_tag_only")


def _arg_type(convert: Callable[[str], Any]) -> Callable[[str], Any]:
    def wrapped(text: str) -> Any:
        try:
            return convert(text)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from None

    return wrapped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description=DESCRIPTION, epilog=EPILOG)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    actions = parser.add_argument_group("what to crawl (run in this order when several are given)")
    flag: dict[str, Any] = {
        "nargs": "?",
        "const": True,
        "default": False,
        "type": _arg_type(parse_bool),
        "metavar": "BOOL",
    }
    actions.add_argument(
        "-c",
        "--crawl_list",
        **flag,
        help="Crawl the gallery list from the front page; stop at galleries already stored.",
    )
    actions.add_argument(
        "-u", "--update_crawl_list", **flag, help="Crawl the whole gallery list again and refresh every stored row."
    )
    actions.add_argument(
        "-p", "--crawl_each_page", **flag, help="Crawl tags and download images of every stored gallery that needs it."
    )
    actions.add_argument(
        "-to", "--crawl_tag_only", **flag, help="Like -p, but only tags, favourites and ratings; no images."
    )
    actions.add_argument(
        "-cu",
        "--crawl_with_url",
        dest="gallery_url",
        metavar="GALLERY_URL",
        help="Download one gallery by URL into the image folder (not stored in the database).",
    )
    actions.add_argument(
        "-ds",
        "--database_sync",
        dest="other_database_path",
        metavar="OTHER_DATABASE_PATH",
        type=Path,
        help="Merge another crawler's database into this one.",
    )

    group = parser.add_argument_group("settings")
    group.add_argument(
        "--config", type=Path, metavar="PATH", help=f"settings file [{CONFIG_ENV}, default: ./{DEFAULT_CONFIG_PATH}]"
    )
    for f in setting_fields():
        if not f.metadata["cli"]:
            continue
        common: dict[str, Any] = {
            "dest": f.name,
            "default": None,
            "help": f"{f.metadata['help']} [{env_name(f)}, default: {f.default}]",
        }
        if setting_types()[f.name] is bool:
            group.add_argument(cli_flag(f), action=argparse.BooleanOptionalAction, **common)
        else:
            group.add_argument(
                cli_flag(f),
                type=_arg_type(converter(f)),
                choices=f.metadata["choices"],
                metavar=None if f.metadata["choices"] else f.name.upper(),
                **common,
            )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not (any(getattr(args, dest) for dest in ACTION_DESTS) or args.gallery_url or args.other_database_path):
        parser.print_help()
        return EXIT_OK

    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    overrides = {f.name: getattr(args, f.name) for f in setting_fields() if f.metadata["cli"]}
    try:
        settings = load_settings(args.config, overrides=overrides)
        logging.getLogger().setLevel(settings.log_level)
        log.debug("settings: %r", settings)  # the cookies are left out of the repr
        with logging_redirect_tqdm():
            _run(args, settings)
    except SettingsError as exc:
        parser.exit(EXIT_USAGE, f"{PROG}: error: {exc}\n")
    except BannedError as exc:
        log.error("%s. Finished galleries are saved; run the same command again later to continue.", exc)
        return EXIT_BANNED
    except CrawlerError as exc:
        log.error("%s", exc)
        return EXIT_ERROR
    except KeyboardInterrupt:
        log.warning("interrupted; run the same command again to continue where it stopped")
        return EXIT_INTERRUPTED
    return EXIT_OK


def _check_before_running(args: argparse.Namespace, settings: Settings) -> None:
    """Catch bad input before any file is created or any request is sent."""
    if args.crawl_list or args.update_crawl_list:
        settings.check_access(settings.index_url)
    if args.crawl_each_page or args.crawl_tag_only:
        settings.check_access(settings.gallery_url)
    if args.gallery_url:
        settings.check_access(resolve_gallery_url(settings, args.gallery_url)[1])
    if args.other_database_path and not args.other_database_path.is_file():
        raise SettingsError(f"database to merge not found: {args.other_database_path}")


def _run(args: argparse.Namespace, settings: Settings) -> None:
    _check_before_running(args, settings)
    crawl_pages = bool(args.crawl_each_page or args.crawl_tag_only)
    crawl_index = bool(args.crawl_list or args.update_crawl_list)
    with ExitStack() as stack:
        db: Database | None = None
        if crawl_index or crawl_pages or args.other_database_path:
            db = stack.enter_context(Database(settings.database_path))
        fetcher: Fetcher | None = None
        if crawl_index or crawl_pages or args.gallery_url:
            fetcher = stack.enter_context(open_fetcher(settings))

        if crawl_index:
            assert db and fetcher
            listed = crawl_list(fetcher, db, settings.index_url, update_all=bool(args.update_crawl_list))
            log.info("list done: %d page(s) read, %d added, %d updated", listed.pages, listed.added, listed.updated)

        if crawl_pages:
            assert db and fetcher
            crawled = crawl_galleries(fetcher, db, settings, tag_only=bool(args.crawl_tag_only))
            log.info(
                "galleries done: %d crawled (%d with every image), %d removed, %d failed%s",
                crawled.crawled,
                crawled.complete,
                crawled.removed,
                crawled.failed,
                "; image quota used up, the rest got tags only" if crawled.quota_exceeded else "",
            )

        if args.gallery_url:
            assert fetcher
            single = crawl_single(fetcher, settings, args.gallery_url)
            if single.download is not None:
                d = single.download
                log.info(
                    "gallery %s: %d of %d images saved, %d already there, %d failed -> %s",
                    single.gallery_id,
                    d.saved,
                    d.total,
                    d.skipped,
                    d.failed,
                    settings.image_folder_path / str(single.gallery_id),
                )

        if args.other_database_path:
            assert db
            other_path: Path = args.other_database_path
            with Database(other_path) as other:
                merged = db.merge_from(other)
            log.info(
                "merged %s: list %d added, %d updated; pages %d added, %d updated",
                other_path,
                merged.list_added,
                merged.list_updated,
                merged.page_added,
                merged.page_updated,
            )
