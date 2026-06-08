CREATE TABLE IF NOT EXISTS employees (
    slack_user_id TEXT PRIMARY KEY,
    real_name     TEXT NOT NULL,
    manager_id    TEXT REFERENCES employees(slack_user_id),
    allowances    JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS requests (
    id                BIGSERIAL PRIMARY KEY,
    employee_id       TEXT NOT NULL REFERENCES employees(slack_user_id),
    leave_type        TEXT NOT NULL,
    start_date        DATE NOT NULL,
    end_date          DATE NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',
    reason            TEXT,
    decline_reason    TEXT,
    calendar_event_id TEXT,
    ticket_channel    TEXT,
    ticket_ts         TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Migrate already-existing tables to add the ticket-message columns.
ALTER TABLE requests ADD COLUMN IF NOT EXISTS ticket_channel TEXT;
ALTER TABLE requests ADD COLUMN IF NOT EXISTS ticket_ts TEXT
