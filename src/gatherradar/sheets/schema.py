"""Google Sheets request formatting over the shared review schema."""
from urllib.parse import urlsplit
from ..review.schema import *  # Compatibility for existing adapter consumers.

def cells(values: list | tuple) -> dict:
    # Explicit stringValue has RAW semantics even for =, +, -, @ prefixes.
    # No caller-supplied formulaValue is ever accepted at this boundary.
    result = []
    for value in values:
        text = str(value) if value is not None else ''
        cell = {'userEnteredValue': {'stringValue': text}}
        lines = text.splitlines()
        runs, offset = [], 0
        for line in lines:
            try:
                parsed = urlsplit(line)
                if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
                        or parsed.password or any(c.isspace() or ord(c) < 32 for c in line)):
                    break
                parsed.port
            except ValueError:
                break
            runs.append({'startIndex': offset, 'format': {'link': {'uri': line}}})
            offset += len(line.encode('utf-16-le')) // 2 + 1
        else:
            if runs:
                cell['textFormatRuns'] = runs
        result.append(cell)
    return {'values': result}


def write_rows(sheet_id: int, rows: list, *, row: int = 0, column: int = 0) -> dict:
    return {'updateCells': {'start': {'sheetId': sheet_id, 'rowIndex': row, 'columnIndex': column},
                           'rows': [cells(values) for values in rows], 'fields': 'userEnteredValue,textFormatRuns'}}


def append_rows(sheet_id: int, rows: list) -> dict:
    return {'appendCells': {'sheetId': sheet_id, 'rows': [cells(values) for values in rows],
                            'fields': 'userEnteredValue,textFormatRuns'}}


def properties(sheet_id: int, title: str, columns: int, rows: int = 1000, *, hidden: bool = False) -> dict:
    return {'sheetId': sheet_id, 'title': title, 'hidden': hidden, 'rightToLeft': not hidden,
            'gridProperties': {'rowCount': max(rows, 2), 'columnCount': max(columns, 2),
                               'frozenRowCount': 1, 'frozenColumnCount': min(2, max(columns - 1, 0))}}


def formatting(sheet_id: int, columns: int, visible: int, row_count: int,
               *, decisions: tuple[str, ...] = (), table: bool = True) -> list[dict]:
    end = max(row_count, 2)
    grid = {'sheetId': sheet_id, 'startRowIndex': 0, 'endRowIndex': end,
            'startColumnIndex': 0, 'endColumnIndex': columns}
    header = dict(grid, endRowIndex=1)
    requests = [
        {'repeatCell': {'range': grid, 'cell': {'userEnteredFormat': {
            'wrapStrategy': 'WRAP', 'verticalAlignment': 'TOP',
            'textFormat': {'fontFamily': 'Arial', 'fontSize': 10}}}, 'fields': 'userEnteredFormat'}},
        {'repeatCell': {'range': header, 'cell': {'userEnteredFormat': {
            'backgroundColor': {'red': .88, 'green': .93, 'blue': .94},
            'textFormat': {'bold': True}}},
            'fields': 'userEnteredFormat.backgroundColor,userEnteredFormat.textFormat.bold'}},
        {'updateDimensionProperties': {'range': {'sheetId': sheet_id, 'dimension': 'COLUMNS',
            'startIndex': 0, 'endIndex': columns}, 'properties': {'pixelSize': 145}, 'fields': 'pixelSize'}},
    ]
    if visible:
        requests.append({'updateDimensionProperties': {'range': {'sheetId': sheet_id,
            'dimension': 'COLUMNS', 'startIndex': 1, 'endIndex': min(2, visible)},
            'properties': {'pixelSize': 260}, 'fields': 'pixelSize'}})
    if visible < columns:
        technical = {'sheetId': sheet_id, 'startColumnIndex': visible, 'endColumnIndex': columns}
        if visible:
            requests.append({'updateDimensionProperties': {'range': {
                'sheetId': sheet_id, 'dimension': 'COLUMNS', 'startIndex': visible, 'endIndex': columns},
                'properties': {'hiddenByUser': True}, 'fields': 'hiddenByUser'}})
        requests.append({'addProtectedRange': {'protectedRange': {'range': technical,
            'description': 'GatherRadar machine-owned identifiers', 'warningOnly': True}}})
    if table:
        requests.append({'setBasicFilter': {'filter': {'range': grid}}})
    if decisions:
        decision_range = {'sheetId': sheet_id, 'startRowIndex': 1, 'startColumnIndex': 0, 'endColumnIndex': 1}
        requests.append({'setDataValidation': {'range': decision_range, 'rule': {
            'condition': {'type': 'ONE_OF_LIST', 'values': [{'userEnteredValue': v} for v in decisions]},
            'strict': True, 'showCustomUi': True}}})
        for index, value in enumerate(decisions[1:]):
            requests.append({'addConditionalFormatRule': {'index': index, 'rule': {
                'ranges': [decision_range], 'booleanRule': {'condition': {
                    'type': 'TEXT_EQ', 'values': [{'userEnteredValue': value}]},
                    'format': {'backgroundColor': {'red': .91, 'green': .96, 'blue': .91}}}}}})
    return requests
