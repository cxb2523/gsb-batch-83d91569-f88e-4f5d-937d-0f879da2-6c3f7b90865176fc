import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from gatherradar.cli import build_parser, main
from gatherradar.collectors.base import CollectorError
from gatherradar.collectors.instagram import InstagramCollector
from gatherradar.collectors.instagram_auth import InstagramAuthError
from gatherradar.collectors.instagram_browser import (
    NOT_AUTHENTICATED_MESSAGE,
    BrowserSessionNotAuthenticatedError,
)
from gatherradar.collectors.instagram_instaloader import InstaloaderPostFetcher

FAKE_COOKIE = "sessionid=super-secret-value; csrftoken=xyz789"
PROFILE_PATH = Path("data") / "browser" / "instagram-profile"


def run_main(argv, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        exit_code = main(argv, **kwargs)
    return exit_code, out.getvalue(), err.getvalue()


def parse_quietly(argv):
    with redirect_stderr(io.StringIO()):
        return build_parser().parse_args(argv)


class AuthArgumentParsingTests(unittest.TestCase):
    def test_auth_instagram_takes_no_username(self) -> None:
        args = build_parser().parse_args(["auth", "instagram"])

        self.assertEqual(args.command, "auth")
        self.assertEqual(args.auth_type, "instagram")
        self.assertFalse(hasattr(args, "username"))
        self.assertEqual(args.data_dir, "data")

    def test_browser_profile_login_is_the_default_auth(self) -> None:
        self.assertFalse(build_parser().parse_args(["auth", "instagram"]).legacy_cookie)

    def test_legacy_cookie_import_must_be_requested_explicitly(self) -> None:
        self.assertTrue(build_parser().parse_args(["auth", "instagram", "--legacy-cookie"]).legacy_cookie)

    def test_auth_instagram_accepts_custom_data_dir(self) -> None:
        args = build_parser().parse_args(["auth", "instagram", "--data-dir", "custom-data"])
        self.assertEqual(args.data_dir, "custom-data")

    def test_auth_requires_a_source_type(self) -> None:
        with self.assertRaises(SystemExit):
            parse_quietly(["auth"])

    def test_auth_instagram_rejects_a_positional_username(self) -> None:
        with self.assertRaises(SystemExit):
            parse_quietly(["auth", "instagram", "davvvat"])


class CollectArgumentParsingTests(unittest.TestCase):
    def test_collect_command_defaults_to_the_browser_transport(self) -> None:
        args = build_parser().parse_args(["collect", "instagram", "davvvat_instagram"])

        self.assertEqual(args.command, "collect")
        self.assertEqual(args.source_id, "davvvat_instagram")
        self.assertEqual(args.transport, "browser")

    def test_legacy_instaloader_transport_can_be_selected(self) -> None:
        args = build_parser().parse_args(
            ["collect", "instagram", "davvvat_instagram", "--transport", "instaloader"]
        )
        self.assertEqual(args.transport, "instaloader")

    def test_unknown_transport_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            parse_quietly(["collect", "instagram", "davvvat_instagram", "--transport", "proxy"])


class BrowserAuthCommandTests(unittest.TestCase):
    def test_successful_browser_auth_reports_verification(self) -> None:
        with mock.patch(
            "gatherradar.cli.authenticate_browser_profile", return_value=PROFILE_PATH
        ) as authenticate:
            exit_code, out, _ = run_main(["auth", "instagram"])

        authenticate.assert_called_once_with(data_dir="data", wait_for_user=mock.ANY)
        self.assertEqual(exit_code, 0)
        self.assertIn(str(PROFILE_PATH), out)
        self.assertIn("Instagram browser session verified.", out)
        self.assertIn("Persistent profile saved.", out)

    def test_custom_data_dir_and_confirmation_are_passed_through(self) -> None:
        def confirm() -> None:
            return None

        with mock.patch("gatherradar.cli.authenticate_browser_profile") as authenticate:
            run_main(["auth", "instagram", "--data-dir", "custom-data"], _wait_for_user=confirm)

        authenticate.assert_called_once_with(data_dir="custom-data", wait_for_user=confirm)

    def test_default_confirmation_explains_manual_login_and_waits_for_enter(self) -> None:
        def authenticate(*, data_dir, wait_for_user):
            wait_for_user()
            return PROFILE_PATH

        with (
            mock.patch("gatherradar.cli.authenticate_browser_profile", side_effect=authenticate),
            mock.patch("builtins.input", return_value="") as enter,
        ):
            exit_code, out, _ = run_main(["auth", "instagram"])

        enter.assert_called_once_with()
        self.assertEqual(exit_code, 0)
        self.assertIn("Log in to Instagram in the opened Chrome window.", out)
        self.assertIn("When the Instagram home page is visible, return here and press Enter.", out)
        self.assertIn("Verifying session...", out)

    def test_browser_auth_never_prompts_for_a_password_or_cookie(self) -> None:
        def authenticate(*, data_dir, wait_for_user):
            wait_for_user()
            return PROFILE_PATH

        with (
            mock.patch("gatherradar.cli.getpass.getpass", side_effect=AssertionError("secret prompt")),
            mock.patch("gatherradar.cli.create_session_from_cookie", side_effect=AssertionError("cookie")),
            mock.patch("gatherradar.cli.authenticate_browser_profile", side_effect=authenticate),
            mock.patch("builtins.input", return_value=""),
        ):
            exit_code, _, _ = run_main(["auth", "instagram"])

        self.assertEqual(exit_code, 0)

    def test_failed_browser_auth_reports_the_error_without_a_traceback(self) -> None:
        with mock.patch(
            "gatherradar.cli.authenticate_browser_profile",
            side_effect=BrowserSessionNotAuthenticatedError(NOT_AUTHENTICATED_MESSAGE),
        ):
            exit_code, _, err = run_main(["auth", "instagram"])

        self.assertEqual(exit_code, 1)
        self.assertIn("python -m gatherradar auth instagram", err)
        self.assertNotIn("Traceback", err)

    def test_cancelled_browser_auth_is_reported(self) -> None:
        with mock.patch("gatherradar.cli.authenticate_browser_profile", side_effect=KeyboardInterrupt):
            exit_code, _, err = run_main(["auth", "instagram"])

        self.assertEqual(exit_code, 1)
        self.assertIn("cancelled", err)


class LegacyCookieAuthCommandTests(unittest.TestCase):
    """The previous cookie-import tests, now reached through --legacy-cookie because the
    browser profile became the default authentication."""

    def test_successful_auth_reports_the_authenticated_username(self) -> None:
        saved_path = Path("data") / "sessions" / "instagram-instaloader.crawler.session"

        with mock.patch(
            "gatherradar.cli.create_session_from_cookie",
            return_value=("instaloader.crawler", saved_path),
        ) as create:
            exit_code, out, _ = run_main(
                ["auth", "instagram", "--legacy-cookie"], _cookie_prompt=lambda: FAKE_COOKIE
            )

        create.assert_called_once_with(FAKE_COOKIE, data_dir="data")
        self.assertEqual(exit_code, 0)
        self.assertIn("Authenticated as @instaloader.crawler", out)
        self.assertIn("Session saved successfully.", out)

    def test_failed_auth_reports_the_error_and_does_not_raise(self) -> None:
        with mock.patch(
            "gatherradar.cli.create_session_from_cookie",
            side_effect=InstagramAuthError("Instagram did not accept the pasted cookie"),
        ):
            exit_code, _, err = run_main(
                ["auth", "instagram", "--legacy-cookie"], _cookie_prompt=lambda: FAKE_COOKIE
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("Instagram did not accept the pasted cookie", err)

    def test_legacy_cookie_import_does_not_open_the_browser(self) -> None:
        with (
            mock.patch("gatherradar.cli.authenticate_browser_profile", side_effect=AssertionError("browser")),
            mock.patch("gatherradar.cli.create_session_from_cookie") as create,
        ):
            create.return_value = ("instaloader.crawler", Path("data/sessions/x.session"))
            run_main(
                ["auth", "instagram", "--legacy-cookie", "--data-dir", "custom-data"],
                _cookie_prompt=lambda: FAKE_COOKIE,
            )

        create.assert_called_once_with(FAKE_COOKIE, data_dir="custom-data")

    def test_no_secret_value_appears_in_cli_output(self) -> None:
        with mock.patch(
            "gatherradar.cli.create_session_from_cookie",
            return_value=("instaloader.crawler", Path("data/sessions/x.session")),
        ):
            _, out, err = run_main(
                ["auth", "instagram", "--legacy-cookie"], _cookie_prompt=lambda: FAKE_COOKIE
            )

        self.assertNotIn("super-secret-value", out)
        self.assertNotIn("super-secret-value", err)

    def test_default_prompt_uses_getpass_so_the_cookie_is_never_echoed(self) -> None:
        with (
            mock.patch("gatherradar.cli.getpass.getpass", return_value=FAKE_COOKIE) as getpass_call,
            mock.patch(
                "gatherradar.cli.create_session_from_cookie",
                return_value=("instaloader.crawler", Path("data/sessions/x.session")),
            ) as create,
        ):
            run_main(["auth", "instagram", "--legacy-cookie"])

        getpass_call.assert_called_once()
        create.assert_called_once_with(FAKE_COOKIE, data_dir="data")


class CollectTransportDispatchTests(unittest.TestCase):
    def test_default_collection_leaves_the_browser_collector_to_orchestration(self) -> None:
        with mock.patch(
            "gatherradar.cli.run_instagram_collection", side_effect=CollectorError("stop")
        ) as run:
            run_main(["collect", "instagram", "davvvat_instagram"])

        self.assertIsNone(run.call_args.kwargs["collector"])

    def test_instaloader_transport_builds_the_legacy_fetcher(self) -> None:
        with mock.patch(
            "gatherradar.cli.run_instagram_collection", side_effect=CollectorError("stop")
        ) as run:
            run_main(["collect", "instagram", "davvvat_instagram", "--transport", "instaloader"])

        collector = run.call_args.kwargs["collector"]
        self.assertIsInstance(collector, InstagramCollector)
        self.assertIsInstance(collector._fetch_posts, InstaloaderPostFetcher)

    def test_browser_session_error_is_printed_without_a_traceback(self) -> None:
        with mock.patch(
            "gatherradar.cli.run_instagram_collection",
            side_effect=BrowserSessionNotAuthenticatedError(NOT_AUTHENTICATED_MESSAGE),
        ):
            exit_code, _, err = run_main(["collect", "instagram", "davvvat_instagram"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Instagram browser session is not authenticated.", err)
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
