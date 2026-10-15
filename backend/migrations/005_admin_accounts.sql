-- Applied automatically at startup (app/schema.py creates both tables and switches row level
-- security on). Kept here for databases that are managed by hand. Every statement can be run again
-- safely. Nothing here removes or rewrites what is stored; the one UPDATE only marks the existing
-- super admins in a column this file adds.

-- The people who may log in to the console. Separate from user_management, where person_type
-- 'admin' means a staff member whose attendance is taken. The email is stored in small letters;
-- password_hash is an Argon2id hash, never a password. Times are UTC.
CREATE TABLE IF NOT EXISTS admin_accounts (
    id SERIAL PRIMARY KEY,
    email VARCHAR(120) NOT NULL,
    full_name VARCHAR(160) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(30) NOT NULL DEFAULT 'admin',
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMP,
    last_login_at TIMESTAMP,
    created_by INTEGER REFERENCES admin_accounts (id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    temporary_password_expires_at TIMESTAMP,
    has_been_super_admin BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT ck_admin_accounts_role CHECK (role IN ('super_admin', 'admin')),
    CONSTRAINT ck_admin_accounts_status CHECK (status IN ('active', 'disabled')),
    CONSTRAINT ck_admin_accounts_email_lower CHECK (email = lower(email))
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_admin_accounts_email ON admin_accounts (email);
-- For a table made by an earlier version of this file. Each adds a column and changes no existing value.
-- When a temporary password (one a super admin was shown) stops working.
ALTER TABLE admin_accounts ADD COLUMN IF NOT EXISTS temporary_password_expires_at TIMESTAMP;
-- True once an account has been a super admin, and never false again: the portal never resets the
-- password of such an account, also after it is made an admin (scripts/create_super_admin.py --force does).
ALTER TABLE admin_accounts ADD COLUMN IF NOT EXISTS has_been_super_admin BOOLEAN NOT NULL DEFAULT FALSE;
UPDATE admin_accounts SET has_been_super_admin = TRUE WHERE role = 'super_admin' AND NOT has_been_super_admin;

-- One row for each device an account is logged in on. token_hash is the SHA-256 of the refresh
-- token; the token itself is only ever in the browser's cookie. Setting revoked_at ends the login.
CREATE TABLE IF NOT EXISTS admin_sessions (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES admin_accounts (id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    revoked_at TIMESTAMP,
    last_used_at TIMESTAMP,
    ip VARCHAR(64),
    user_agent VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_admin_sessions_account_id ON admin_sessions (account_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_admin_sessions_token_hash ON admin_sessions (token_hash);

-- Row level security with no policy: nothing reaches these tables through Supabase's REST API with
-- the anon or authenticated key. The backend connects as the tables' owner and is not affected.
ALTER TABLE admin_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_sessions ENABLE ROW LEVEL SECURITY;
