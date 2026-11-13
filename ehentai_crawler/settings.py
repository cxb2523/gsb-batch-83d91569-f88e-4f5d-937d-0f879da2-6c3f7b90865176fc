"""Settings, resolved in this order (later wins):

1. the defaults below,
2. ``setting.ini`` (or the file given by ``--config`` / ``EHENTAI_CONFIG``),
3. environment variables ``EHENTAI_<KEY>``,
4. command-line flags ``--<key>`` (not for cookies, they would end up in shell history).

Every setting is declared once on :class:`Settings`; the INI key, the
environment variable and the CLI flag are all derived from the field name.
"""

from __future__ import annotations

import configparser
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import Field, dataclass, field, fields
from functools import cache
from pathlib import Path
from typing import Any, get_type_hints
from urllib.parse import urlsplit

from . import __version__
from .errors import SettingsError

log = logging.getLogger(__name__)

ENV_PREFIX = "EHENTAI_"
CONFIG_ENV = f"{ENV_PREFIX}CONFIG"
DEFAULT_CONFIG_PATH = Path("setting.ini")
PROJECT_URL = "https://github.com/NatLee/ehentai-crawler"
DEFAULT_USER_AGENT = f"ehentai-crawler/{__version__} (+{PROJECT_URL})"
FETCHERS = ("http", "browser")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

#: Cookie that tells the site to skip its "Content Warning" interstitial.
CONTENT_WARNING_COOKIE = {"nw": "1"}

# --- Compatibility with setting.ini files written for the 2019 version --------------
# Kept so an old setting.ini keeps working unchanged. Safe to delete once nobody
# runs a pre-2.0 setting.ini any more; removing it only turns these into warnings.
#: The old crawler built list URLs from these; the site now pages with "next" links.
LEGACY_IGNORED_KEYS = frozenset({("hentaiurl", "ehentai_list"), ("hentaiurl", "exhentai_list")})


def _is_placeholder(value: str) -> bool:
    """The old example file shipped ``<YOUR_MEMBER_ID>``-style placeholders."""
    return value.startswith("<") and value.endswith(">")


# -------------------------------------------------------------------------------------


