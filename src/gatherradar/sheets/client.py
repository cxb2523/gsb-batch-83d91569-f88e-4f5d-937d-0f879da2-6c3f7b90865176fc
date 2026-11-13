"""Small official Sheets API boundary. Mutations are never blindly retried."""
from __future__ import annotations

import re
from typing import Protocol


class SheetsError(Exception):
    """Safe public error; never contains a Google response or credential payload."""


class SheetsClient(Protocol):
    def create(self, body: dict) -> dict: ...
    def metadata(self, spreadsheet_id: str) -> dict: ...
    def read(self, spreadsheet_id: str, title: str, start: int, end: int, columns: int) -> list[list]: ...
    def batch(self, spreadsheet_id: str, requests: list[dict]) -> dict: ...


def validate_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,200}', value):
        raise SheetsError('Invalid spreadsheet ID.')
    return value


def column_name(number: int) -> str:
    result = ''
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


class GoogleSheetsClient:
    def __init__(self, service: object) -> None:
        self.api = service.spreadsheets()

    @staticmethod
    def _execute(request: object, *, read: bool = False) -> dict:
        try:
            return request.execute(num_retries=2 if read else 0)
        except Exception as exc:
            status = getattr(getattr(exc, 'resp', None), 'status', None)
            message = {
                400: 'Google rejected the Sheets request; check schema and spreadsheet ID.',
                401: 'Google authorization expired or was revoked; run auth google again.',
                403: 'Google denied access; check Sheets API, account permissions and quota.',
                404: 'Spreadsheet unavailable or deleted; check the configured workbook.',
                429: 'Google quota exceeded; retry this same run later.',
            }.get(status, 'Google request failed or timed out; retry the same run ID to reconcile its outcome.')
            raise SheetsError(message) from None

    def create(self, body: dict) -> dict:
        return self._execute(self.api.create(body=body, fields='spreadsheetId,spreadsheetUrl'))

    def metadata(self, spreadsheet_id: str) -> dict:
        return self._execute(self.api.get(spreadsheetId=validate_id(spreadsheet_id),
            fields='spreadsheetId,spreadsheetUrl,sheets(properties,developerMetadata)'), read=True)

    def read(self, spreadsheet_id: str, title: str, start: int, end: int, columns: int) -> list[list]:
        if not 1 <= start <= end or end - start >= 500 or not 1 <= columns <= 100:
            raise SheetsError('Invalid bounded Sheets read.')
        quoted = "'" + title.replace("'", "''") + "'"
        result = self._execute(self.api.values().get(spreadsheetId=validate_id(spreadsheet_id),
            range=f'{quoted}!A{start}:{column_name(columns)}{end}',
            valueRenderOption='UNFORMATTED_VALUE'), read=True)
        values = result.get('values', [])
        if not isinstance(values, list) or any(not isinstance(row, list) for row in values):
            raise SheetsError('Invalid spreadsheet values response.')
        return values

    def batch(self, spreadsheet_id: str, requests: list[dict]) -> dict:
        if not requests:
            return {}
        return self._execute(self.api.batchUpdate(spreadsheetId=validate_id(spreadsheet_id),
                                                  body={'requests': requests}))
