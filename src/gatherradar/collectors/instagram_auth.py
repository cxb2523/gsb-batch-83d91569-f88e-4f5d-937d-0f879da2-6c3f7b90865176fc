from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Authenticated session handling for the Instagram collector, isolated from the
# domain models per AGENTS.md.
#
# The authenticated Instagram account (the "login account", e.g. instaloader.crawler)
# and the public source being crawled (e.g. davvvat) are two different concepts. One
# authenticated local session is saved and reused to collect from every approved
# public source; the collector never needs to know the login account in advance.
#
# Authentication is cookie-based rather than password-based: this account has
# previously hit Instagram's "Checkpoint required" flow during interactive_login(),
# so the primary path instead imports a Cookie request-header string from an
# already-logged-in browser session, following the same
# update_cookies()/test_login() sequence Instaloader's own browser-import feature
# uses. The cookie is only ever accepted through an interactive, hidden prompt
# (never a CLI argument, which would land in shell history) and is never printed,
# logged, or persisted; only the resulting Instaloader session is saved to disk.

LoaderFactory = Callable[[], Any]

SESSION_SUBDIR = "sessions"
ACTIVE_SESSION_FILENAME = "instagram-active.json"

NO_ACTIVE_SESSION_MESSAGE = (
    "Authenticated Instagram session is not configured.\n"
    "Run:\n"
    "python -m gatherradar auth instagram"
)


class InstagramAuthError(Exception):
    """Base class for Instagram authentication/session failures."""


class InvalidCookieError(InstagramAuthError):
    """The pasted Instagram Cookie header could not be parsed into cookies."""


class LoginFailedError(InstagramAuthError):
    """Instagram did not recognize the pasted cookie as an authenticated session."""


class SessionNotFoundError(InstagramAuthError):
    """No active authenticated Instagram session has been configured yet."""


class SessionInvalidError(InstagramAuthError):
    """A saved session exists but failed to load or no longer authenticates."""


def _default_loader_factory(*, quiet: bool) -> Any:
    import instaloader

    return instaloader.Instaloader(
        quiet=quiet,
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        iphone_support=False,
    )


def _usernames_match(expected: str, actual: str | None) -> bool:
    return isinstance(actual, str) and actual.strip().lower() == expected.strip().lower()


def session_path(username: str, data_dir: str | Path = "data") -> Path:
    """Deterministic local path for one login account's saved Instaloader session.

    Matches the `data/sessions/instagram-<username>.session` layout. `username` here
    is always the authenticated login account, never a crawled source.
    """
    normalized = (username or "").strip().lower()
    if not normalized:
        raise ValueError("username must not be empty")
    return Path(data_dir) / SESSION_SUBDIR / f"instagram-{normalized}.session"


def active_session_metadata_path(data_dir: str | Path = "data") -> Path:
    return Path(data_dir) / SESSION_SUBDIR / ACTIVE_SESSION_FILENAME


def parse_cookie_header(cookie_header: str) -> dict[str, str]:
    """Parse a raw `Cookie:` request-header value (e.g. copied from a browser's
    devtools) into a name -> value mapping.

    Raises InvalidCookieError if the header is empty, has no `name=value` pairs, or
    is missing `sessionid`, the cookie that actually carries the login.
    """
    if not isinstance(cookie_header, str) or not cookie_header.strip():
        raise InvalidCookieError("cookie header must not be empty")

    cookies: dict[str, str] = {}
    for segment in cookie_header.strip().split(";"):
        segment = segment.strip()
        if not segment:
            continue
        if "=" not in segment:
            raise InvalidCookieError(f"malformed cookie segment: {segment!r}")
        name, _, value = segment.partition("=")
        name = name.strip()
        value = value.strip()
        if not name:
            raise InvalidCookieError(f"malformed cookie segment: {segment!r}")
        cookies[name] = value

    if not cookies:
        raise InvalidCookieError("cookie header contained no usable cookies")
    if "sessionid" not in cookies:
        raise InvalidCookieError("cookie header is missing the 'sessionid' cookie")

    return cookies


def _write_active_session_metadata(
    username: str, session_file: Path, *, data_dir: str | Path
) -> Path:
    meta_path = active_session_metadata_path(data_dir)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps({"username": username, "session_file": session_file.name}, indent=2),
        encoding="utf-8",
    )
    return meta_path