def _meta(
    section: str,
    help: str,
    *,
    cli: bool = True,
    secret: bool = False,
    choices: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Field metadata: INI section, help text, whether a CLI flag exists, secrecy, allowed values."""
    return {"section": section, "help": help, "cli": cli, "secret": secret, "choices": choices}


@dataclass(frozen=True)
class Settings:
    ex_mode: bool = field(
        default=True, metadata=_meta("Mode", "Crawl ExHentai instead of E-Hentai (needs the two login cookies).")
    )
    fetcher: str = field(
        default="http",
        metadata=_meta(
            "Mode",
            "How pages are loaded: 'http' (plain requests) or 'browser' "
            "(Chrome through Selenium, needs pip install 'ehentai-crawler[browser]').",
            choices=FETCHERS,
        ),
    )
    headless: bool = field(default=False, metadata=_meta("Mode", "Hide the Chrome window (browser fetcher only)."))
    ehentai_index: str = field(
        default="https://e-hentai.org/", metadata=_meta("HentaiUrl", "E-Hentai front page.", cli=False)
    )
    ehentai_gallery: str = field(
        default="https://e-hentai.org/g/", metadata=_meta("HentaiUrl", "E-Hentai gallery URL prefix.", cli=False)
    )
    exhentai_index: str = field(
        default="https://exhentai.org/", metadata=_meta("HentaiUrl", "ExHentai front page.", cli=False)
    )
    exhentai_gallery: str = field(
        default="https://exhentai.org/g/", metadata=_meta("HentaiUrl", "ExHentai gallery URL prefix.", cli=False)
    )
    ipb_member_id: str = field(
        default="",
        repr=False,
        metadata=_meta("ExHentaiAccess", "ExHentai login cookie ipb_member_id.", cli=False, secret=True),
    )
    ipb_pass_hash: str = field(
        default="",
        repr=False,
        metadata=_meta("ExHentaiAccess", "ExHentai login cookie ipb_pass_hash.", cli=False, secret=True),
    )
    number_of_thread: int = field(default=24, metadata=_meta("Parallel", "Galleries crawled at the same time."))
    request_delay: float = field(
        default=1.0,
        metadata=_meta(
            "Politeness",
            "Minimum seconds between two requests to the same host; a random extra of up to the same amount is added.",
        ),
    )
    max_retries: int = field(
        default=5, metadata=_meta("Politeness", "Retries for timeouts and server errors, with exponential backoff.")
    )
    timeout: float = field(default=60.0, metadata=_meta("Politeness", "Seconds to wait for one response."))
    user_agent: str = field(
        default=DEFAULT_USER_AGENT,
        metadata=_meta(
            "Politeness", "User-Agent of plain HTTP requests (the browser fetcher keeps Chrome's own).", cli=False
        ),
    )
    image_folder_path: Path = field(
        default=Path("img"), metadata=_meta("ImageFolder", "Images go to <folder>/<gallery id>/<file name>.")
    )
    database_path: Path = field(
        default=Path("list.db"), metadata=_meta("Database", "SQLite file with the gallery list and metadata.")
    )
    log_level: str = field(default="INFO", metadata=_meta("Logging", "How chatty the log is.", choices=LOG_LEVELS))

    def __post_init__(self) -> None:
        checks = [
            (self.number_of_thread >= 1, "NUMBER_OF_THREAD must be at least 1"),
            (self.request_delay >= 0, "REQUEST_DELAY cannot be negative"),
            (self.max_retries >= 0, "MAX_RETRIES cannot be negative"),
            (self.timeout > 0, "TIMEOUT must be positive"),
            (self.fetcher in FETCHERS, f"FETCHER must be one of {', '.join(FETCHERS)}"),
            (self.log_level in LOG_LEVELS, f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}"),
        ]
        for name in ("ehentai_index", "ehentai_gallery", "exhentai_index", "exhentai_gallery"):
            parts = urlsplit(getattr(self, name))
            checks.append((parts.scheme in ("http", "https") and bool(parts.hostname), f"{name.upper()} is not a URL"))
        for ok, message in checks:
            if not ok:
                raise SettingsError(message)

    @property
    def index_url(self) -> str:
        """Front page of the site selected by ``EX_MODE``."""
        return self.exhentai_index if self.ex_mode else self.ehentai_index

    @property
    def gallery_url(self) -> str:
        """Gallery URL prefix of the site selected by ``EX_MODE``."""
        return self.exhentai_gallery if self.ex_mode else self.ehentai_gallery

    @property
    def has_login_cookies(self) -> bool:
        return bool(self.ipb_member_id and self.ipb_pass_hash)

    def cookies_by_host(self) -> dict[str, dict[str, str]]:
        """Cookies to send, per host. Login cookies only ever go to ExHentai."""
        jar: dict[str, dict[str, str]] = {}
        for url in (self.ehentai_index, self.ehentai_gallery, self.exhentai_index, self.exhentai_gallery):
            jar.setdefault(_host(url), dict(CONTENT_WARNING_COOKIE))
        if self.has_login_cookies:
            for url in (self.exhentai_index, self.exhentai_gallery):
                jar[_host(url)].update(ipb_member_id=self.ipb_member_id, ipb_pass_hash=self.ipb_pass_hash)
        return jar

    def check_access(self, url: str) -> None:
        """Fail early with a clear message when ``url`` needs cookies we do not have."""
        exhentai_hosts = {_host(self.exhentai_index), _host(self.exhentai_gallery)}
        if _host(url) in exhentai_hosts and not self.has_login_cookies:
            raise SettingsError(
                f"{url} needs the ExHentai login cookies. Set {ENV_PREFIX}IPB_MEMBER_ID and "
                f"{ENV_PREFIX}IPB_PASS_HASH (or [ExHentaiAccess] in setting.ini), "
                "or use E-Hentai with --no-ex-mode."
            )


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def setting_fields() -> tuple[Field[Any], ...]:
    return fields(Settings)


@cache
def setting_types() -> dict[str, type]:
    return get_type_hints(Settings)


def env_name(f: Field[Any]) -> str:
    return f"{ENV_PREFIX}{f.name.upper()}"


def cli_flag(f: Field[Any]) -> str:
    return "--" + f.name.replace("_", "-")


_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def parse_bool(text: str) -> bool:
    value = text.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"expected yes/no, true/false, on/off or 1/0, got {text!r}")


_CONVERTERS: dict[type, Callable[[str], Any]] = {bool: parse_bool, int: int, float: float, str: str, Path: Path}


def converter(f: Field[Any]) -> Callable[[str], Any]:
    """Turn the text form of a setting into its typed value (used for INI, env and CLI)."""
    base = _CONVERTERS[setting_types()[f.name]]
    choices: tuple[str, ...] | None = f.metadata["choices"]
    if choices is None:
        return base

    def pick(text: str) -> str:
        for choice in choices:
            if text.strip().lower() == choice.lower():
                return choice
        raise ValueError(f"expected one of {', '.join(choices)}, got {text!r}")

    return pick


def _convert(f: Field[Any], raw: str, source: str) -> Any:
    raw = raw.strip()
    if f.metadata["secret"] and _is_placeholder(raw):
        return ""
    try:
        return converter(f)(raw)
    except ValueError as exc:
        shown = "" if f.metadata["secret"] else f": {exc}"
        raise SettingsError(f"{source} is invalid{shown}") from None


def _read_ini(path: Path) -> dict[str, Any]:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, UnicodeDecodeError, configparser.Error) as exc:
        raise SettingsError(f"cannot read {path}: {exc}") from None

    by_key = {(str(f.metadata["section"]).lower(), f.name): f for f in setting_fields()}
    values: dict[str, Any] = {}
    for section in parser.sections():
        for key, raw in parser.items(section):
            where = (section.lower(), key.lower())
            if where in LEGACY_IGNORED_KEYS:
                log.debug("%s: [%s] %s is no longer used, ignoring it", path, section, key.upper())
                continue
            f = by_key.get(where)
            if f is None:
                log.warning("%s: unknown setting [%s] %s, ignoring it", path, section, key.upper())
                continue
            values[f.name] = _convert(f, raw, f"{path} [{section}] {key.upper()}")
    return values


def _read_env(env: Mapping[str, str]) -> dict[str, Any]:
    return {f.name: _convert(f, env[env_name(f)], env_name(f)) for f in setting_fields() if env_name(f) in env}


def load_settings(
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> Settings:
    """Build :class:`Settings` from defaults, the INI file, the environment and CLI overrides."""
    env = os.environ if env is None else env
    explicit = config_path is not None or CONFIG_ENV in env
    path = config_path or Path(env.get(CONFIG_ENV, str(DEFAULT_CONFIG_PATH)))

    values: dict[str, Any] = {}
    if path.is_file():
        values.update(_read_ini(path))
    elif explicit:
        raise SettingsError(f"config file not found: {path}")
    values.update(_read_env(env))
    values.update({name: value for name, value in (overrides or {}).items() if value is not None})
    return Settings(**values)
