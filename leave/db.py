"""DynamoDB connection handle and employee lookup."""

import os

import boto3

EMPLOYEES_TABLE = os.environ.get("EMPLOYEES_TABLE", "leave_employees")
REQUESTS_TABLE = os.environ.get("REQUESTS_TABLE", "leave_requests")
BY_EMPLOYEE_INDEX = "by_employee"


class Db:
    """Handle holding the DynamoDB Table resources and the GSI name, threaded
    everywhere the old SQL connection went. Doubles as a no-op context manager
    so `with db.connect() as db:` reads the same as before. Holidays live as a
    reserved item in the employees table (see leave/holidays.py), so there is no
    separate holidays handle."""

    def __init__(self, employees, requests, by_employee_index=BY_EMPLOYEE_INDEX):
        self.employees = employees
        self.requests = requests
        self.by_employee_index = by_employee_index

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def connect():
    """A handle exposing the `employees`/`requests` Table resources and the
    `by_employee` GSI name. Credentials come from the standard boto3 chain."""
    dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION"))
    return Db(
        dynamodb.Table(EMPLOYEES_TABLE),
        dynamodb.Table(REQUESTS_TABLE),
    )


def get_employee(db, slack_user_id):
    """Return the employee item (dict) or None if not registered."""
    return db.employees.get_item(Key={"slack_user_id": slack_user_id}).get("Item")


def list_reports(db, manager_id):
    """Employees whose manager is `manager_id` — the block-and-tell delete guard.
    Scans the employees table; the reserved policy/board items have no manager_id
    so they never match."""
    reports, scan_kwargs = [], {}
    while True:
        resp = db.employees.scan(**scan_kwargs)
        reports += [i for i in resp["Items"] if i.get("manager_id") == manager_id]
        if "LastEvaluatedKey" not in resp:
            return reports
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def list_employees(db):
    """All registered employees (real rows only); the reserved policy/board items
    have no real_name, so they're excluded. Scans the employees table."""
    people, scan_kwargs = [], {}
    while True:
        resp = db.employees.scan(**scan_kwargs)
        people += [i for i in resp["Items"] if i.get("real_name")]
        if "LastEvaluatedKey" not in resp:
            return people
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def employee_with_name(db, real_name, exclude_id=None):
    """The employee whose `real_name` matches (case-insensitive, trimmed), excluding
    `exclude_id` — used to keep names unique so manager approval tickets are
    unambiguous. Returns the conflicting item or None. Scans the employees table;
    reserved items (no real_name) never match a real name."""
    target = (real_name or "").strip().casefold()
    scan_kwargs = {}
    while True:
        resp = db.employees.scan(**scan_kwargs)
        for item in resp["Items"]:
            if item["slack_user_id"] == exclude_id:
                continue
            if (item.get("real_name") or "").strip().casefold() == target:
                return item
        if "LastEvaluatedKey" not in resp:
            return None
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
