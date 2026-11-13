"""Personal Desktop OAuth using a loopback callback and the Sheets scope only."""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from functools import partial
from pathlib import Path

from .client import GoogleSheetsClient, SheetsError
from .state import atomic_json

SCOPES = ('https://www.googleapis.com/auth/spreadsheets',)


@contextmanager
def _quiet_credentials():
    # OAuth libraries can log callback URLs, authorization codes and token
    # responses even at INFO/DEBUG. Do not let application logging expose them.
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


def token_path(data_dir: str | Path = 'data') -> Path:
    return Path(data_dir) / 'auth' / 'google' / 'token.json'


def authenticate(credentials_path: str | Path, *, data_dir: str | Path = 'data') -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    try:
        path = Path(credentials_path)
        payload = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(payload, dict) or not isinstance(payload.get('installed'), dict):
            raise ValueError
        with _quiet_credentials():
            flow = InstalledAppFlow.from_client_config(payload, scopes=list(SCOPES))
            flow.oauth2session.request = partial(flow.oauth2session.request, timeout=30)
            credentials = flow.run_local_server(host='localhost', port=0, timeout_seconds=180,
                authorization_prompt_message='Complete Google authorization in your browser.',
                success_message='GatherRadar authorization complete. You may close this window.',
                access_type='offline', prompt='consent')
        if not credentials.refresh_token or not credentials.has_scopes(SCOPES):
            raise ValueError
        atomic_json(token_path(data_dir), json.loads(credentials.to_json()))
    except Exception:
        raise SheetsError('Google Desktop authorization failed or timed out. Check the local credential file and test-user setup; no credential values were logged.') from None


def build_client(*, data_dir: str | Path = 'data') -> GoogleSheetsClient:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from google_auth_httplib2 import AuthorizedHttp
    import httplib2

    path = token_path(data_dir)
    if not path.exists():
        raise SheetsError('Google is not authenticated. Run auth google --credentials <local-path>.')
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        # Do not silently accept a broader token from an unrelated application.
        if set(payload.get('scopes', ())) != set(SCOPES):
            raise ValueError
        credentials = Credentials.from_authorized_user_info(payload, scopes=list(SCOPES))
        if not credentials.valid:
            if not credentials.refresh_token:
                raise ValueError
            # google-auth's requests transport receives an explicit timeout.
            request = Request()
            with _quiet_credentials():
                credentials.refresh(partial(request, timeout=30))
            atomic_json(path, json.loads(credentials.to_json()))
        service = build('sheets', 'v4', http=AuthorizedHttp(credentials, http=httplib2.Http(timeout=30)),
                        cache_discovery=False, static_discovery=True)
        return GoogleSheetsClient(service)
    except Exception:
        raise SheetsError('Google token is invalid, expired or revoked, or refresh failed. Run auth google again if needed.') from None
