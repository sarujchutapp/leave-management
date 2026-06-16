"""Unit-test the Sheets request-building (the real API call is faked). Guards the
'resize the grid before writing' fix — a fresh sheet has only 26 columns."""

from leave.sheets_client import TYPE_COLOR, SheetsClient


class _FakeSheetsService:
    """Minimal stand-in for the googleapiclient sheets service."""

    def __init__(self):
        self.batch_body = None
        self._mode = None

    def spreadsheets(self):
        return self

    def get(self, **kwargs):
        self._mode = "get"
        return self

    def batchUpdate(self, spreadsheetId=None, body=None):
        self._mode = "batch"
        self.batch_body = body
        return self

    def execute(self):
        if self._mode == "get":
            return {"sheets": [{"properties": {"sheetId": 0}}]}
        return {}


def _requests(service):
    return {list(r)[0]: list(r.values())[0] for r in service.batch_body["requests"]}


def test_render_grid_resizes_columns_to_fit_the_month():
    service = _FakeSheetsService()
    SheetsClient(service, "SID").render_grid("June 2026", 30, [])
    resize = _requests(service)["updateSheetProperties"]
    # 30 days + 1 name column = 31; must grow past a fresh sheet's 26 columns.
    assert resize["properties"]["gridProperties"]["columnCount"] == 31


def test_render_grid_colours_cell_by_leave_type():
    service = _FakeSheetsService()
    rows = [{"name": "Alice", "cells": {10: {"type": "vacation", "half": None}}}]
    SheetsClient(service, "SID").render_grid("June 2026", 30, rows)

    grid = _requests(service)["updateCells"]["rows"]
    assert len(grid) == 2  # header + Alice
    alice_day10 = grid[1]["values"][10]  # col 0 = name, col d = day d
    assert alice_day10["userEnteredFormat"]["backgroundColor"] == TYPE_COLOR["vacation"]
