import io
import json
import logging
import importlib.util
from unittest import skipUnless

GOOGLE_AVAILABLE = all(importlib.util.find_spec(name) is not None for name in ("googleapiclient", "google_auth_oauthlib", "google_auth_httplib2"))
from contextlib import redirect_stdout, redirect_stderr
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gatherradar.cli import build_parser, main
from gatherradar.sheets.auth import SCOPES, authenticate, build_client, token_path
from gatherradar.sheets.client import GoogleSheetsClient, SheetsError, validate_id
from gatherradar.sheets.state import RuntimeState, atomic_json
from sheets_fakes import OfflineCase


class AuthClientTests(OfflineCase):
    def test_scope_and_default_token_path(self):
        self.assertEqual(SCOPES, ('https://www.googleapis.com/auth/spreadsheets',))
        self.assertEqual(token_path().as_posix(), 'data/auth/google/token.json')

    @skipUnless(GOOGLE_AVAILABLE, "Install .[google-sheets] for optional OAuth tests.")
    def test_missing_token_does_not_open_browser(self):
        with self.assertRaisesRegex(SheetsError, 'not authenticated'):
            build_client(data_dir=self.directory)

    @skipUnless(GOOGLE_AVAILABLE, "Install .[google-sheets] for optional OAuth tests.")
    def test_desktop_flow_keeps_credentials_local_and_uses_loopback(self):
        path = self.directory / 'credentials.json'
        payload = {'installed': {'client_id': 'fake', 'client_secret': 'fake'}}
        path.write_text(json.dumps(payload), encoding='utf-8')
        credentials = Mock(refresh_token='fake_refresh')
        credentials.has_scopes.return_value = True
        credentials.to_json.return_value = json.dumps({'token': 'fake_access', 'scopes': list(SCOPES)})
        flow = Mock()
        flow.run_local_server.return_value = credentials
        with patch('google_auth_oauthlib.flow.InstalledAppFlow.from_client_config', return_value=flow) as factory:
            authenticate(path, data_dir=self.directory)
        self.assertEqual(factory.call_args.kwargs['scopes'], list(SCOPES))
        self.assertEqual(flow.run_local_server.call_args.kwargs['host'], 'localhost')
        self.assertEqual(flow.run_local_server.call_args.kwargs['port'], 0)
        self.assertNotIn('client_secret', token_path(self.directory).read_text())
        self.assertEqual(json.loads(path.read_text()), payload)

    @skipUnless(GOOGLE_AVAILABLE, "Install .[google-sheets] for optional OAuth tests.")
    def test_web_or_service_account_credentials_rejected(self):
        path = self.directory / 'credentials.json'
        for payload in ({'web': {}}, {'type': 'service_account'}, []):
            path.write_text(json.dumps(payload), encoding='utf-8')
            with self.subTest(payload=payload), self.assertRaises(SheetsError):
                authenticate(path, data_dir=self.directory)

    @skipUnless(GOOGLE_AVAILABLE, "Install .[google-sheets] for optional OAuth tests.")
    def test_auth_failure_does_not_expose_secret(self):
        path = self.directory / 'credentials.json'
        path.write_text('{"installed": {}}')
        with patch('google_auth_oauthlib.flow.InstalledAppFlow.from_client_config', side_effect=ValueError('secret-value')):
            with self.assertRaises(SheetsError) as caught:
                authenticate(path, data_dir=self.directory)
        self.assertNotIn('secret-value', str(caught.exception))

    def test_oauth_library_logs_are_suppressed_and_logging_restored(self):
        from gatherradar.sheets.auth import _quiet_credentials
        original = logging.root.manager.disable
        with _quiet_credentials():
            self.assertFalse(logging.getLogger('google_auth_oauthlib.flow').isEnabledFor(logging.INFO))
            self.assertFalse(logging.getLogger('oauthlib.oauth2').isEnabledFor(logging.DEBUG))
        self.assertEqual(logging.root.manager.disable, original)

    @skipUnless(GOOGLE_AVAILABLE, "Install .[google-sheets] for optional OAuth tests.")
    def test_valid_token_builds_official_service_without_network_discovery(self):
        atomic_json(token_path(self.directory), {'scopes': list(SCOPES)})
        credentials = Mock(valid=True)
        with patch('google.oauth2.credentials.Credentials.from_authorized_user_info', return_value=credentials), \
             patch('google_auth_httplib2.AuthorizedHttp') as http, \
             patch('googleapiclient.discovery.build') as build:
            client = build_client(data_dir=self.directory)
        self.assertIsInstance(client, GoogleSheetsClient)
        self.assertTrue(build.call_args.kwargs['static_discovery'])
        self.assertFalse(build.call_args.kwargs['cache_discovery'])
        self.assertEqual(http.call_args.kwargs['http'].timeout, 30)

    @skipUnless(GOOGLE_AVAILABLE, "Install .[google-sheets] for optional OAuth tests.")
    def test_broader_scopes_are_not_silently_reused(self):
        atomic_json(token_path(self.directory), {'scopes': list(SCOPES) + ['https://www.googleapis.com/auth/drive']})
        with self.assertRaises(SheetsError):
            build_client(data_dir=self.directory)

    @skipUnless(GOOGLE_AVAILABLE, "Install .[google-sheets] for optional OAuth tests.")
    def test_revoked_token_is_secret_safe(self):
        atomic_json(token_path(self.directory), {'scopes': list(SCOPES)})
        credentials = Mock(valid=False, refresh_token='fake')
        credentials.refresh.side_effect = ValueError('secret_refresh')
        with patch('google.oauth2.credentials.Credentials.from_authorized_user_info', return_value=credentials):
            with self.assertRaises(SheetsError) as caught:
                build_client(data_dir=self.directory)
        self.assertNotIn('secret_refresh', str(caught.exception))

    def test_read_retries_but_mutation_never_blindly_retries(self):
        request = Mock()
        request.execute.return_value = {}
        GoogleSheetsClient._execute(request, read=True)
        request.execute.assert_called_once_with(num_retries=2)
        request.reset_mock()
        GoogleSheetsClient._execute(request)
        request.execute.assert_called_once_with(num_retries=0)

    def test_error_translation_strips_api_payloads(self):
        for status in (400, 401, 403, 404, 429, 503):
            error = RuntimeError('secret-token-and-response')
            error.resp = SimpleNamespace(status=status)
            request = Mock()
            request.execute.side_effect = error
            with self.subTest(status=status), self.assertRaises(SheetsError) as caught:
                GoogleSheetsClient._execute(request)
            self.assertNotIn('secret-token', str(caught.exception))

    def test_adapter_quotes_title_and_bounds_range(self):
        service = Mock()
        service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {'values': [['hello']]}
        adapter = GoogleSheetsClient(service)
        self.assertEqual(adapter.read('fake_workbook_123', "Owner's tab", 1, 10, 28), [['hello']])
        self.assertEqual(service.spreadsheets.return_value.values.return_value.get.call_args.kwargs['range'], "'Owner''s tab'!A1:AB10")
        with self.assertRaises(SheetsError):
            adapter.read('fake_workbook_123', 'tab', 1, 501, 28)

    def test_invalid_spreadsheet_id(self):
        for value in ('https://docs.google.com/spreadsheets/d/test', '../id', '', 'id with space'):
            with self.subTest(value=value), self.assertRaises(SheetsError):
                validate_id(value)

    def test_local_lock_prevents_second_writer(self):
        state = RuntimeState(self.directory)
        with state.lock():
            with self.assertRaises(SheetsError):
                with state.lock():
                    pass
        self.assertFalse(state.path.with_suffix('.lock').exists())

    def test_malformed_local_state_is_not_replaced(self):
        state = RuntimeState(self.directory)
        state.path.parent.mkdir(parents=True)
        state.path.write_text('malformed')
        with self.assertRaises(SheetsError):
            state.read()
        self.assertEqual(state.path.read_text(), 'malformed')

    def test_cli_routes_google_auth_before_legacy_instagram_options(self):
        with patch('gatherradar.sheets.cli.authenticate') as auth, redirect_stdout(io.StringIO()):
            self.assertEqual(main(['auth', 'google', '--credentials', 'fake-local-path']), 0)
        auth.assert_called_once_with('fake-local-path', data_dir='data')

    def test_cli_refresh_and_sync_defaults(self):
        for command in (['refresh'], ['sheets', 'sync']):
            args = build_parser().parse_args(command + ['--all-enabled'])
            self.assertEqual((args.days, args.limit), (14, 5))
            self.assertFalse(args.skip_instagram_evidence)

    @skipUnless(GOOGLE_AVAILABLE, "Install .[google-sheets] for optional OAuth tests.")
    def test_cli_status_missing_auth_has_safe_report(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(['sheets', 'status', '--data-dir', str(self.directory)])
        self.assertEqual(code, 1)
        self.assertIn('Google token present: False', out.getvalue())
        self.assertIn('not authenticated', err.getvalue())