def create_session_from_cookie(
    cookie_header: str,
    *,
    data_dir: str | Path = "data",
    loader_factory: LoaderFactory | None = None,
) -> tuple[str, Path]:
    """Verify a pasted Instagram Cookie header and save it as the active local
    session, reusable to collect from any approved public source.

    Never accepts the cookie as anything but this in-memory argument (the CLI only
    ever obtains it through a hidden, interactive prompt) and never logs, prints, or
    persists the raw cookie; only the resulting Instaloader session is written to
    disk. Returns the verified login username and the path of its saved session.
    Raises InvalidCookieError if the header cannot be parsed, or LoginFailedError if
    Instagram does not recognize the cookies as a logged-in session.
    """
    cookies = parse_cookie_header(cookie_header)

    build_loader = loader_factory or (lambda: _default_loader_factory(quiet=True))
    loader = build_loader()

    loader.context.update_cookies(cookies)

    try:
        verified_username = loader.test_login()
    except Exception as exc:
        raise LoginFailedError(f"Instagram did not accept the pasted cookie: {exc}") from exc

    if not isinstance(verified_username, str) or not verified_username.strip():
        raise LoginFailedError(
            "Instagram did not recognize the pasted cookie as a logged-in session"
        )
    verified_username = verified_username.strip()

    # update_cookies() alone does not mark the context as logged in; Instaloader's
    # own session persistence keys off context.username, so it must be set from the
    # verified identity before the session can be saved.
    loader.context.username = verified_username

    path = session_path(verified_username, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    loader.save_session_to_file(str(path))

    _write_active_session_metadata(verified_username, path, data_dir=data_dir)

    return verified_username, path


def load_active_session_metadata(data_dir: str | Path = "data") -> dict[str, str]:
    """Read which login account's session is currently active, without touching
    Instagram. Raises SessionNotFoundError if `auth instagram` has never been run,
    or SessionInvalidError if the metadata file is corrupt or incomplete."""
    meta_path = active_session_metadata_path(data_dir)
    if not meta_path.exists():
        raise SessionNotFoundError(NO_ACTIVE_SESSION_MESSAGE)

    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SessionInvalidError(
            f"active Instagram session metadata at {meta_path} is corrupt: {exc}"
        ) from exc

    username = data.get("username") if isinstance(data, dict) else None
    if not isinstance(username, str) or not username.strip():
        raise SessionInvalidError(
            f"active Instagram session metadata at {meta_path} is missing a username"
        )

    session_file = data.get("session_file") if isinstance(data, dict) else None
    return {"username": username.strip(), "session_file": session_file}


def load_active_authenticated_loader(
    *,
    data_dir: str | Path = "data",
    loader_factory: LoaderFactory | None = None,
) -> Any:
    """Load and verify the currently active authenticated Instagram session.

    This is independent of any particular public source: the same login account's
    session is reused to crawl every approved source. Raises SessionNotFoundError if
    no session has been configured via `auth instagram`, or SessionInvalidError if
    the saved session file is missing, fails to load, or no longer authenticates.
    """
    metadata = load_active_session_metadata(data_dir)
    username = metadata["username"]
    path = session_path(username, data_dir)
    if not path.exists():
        raise SessionInvalidError(
            f"active Instagram session file for @{username} is missing: {path}"
        )

    build_loader = loader_factory or (lambda: _default_loader_factory(quiet=True))
    loader = build_loader()

    try:
        loader.load_session_from_file(username, str(path))
    except Exception as exc:  # session files can fail to load in ways Instaloader
        # itself does not type consistently (corrupt pickle, permission errors, an
        # old format); any such failure means the session cannot be trusted.
        raise SessionInvalidError(
            f"Instagram session for @{username} could not be loaded: {exc}"
        ) from exc

    try:
        verified_username = loader.test_login()
    except Exception as exc:
        raise SessionInvalidError(
            f"Instagram session for @{username} failed verification: {exc}"
        ) from exc

    if not _usernames_match(username, verified_username):
        raise SessionInvalidError(
            f"Instagram session for @{username} is no longer valid or has expired"
        )

    return loader


__all__ = [
    "InstagramAuthError",
    "InvalidCookieError",
    "LoginFailedError",
    "SessionNotFoundError",
    "SessionInvalidError",
    "NO_ACTIVE_SESSION_MESSAGE",
    "session_path",
    "active_session_metadata_path",
    "parse_cookie_header",
    "create_session_from_cookie",
    "load_active_session_metadata",
    "load_active_authenticated_loader",
]
