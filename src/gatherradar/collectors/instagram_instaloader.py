from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

from .base import AuthenticationRequiredError, SourceAccessRestrictedError, SourceUnavailableError
from .instagram_auth import (
    NO_ACTIVE_SESSION_MESSAGE,
    SessionInvalidError,
    SessionNotFoundError,
    load_active_authenticated_loader,
)
from .instagram_dom import ORIGIN_POST, ORIGIN_REEL

# LEGACY transport, kept only while the browser transport is validated. Live runs showed
# Instaloader's Profile.from_username() hitting /api/v1/users/web_profile_info/ and
# receiving HTTP 429 even with a valid session. It is never the default and never used
# as an automatic fallback; it runs only through `collect instagram --transport instaloader`.


class InstaloaderPostFetcher:
    """Reads recent public posts and reels through the active authenticated
    Instaloader session, without downloading media.

    The active session belongs to whichever Instagram account the owner
    authenticated as (see `python -m gatherradar auth instagram --legacy-cookie`); it
    is loaded independently of `username`, the public source profile being crawled,
    so one login account can be reused across every approved source.
    """

    def __init__(
        self,
        *,
        data_dir: str | Path = "data",
        request_timeout: float = 30.0,
        max_connection_attempts: int = 1,
        load_session: Callable[[], Any] | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._request_timeout = request_timeout
        # A single attempt means a rejected request (e.g. HTTP 429) is reported
        # immediately instead of triggering Instaloader's own long rate-limit backoff.
        self._max_connection_attempts = max_connection_attempts
        self._load_session = load_session if load_session is not None else self._load_session_default

    def _load_session_default(self) -> Any:
        return load_active_authenticated_loader(data_dir=self._data_dir)

    def __call__(self, username: str, limit: int) -> Iterator[tuple[str, Any]]:
        import instaloader
        from instaloader import exceptions as instaloader_errors

        try:
            loader = self._load_session()
        except SessionNotFoundError as exc:
            raise AuthenticationRequiredError(NO_ACTIVE_SESSION_MESSAGE) from exc
        except SessionInvalidError as exc:
            raise AuthenticationRequiredError(
                f"the active Instagram session is no longer valid ({exc}); "
                "run 'python -m gatherradar auth instagram --legacy-cookie' again to refresh it"
            ) from exc

        loader.context.max_connection_attempts = self._max_connection_attempts
        loader.context.request_timeout = self._request_timeout

        try:
            profile = instaloader.Profile.from_username(loader.context, username)
            if profile.is_private:
                raise SourceAccessRestrictedError(
                    f"Instagram profile @{username} is private; "
                    "GatherRadar collects public content only"
                )
            yield from _tagged(profile.get_posts(), ORIGIN_POST, limit)
            yield from _tagged(profile.get_reels(), ORIGIN_REEL, limit)
        except instaloader_errors.InstaloaderException as exc:
            raise _translate_instaloader_error(username, exc) from exc


def _tagged(posts: Iterable[Any], origin: str, limit: int) -> Iterator[tuple[str, Any]]:
    for index, post in enumerate(posts):
        if index >= limit:
            break
        yield origin, post


def _looks_rate_limited(exc: Exception) -> bool:
    # Once Instaloader exhausts its retries it re-raises a plain ConnectionException
    # that still carries the original 429 text, so the status has to be read back out.
    text = str(exc).lower()
    return "429" in text or "too many requests" in text


def _translate_instaloader_error(username: str, exc: Exception) -> SourceUnavailableError:
    from instaloader import exceptions as errors

    if isinstance(exc, errors.ProfileNotExistsException):
        return SourceUnavailableError(
            f"Instagram profile @{username} was not found or is unavailable"
        )
    if isinstance(exc, errors.PrivateProfileNotFollowedException):
        return SourceAccessRestrictedError(
            f"Instagram profile @{username} is private; GatherRadar collects public content only"
        )
    if isinstance(exc, errors.TooManyRequestsException) or _looks_rate_limited(exc):
        # Report only what is actually known: Instagram returned HTTP 429 for this
        # request. That may reflect rate limiting or access policy; it does not by
        # itself prove an IP-level block, so no root cause is inferred here.
        return SourceAccessRestrictedError(
            f"Instagram refused the request with HTTP 429 (Too Many Requests): {exc}"
        )
    if isinstance(exc, (errors.LoginRequiredException, errors.QueryReturnedForbiddenException)):
        return SourceAccessRestrictedError(
            "Instagram refused anonymous access and asked for a logged-in session"
        )
    if isinstance(exc, errors.ConnectionException):
        return SourceUnavailableError(f"Could not reach Instagram: {exc}")
    return SourceUnavailableError(f"Instagram collection failed: {type(exc).__name__}: {exc}")


__all__ = ["InstaloaderPostFetcher"]
