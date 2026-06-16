"""Thin wrapper over the Google Sheets API for the shared leave board.

Renders a people x days grid onto the first tab of LEAVE_SHEET_ID, colouring each
leave cell by leave type. Injected into the board so tests can substitute a fake.
"""

import os

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Cell background per leave type (Sheets API wants 0..1 RGB floats).
_WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
TYPE_COLOR = {
    "vacation": {"red": 0.71, "green": 0.88, "blue": 0.80},  # green
    "sick": {"red": 0.96, "green": 0.78, "blue": 0.77},      # red
    "personal": {"red": 0.79, "green": 0.85, "blue": 0.97},  # blue
}
_HALF_LABEL = {"morning": "AM", "afternoon": "PM"}


def _str_cell(text, color=_WHITE):
    return {
        "userEnteredValue": {"stringValue": text},
        "userEnteredFormat": {"backgroundColor": color},
    }


def _num_cell(n):
    return {"userEnteredValue": {"numberValue": n}}


class SheetsClient:
    def __init__(self, service, spreadsheet_id):
        self.service = service
        self.spreadsheet_id = spreadsheet_id

    @classmethod
    def from_env(cls):
        # Imported lazily (like CalendarClient) so cold-start paths that never render
        # the board don't pay for the heavy google-api-python-client import.
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"], scopes=SCOPES
        )
        service = build("sheets", "v4", credentials=creds)
        return cls(service, os.environ["LEAVE_SHEET_ID"])

    def _first_sheet_id(self):
        meta = (
            self.service.spreadsheets()
            .get(spreadsheetId=self.spreadsheet_id, fields="sheets.properties.sheetId")
            .execute()
        )
        return meta["sheets"][0]["properties"]["sheetId"]

    def render_grid(self, title, num_days, rows):
        """Overwrite the first tab with the month grid. `rows` is
        [{name, cells: {day -> {type, half}}}]."""
        days = range(1, num_days + 1)
        header = {"values": [_str_cell(title)] + [_num_cell(d) for d in days]}
        grid = [header]
        for r in rows:
            values = [_str_cell(r["name"])]
            for d in days:
                cell = r["cells"].get(d)
                if cell is None:
                    values.append(_str_cell(""))
                else:
                    color = TYPE_COLOR.get(cell["type"], _WHITE)
                    values.append(_str_cell(_HALF_LABEL.get(cell.get("half"), ""), color))
            grid.append({"values": values})

        # A fresh sheet is only 26 columns / 1000 rows; resize it to fit the grid first
        # (writing past the grid bounds otherwise fails with "exceeds grid limits"). The
        # full grid is rewritten each time, so this also clears removed people/old months.
        cols = num_days + 1  # name column + one per day
        sheet_id = self._first_sheet_id()
        requests = [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {"rowCount": max(len(grid), 2), "columnCount": cols},
                    },
                    "fields": "gridProperties.rowCount,gridProperties.columnCount",
                }
            },
            {
                "updateCells": {
                    "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
                    "rows": grid,
                    "fields": "userEnteredValue,userEnteredFormat.backgroundColor",
                }
            },
        ]
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id, body={"requests": requests}
        ).execute()
