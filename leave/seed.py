"""Table provisioning and proxy-data seeding.

Run `python -m leave.seed` to provision the DynamoDB tables (on-demand) and load
proxy employees. Replace the proxy Slack IDs with real ones (Slack profile ->
Copy member ID) to exercise the bot live.
"""

import os

import boto3

from leave import db
from leave.policy import set_policy


def create_tables():
    """Provision both tables in on-demand (PAY_PER_REQUEST) mode: `employees`
    (PK slack_user_id) and `requests` (PK request_id) with the `by_employee`
    GSI (partition employee_id, sort start_date, projection ALL). Idempotent."""
    dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION"))
    existing = dynamodb.meta.client.list_tables()["TableNames"]

    if db.EMPLOYEES_TABLE not in existing:
        dynamodb.create_table(
            TableName=db.EMPLOYEES_TABLE,
            KeySchema=[{"AttributeName": "slack_user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "slack_user_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
    if db.REQUESTS_TABLE not in existing:
        dynamodb.create_table(
            TableName=db.REQUESTS_TABLE,
            KeySchema=[{"AttributeName": "request_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "request_id", "AttributeType": "S"},
                {"AttributeName": "employee_id", "AttributeType": "S"},
                {"AttributeName": "start_date", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            GlobalSecondaryIndexes=[
                {
                    "IndexName": db.BY_EMPLOYEE_INDEX,
                    "KeySchema": [
                        {"AttributeName": "employee_id", "KeyType": "HASH"},
                        {"AttributeName": "start_date", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )

    waiter = dynamodb.meta.client.get_waiter("table_exists")
    waiter.wait(TableName=db.EMPLOYEES_TABLE)
    waiter.wait(TableName=db.REQUESTS_TABLE)


def upsert_employee(db, slack_user_id, real_name, manager_id=None, allowances=None):
    item = {
        "slack_user_id": slack_user_id,
        "real_name": real_name,
        "manager_id": manager_id,
    }
    # Allowances are a per-person override only; absent, balances read the central
    # policy (see leave/policy.py). Don't write a default onto every employee.
    if allowances is not None:
        item["allowances"] = allowances
    db.employees.put_item(Item=item)


# Proxy employees for local testing. U_BOSS has no manager (top of chain).
PROXY_EMPLOYEES = [
    ("U_EXAMPLE_OWNER", "Owner", None),
    ("U_EXAMPLE_MEMBER", "Member", "U_EXAMPLE_OWNER"),
]


def main():
    from dotenv import load_dotenv

    load_dotenv()
    create_tables()
    handle = db.connect()
    set_policy(handle)  # establish the central leave policy (defaults; editable later)
    for slack_user_id, real_name, manager_id in PROXY_EMPLOYEES:
        upsert_employee(handle, slack_user_id, real_name, manager_id)
    print(f"Seeded {len(PROXY_EMPLOYEES)} employees + central policy.")


if __name__ == "__main__":
    main()
