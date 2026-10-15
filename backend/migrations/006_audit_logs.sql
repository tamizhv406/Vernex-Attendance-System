-- Applied automatically at startup (app/schema.py creates the table and switches row level security
-- on). Kept here for databases that are managed by hand. Every statement can be run again safely,
-- and nothing here touches an existing table or row. Needs 005 (admin_accounts) first.

-- Who did what, and when: logins, account changes, deletions, manual attendance, face enrollment,
-- bulk uploads. Rows are only ever added; the backend has no route that changes or removes one.
-- actor_id is empty for a failed login and for the command-line tool. details is JSON without
-- passwords, tokens, hashes or face data. created_at is UTC, like every time the backend writes.
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    actor_id INTEGER REFERENCES admin_accounts (id) ON DELETE SET NULL,
    action VARCHAR(60) NOT NULL,
    target_type VARCHAR(40),
    target_id INTEGER,
    details JSON,
    ip VARCHAR(64),
    user_agent VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS ix_audit_logs_actor_id ON audit_logs (actor_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_action ON audit_logs (action);
CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs (created_at);
CREATE INDEX IF NOT EXISTS ix_audit_logs_target ON audit_logs (target_type, target_id);

-- Row level security with no policy: nothing reaches the log through Supabase's REST API with the
-- anon or authenticated key. The backend connects as the table's owner and is not affected.
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
