import json
import tempfile
import unittest
from pathlib import Path

from gatherradar.collectors.instagram_auth import (
    InvalidCookieError,
    LoginFailedError,
    NO_ACTIVE_SESSION_MESSAGE,
    SessionInvalidError,
    SessionNotFoundError,
    active_session_metadata_path,
    create_session_from_cookie,
    load_active_authenticated_loader,
    load_active_session_metadata,
    parse_cookie_header,
    session_path,
)

RAW_COOKIE = (
    "sessionid=abc123; csrftoken=xyz789; ds_user_id=1234567890; mid=Zzzzzz-example"
)


class FakeLoader:
    """Stand-in for instaloader.Instaloader matching only the methods GatherRadar
    calls, so tests never import or contact the real Instaloader/Instagram."""

    def __init__(
        self,
        *,
        load_error: Exception | None = None,
        test_login_error: Exception | None = None,
        verified_username: str | None = "instaloader.crawler",
    ) -> None:
        self._load_error = load_error
        self._test_login_error = test_login_error
        self._verified_username = verified_username
        self.context = FakeContext()
        self.load_session_calls: list[tuple[str, str]] = []
        self.save_session_calls: list[str] = []

    def load_session_from_file(self, username: str, filename: str) -> None:
        self.load_session_calls.append((username, filename))
        if self._load_error is not None:
            raise self._load_error

    def test_login(self) -> str | None:
        if self._test_login_error is not None:
            raise self._test_login_error
        return self._verified_username

    def save_session_to_file(self, filename: str) -> None:
        self.save_session_calls.append(filename)
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        Path(filename).write_text("fake-session", encoding="utf-8")


class FakeContext:
    def __init__(self) -> None:
        self.update_cookies_calls: list[dict[str, str]] = []
        self.username: str | None = None

    def update_cookies(self, cookies: dict[str, str]) -> None:
        self.update_cookies_calls.append(cookies)


class CookieHeaderParsingTests(unittest.TestCase):
    def test_parses_a_typical_cookie_header(self) -> None:
        cookies = parse_cookie_header(
            "sessionid=abc123; csrftoken=xyz789; ds_user_id=42; mid=zzz"
        )
        self.assertEqual(
            cookies,
            {"sessionid": "abc123", "csrftoken": "xyz789", "ds_user_id": "42", "mid": "zzz"},
        )

    def test_tolerates_extra_whitespace_around_pairs(self) -> None:
        cookies = parse_cookie_header("  sessionid = abc123 ;  csrftoken=xyz789  ")
        self.assertEqual(cookies, {"sessionid": "abc123", "csrftoken": "xyz789"})

    def test_empty_string_is_rejected(self) -> None:
        with self.assertRaises(InvalidCookieError):
            parse_cookie_header("")

    def test_whitespace_only_is_rejected(self) -> None:
        with self.assertRaises(InvalidCookieError):
            parse_cookie_header("   ")

    def test_segment_without_equals_sign_is_rejected(self) -> None:
        with self.assertRaises(InvalidCookieError):
            parse_cookie_header("sessionid=abc123; not-a-pair; csrftoken=xyz789")

    def test_missing_sessionid_is_rejected(self) -> None:
        with self.assertRaises(InvalidCookieError):
            parse_cookie_header("csrftoken=xyz789; ds_user_id=42")

    def test_pasted_cookie_value_never_appears_in_the_error_for_a_bad_segment(self) -> None:
        secret_looking_segment = "totally-not-a-pair-SECRETVALUE"
        try:
            parse_cookie_header(f"sessionid=abc123; {secret_looking_segment}")
        except InvalidCookieError as exc:
            # The malformed segment's *shape* may be echoed back to help debugging,
            # but no cookie *value* (e.g. sessionid's) is ever included.
            self.assertNotIn("abc123", str(exc))


class CreateSessionFromCookieTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)

    def test_successful_cookie_login_saves_and_verifies_the_session(self) -> None:
        fake = FakeLoader(verified_username="instaloader.crawler")

        username, path = create_session_from_cookie(
            RAW_COOKIE, data_dir=self.data_dir, loader_factory=lambda: fake
        )

        self.assertEqual(username, "instaloader.crawler")
        self.assertEqual(path, session_path("instaloader.crawler", self.data_dir))
        self.assertTrue(path.exists())

    def test_cookie_header_is_parsed_and_handed_to_update_cookies(self) -> None:
        fake = FakeLoader()

        create_session_from_cookie(RAW_COOKIE, data_dir=self.data_dir, loader_factory=lambda: fake)

        self.assertEqual(len(fake.context.update_cookies_calls), 1)
        self.assertEqual(fake.context.update_cookies_calls[0]["sessionid"], "abc123")

    def test_verified_username_from_test_login_becomes_the_context_username(self) -> None:
        fake = FakeLoader(verified_username="instaloader.crawler")

        create_session_from_cookie(RAW_COOKIE, data_dir=self.data_dir, loader_factory=lambda: fake)

        self.assertEqual(fake.context.username, "instaloader.crawler")

    def test_malformed_cookie_header_raises_invalid_cookie_before_touching_the_loader(
        self,
    ) -> None:
        fake = FakeLoader()

        with self.assertRaises(InvalidCookieError):
            create_session_from_cookie("not-a-cookie-header", data_dir=self.data_dir, loader_factory=lambda: fake)

        self.assertEqual(fake.context.update_cookies_calls, [])

    def test_test_login_returning_none_raises_login_failed(self) -> None:
        fake = FakeLoader(verified_username=None)

        with self.assertRaises(LoginFailedError):
            create_session_from_cookie(RAW_COOKIE, data_dir=self.data_dir, loader_factory=lambda: fake)

    def test_test_login_raising_raises_login_failed(self) -> None:
        fake = FakeLoader(test_login_error=ConnectionError("network down"))

        with self.assertRaises(LoginFailedError):
            create_session_from_cookie(RAW_COOKIE, data_dir=self.data_dir, loader_factory=lambda: fake)

    def test_failed_login_writes_no_session_or_active_metadata(self) -> None:
        fake = FakeLoader(verified_username=None)

        with self.assertRaises(LoginFailedError):
            create_session_from_cookie(RAW_COOKIE, data_dir=self.data_dir, loader_factory=lambda: fake)

        self.assertFalse(active_session_metadata_path(self.data_dir).exists())

    def test_active_session_metadata_records_username_and_session_file(self) -> None:
        fake = FakeLoader(verified_username="instaloader.crawler")

        _, path = create_session_from_cookie(
            RAW_COOKIE, data_dir=self.data_dir, loader_factory=lambda: fake
        )

        meta_path = active_session_metadata_path(self.data_dir)
        self.assertTrue(meta_path.exists())
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["username"], "instaloader.crawler")
        self.assertEqual(metadata["session_file"], path.name)

    def test_active_session_metadata_contains_no_secret_values(self) -> None:
        fake = FakeLoader(verified_username="instaloader.crawler")

        create_session_from_cookie(RAW_COOKIE, data_dir=self.data_dir, loader_factory=lambda: fake)

        raw = active_session_metadata_path(self.data_dir).read_text(encoding="utf-8")
        self.assertNotIn("abc123", raw)  # the sessionid cookie value
        self.assertNotIn("sessionid", raw)


class LoadActiveSessionMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)

    def test_missing_metadata_raises_session_not_found_with_actionable_message(self) -> None:
        with self.assertRaises(SessionNotFoundError) as ctx:
            load_active_session_metadata(self.data_dir)
        self.assertEqual(str(ctx.exception), NO_ACTIVE_SESSION_MESSAGE)

    def test_corrupt_metadata_raises_session_invalid(self) -> None:
        meta_path = active_session_metadata_path(self.data_dir)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text("{not json}", encoding="utf-8")

        with self.assertRaises(SessionInvalidError):
            load_active_session_metadata(self.data_dir)

    def test_metadata_without_username_raises_session_invalid(self) -> None:
        meta_path = active_session_metadata_path(self.data_dir)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps({"session_file": "instagram-x.session"}), encoding="utf-8")

        with self.assertRaises(SessionInvalidError):
            load_active_session_metadata(self.data_dir)

    def test_valid_metadata_returns_username(self) -> None:
        meta_path = active_session_metadata_path(self.data_dir)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps({"username": "instaloader.crawler", "session_file": "x.session"}),
            encoding="utf-8",
        )

        metadata = load_active_session_metadata(self.data_dir)
        self.assertEqual(metadata["username"], "instaloader.crawler")


