"""DynamoDB connection handle and employee lookup."""

import os

import boto3

EMPLOYEES_TABLE = os.environ.get("EMPLOYEES_TABLE", "leave_employees")
REQUESTS_TABLE = os.environ.get("REQUESTS_TABLE", "leave_requests")
BY_EMPLOYEE_INDEX = "by_employee"


class Db:
    """Handle holding the two DynamoDB Table resources and the GSI name,
    threaded everywhere the old SQL connection went. Doubles as a no-op
    context manager so `with db.connect() as db:` reads the same as before."""

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
    return Db(dynamodb.Table(EMPLOYEES_TABLE), dynamodb.Table(REQUESTS_TABLE))


def get_employee(db, slack_user_id):
    """Return the employee item (dict) or None if not registered."""
    return db.employees.get_item(Key={"slack_user_id": slack_user_id}).get("Item")
