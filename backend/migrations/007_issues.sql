-- Applied automatically at startup (app/schema.py creates both tables and switches row level security
-- on). Kept here for databases that are managed by hand. Every statement can be run again safely, and
-- nothing here touches an existing table or row. Needs 005 (admin_accounts) first.

-- Problems reported from the console by admins and super admins. reported_by is the account that was
-- logged in, never a value sent by the browser. Accounts are disabled, never deleted, so an account
-- cannot be removed while it has reported an issue (RESTRICT). page_url is a path inside the console;
-- device_info is JSON with the browser, the OS and the screen. A resolved issue always has a
-- resolution note. Times are UTC.
CREATE TABLE IF NOT EXISTS issues (
    id SERIAL PRIMARY KEY,
    title VARCHAR(120) NOT NULL,
    description TEXT NOT NULL,
    category VARCHAR(30) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    page_url VARCHAR(255),
    device_info JSON,
    reported_by INTEGER NOT NULL REFERENCES admin_accounts (id) ON DELETE RESTRICT,
    assigned_to INTEGER REFERENCES admin_accounts (id) ON DELETE SET NULL,
    resolution_note TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    updated_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    resolved_at TIMESTAMP,
    CONSTRAINT ck_issues_category CHECK (category IN ('bug', 'face_recognition', 'attendance_data', 'camera_device', 'login_access', 'other')),
    CONSTRAINT ck_issues_severity CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT ck_issues_status CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    CONSTRAINT ck_issues_resolution_note CHECK (status <> 'resolved' OR (resolution_note IS NOT NULL AND length(trim(resolution_note)) > 0))
);
CREATE INDEX IF NOT EXISTS ix_issues_status ON issues (status);
CREATE INDEX IF NOT EXISTS ix_issues_reported_by ON issues (reported_by);
CREATE INDEX IF NOT EXISTS ix_issues_assigned_to ON issues (assigned_to);
CREATE INDEX IF NOT EXISTS ix_issues_created_at ON issues (created_at);

-- The thread under an issue, by its reporter and by super admins. Comments are never changed or
-- removed by the app; they go with their issue if an issue is ever deleted by hand.
CREATE TABLE IF NOT EXISTS issue_comments (
    id SERIAL PRIMARY KEY,
    issue_id INTEGER NOT NULL REFERENCES issues (id) ON DELETE CASCADE,
    author_id INTEGER NOT NULL REFERENCES admin_accounts (id) ON DELETE RESTRICT,
    body TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS ix_issue_comments_issue_id ON issue_comments (issue_id);

-- Row level security switched on, with no policy. It is meant to keep Supabase's REST API (the anon and
-- authenticated roles) away from these tables; switching it on does not show by itself that they are
-- kept out. Roles that bypass it are not affected: the tables' owner (the backend connects as that),
-- a superuser, and Supabase's service_role. What each role is granted on these tables, and any REVOKE,
-- is checked on the real database in Phase 4 (S-02). Nothing here grants or revokes anything.
ALTER TABLE issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE issue_comments ENABLE ROW LEVEL SECURITY;