class LoadActiveAuthenticatedLoaderTests(unittest.TestCase):
    """The authenticated LOGIN account (e.g. instaloader.crawler) is independent of
    whatever public source (e.g. davvvat) the collector later targets."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)

    def _activate(self, username: str = "instaloader.crawler") -> Path:
        session_file = session_path(username, self.data_dir)
        session_file.parent.mkdir(parents=True, exist_ok=True)
        session_file.write_text("fake-session", encoding="utf-8")
        meta_path = active_session_metadata_path(self.data_dir)
        meta_path.write_text(
            json.dumps({"username": username, "session_file": session_file.name}),
            encoding="utf-8",
        )
        return session_file

    def test_no_active_session_raises_session_not_found_with_actionable_message(self) -> None:
        with self.assertRaises(SessionNotFoundError) as ctx:
            load_active_authenticated_loader(data_dir=self.data_dir)
        self.assertEqual(str(ctx.exception), NO_ACTIVE_SESSION_MESSAGE)

    def test_active_session_is_loaded_using_the_login_account_username(self) -> None:
        self._activate("instaloader.crawler")
        fake = FakeLoader(verified_username="instaloader.crawler")

        loader = load_active_authenticated_loader(
            data_dir=self.data_dir, loader_factory=lambda: fake
        )

        self.assertIs(loader, fake)
        self.assertEqual(fake.load_session_calls, [("instaloader.crawler", str(session_path("instaloader.crawler", self.data_dir)))])

    def test_login_account_different_from_any_target_source_is_used_correctly(self) -> None:
        # authenticated account = instaloader.crawler, target source = davvvat: the
        # loader must be built from the LOGIN account's session, never davvvat's.
        self._activate("instaloader.crawler")
        fake = FakeLoader(verified_username="instaloader.crawler")

        loader = load_active_authenticated_loader(
            data_dir=self.data_dir, loader_factory=lambda: fake
        )

        used_username, used_path = fake.load_session_calls[0]
        self.assertEqual(used_username, "instaloader.crawler")
        self.assertNotIn("davvvat", used_path)
        self.assertIs(loader, fake)

    def test_session_file_missing_despite_metadata_raises_session_invalid(self) -> None:
        meta_path = active_session_metadata_path(self.data_dir)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps({"username": "instaloader.crawler", "session_file": "gone.session"}),
            encoding="utf-8",
        )

        with self.assertRaises(SessionInvalidError):
            load_active_authenticated_loader(data_dir=self.data_dir)

    def test_corrupt_session_file_raises_session_invalid(self) -> None:
        self._activate("instaloader.crawler")
        fake = FakeLoader(load_error=EOFError("corrupt pickle"))

        with self.assertRaises(SessionInvalidError):
            load_active_authenticated_loader(data_dir=self.data_dir, loader_factory=lambda: fake)

    def test_expired_session_fails_verification_and_raises_session_invalid(self) -> None:
        self._activate("instaloader.crawler")
        fake = FakeLoader(verified_username=None)

        with self.assertRaises(SessionInvalidError):
            load_active_authenticated_loader(data_dir=self.data_dir, loader_factory=lambda: fake)

    def test_session_belonging_to_another_account_raises_session_invalid(self) -> None:
        self._activate("instaloader.crawler")
        fake = FakeLoader(verified_username="someone_else")

        with self.assertRaises(SessionInvalidError):
            load_active_authenticated_loader(data_dir=self.data_dir, loader_factory=lambda: fake)

    def test_test_login_error_raises_session_invalid(self) -> None:
        self._activate("instaloader.crawler")
        fake = FakeLoader(test_login_error=ConnectionError("network down"))

        with self.assertRaises(SessionInvalidError):
            load_active_authenticated_loader(data_dir=self.data_dir, loader_factory=lambda: fake)


if __name__ == "__main__":
    unittest.main()
