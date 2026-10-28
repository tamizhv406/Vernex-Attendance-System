-- Complete current schema in one file, for creating a NEW empty PostgreSQL/Supabase database by hand.
-- It matches the SQLAlchemy models in app/models (generated from them) plus the foreign-key rules that
-- app/schema.py enforces on PostgreSQL.
--
-- On PostgreSQL the backend does not create or change tables when it starts: it checks that this schema
-- is in place and refuses to start, naming what is missing, if it is not (DATABASE_AUTO_UPGRADE=true
-- brings back the old changes at every start). Run this file once on a new, empty database. A database
-- created by an older version is upgraded by the numbered files it does not have yet (001 -> 010);
-- don't run this file on such a database. Every statement can be run again safely.

CREATE TABLE IF NOT EXISTS courses (
    id SERIAL PRIMARY KEY,
    course_code VARCHAR(40) NOT NULL,
    course_name VARCHAR(120) NOT NULL,
    description TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_courses_course_code ON courses (course_code);
CREATE INDEX IF NOT EXISTS ix_courses_course_name ON courses (course_name);

CREATE TABLE IF NOT EXISTS timings (
    id SERIAL PRIMARY KEY,
    name VARCHAR(140) NOT NULL,
    timing_type VARCHAR(40) NOT NULL,
    category_program VARCHAR(120),
    batch_name VARCHAR(120),
    start_time TIME,
    grace_time TIME,
    end_time TIME,
    late_after_time TIME,
    auto_absent_after_time TIME,
    working_days VARCHAR(160),
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_timings_name ON timings (name);

CREATE TABLE IF NOT EXISTS batches (
    id SERIAL PRIMARY KEY,
    course_id INTEGER NOT NULL REFERENCES courses (id) ON DELETE RESTRICT,
    batch_name VARCHAR(120) NOT NULL,
    batch_level VARCHAR(120),
    timing_id INTEGER REFERENCES timings (id) ON DELETE SET NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_batches_course_name UNIQUE (course_id, batch_name)
);
CREATE INDEX IF NOT EXISTS ix_batches_course_id ON batches (course_id);
CREATE INDEX IF NOT EXISTS ix_batches_batch_name ON batches (batch_name);

CREATE TABLE IF NOT EXISTS user_management (
    id SERIAL PRIMARY KEY,
    person_code VARCHAR(80) NOT NULL,
    full_name VARCHAR(160) NOT NULL,
    phone VARCHAR(20),
    email VARCHAR(160),
    person_type VARCHAR(30) NOT NULL,
    gender VARCHAR(30),
    guardian_name VARCHAR(160),
    guardian_phone VARCHAR(20),
    course_id INTEGER REFERENCES courses (id) ON DELETE SET NULL,
    batch_id INTEGER REFERENCES batches (id) ON DELETE SET NULL,
    category_program VARCHAR(120),
    batch_name VARCHAR(120),
    level_class VARCHAR(120),
    designation VARCHAR(120),
    department VARCHAR(120),
    membership_type VARCHAR(120),
    plan_name VARCHAR(120),
    timing_id INTEGER,
    joining_date DATE,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    face_enrollment_status VARCHAR(40) NOT NULL DEFAULT 'not_started',
    notes TEXT,
    -- The random code a QR card holds (010). Never a person's ID; unique, see the index below.
    attendance_code VARCHAR(16),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_user_management_person_code ON user_management (person_code);
CREATE INDEX IF NOT EXISTS ix_user_management_full_name ON user_management (full_name);
CREATE INDEX IF NOT EXISTS ix_user_management_person_type ON user_management (person_type);
CREATE INDEX IF NOT EXISTS ix_user_management_course_id ON user_management (course_id);
CREATE INDEX IF NOT EXISTS ix_user_management_batch_id ON user_management (batch_id);
CREATE INDEX IF NOT EXISTS ix_user_management_category_program ON user_management (category_program);
CREATE INDEX IF NOT EXISTS ix_user_management_batch_name ON user_management (batch_name);
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_management_attendance_code ON user_management (attendance_code);

CREATE TABLE IF NOT EXISTS face_enrollments (
    id SERIAL PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES user_management (id) ON DELETE CASCADE,
    enrollment_status VARCHAR(50) NOT NULL DEFAULT 'not_started',
    current_step VARCHAR(40),
    total_steps INTEGER NOT NULL DEFAULT 5,
    completed_steps INTEGER NOT NULL DEFAULT 0,
    quality_score DOUBLE PRECISION,
    has_specs_reference BOOLEAN NOT NULL DEFAULT FALSE,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_face_enrollments_person_id ON face_enrollments (person_id);

-- capture_meta: JSON describing how the reference face was captured. No image is stored.
CREATE TABLE IF NOT EXISTS face_embeddings (
    id SERIAL PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES user_management (id) ON DELETE CASCADE,
    embedding_vector TEXT NOT NULL,
    pose_type VARCHAR(40) NOT NULL,
    model_name VARCHAR(80) NOT NULL DEFAULT 'DeepFace',
    quality_score DOUBLE PRECISION,
    brightness_score DOUBLE PRECISION,
    blur_score DOUBLE PRECISION,
    face_angle DOUBLE PRECISION,
    has_specs BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    capture_meta TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_face_embeddings_person_id ON face_embeddings (person_id);

CREATE TABLE IF NOT EXISTS attendance_sessions (
    id SERIAL PRIMARY KEY,
    session_name VARCHAR(140) NOT NULL,
    session_type VARCHAR(40) NOT NULL,
    course_id INTEGER REFERENCES courses (id) ON DELETE SET NULL,
    batch_id INTEGER REFERENCES batches (id) ON DELETE SET NULL,
    category_program VARCHAR(120),
    batch_name VARCHAR(120),
    timing_id INTEGER REFERENCES timings (id),
    session_date DATE NOT NULL,
    start_time TIME,
    grace_time TIME,
    end_time TIME,
    status VARCHAR(30) NOT NULL DEFAULT 'scheduled',
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_attendance_sessions_session_date ON attendance_sessions (session_date);
CREATE INDEX IF NOT EXISTS ix_attendance_sessions_course_id ON attendance_sessions (course_id);
CREATE INDEX IF NOT EXISTS ix_attendance_sessions_batch_id ON attendance_sessions (batch_id);

CREATE TABLE IF NOT EXISTS attendance_records (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES attendance_sessions (id),
    person_id INTEGER REFERENCES user_management (id) ON DELETE SET NULL,
    person_code VARCHAR(80),
    person_name VARCHAR(160),
    person_type VARCHAR(30),
    course_id INTEGER REFERENCES courses (id) ON DELETE SET NULL,
    batch_id INTEGER REFERENCES batches (id) ON DELETE SET NULL,
    category_program VARCHAR(120),
    batch_name VARCHAR(120),
    level_class VARCHAR(120),
    attendance_date DATE NOT NULL,
    marked_time TIMESTAMP NOT NULL DEFAULT now(),
    status VARCHAR(40) NOT NULL,
    confidence_score DOUBLE PRECISION,
    recognition_method VARCHAR(40) NOT NULL DEFAULT 'face_ai',
    device_name VARCHAR(120),
    marked_by VARCHAR(120),
    duplicate_flag BOOLEAN NOT NULL DEFAULT FALSE,
    sync_status VARCHAR(30) NOT NULL DEFAULT 'pending',
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
-- One attendance record per person, session and day.
CREATE UNIQUE INDEX IF NOT EXISTS uq_attendance_session_person_date
    ON attendance_records (session_id, person_id, attendance_date);
CREATE INDEX IF NOT EXISTS ix_attendance_records_session_id ON attendance_records (session_id);
CREATE INDEX IF NOT EXISTS ix_attendance_records_person_id ON attendance_records (person_id);
CREATE INDEX IF NOT EXISTS ix_attendance_records_course_id ON attendance_records (course_id);
CREATE INDEX IF NOT EXISTS ix_attendance_records_batch_id ON attendance_records (batch_id);
CREATE INDEX IF NOT EXISTS ix_attendance_records_attendance_date ON attendance_records (attendance_date);

CREATE TABLE IF NOT EXISTS sheet_sync_logs (
    id SERIAL PRIMARY KEY,
    attendance_record_id INTEGER REFERENCES attendance_records (id),
    sheet_name VARCHAR(140),
    sync_status VARCHAR(30) NOT NULL,
    request_payload TEXT,
    response_message TEXT,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

-- The people who may log in to the console (005). Separate from user_management, where person_type
-- 'admin' means a staff member. The email is stored in small letters; password_hash is an Argon2id
-- hash, never a password. Times are UTC.
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

-- One row for each device an account is logged in on. token_hash is the SHA-256 of the refresh
-- token; the token itself is only ever in the browser's cookie.
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

-- Who did what, and when (006). Rows are only ever added. actor_id is empty for a failed login and
-- for the command-line tool; details is JSON without passwords, tokens, hashes or face data. Times are UTC.
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

-- Problems reported from the console (007). reported_by is the account that was logged in; accounts
-- are disabled, never deleted (RESTRICT). page_url is a path inside the console; device_info is JSON
-- with the browser, the OS and the screen. A resolved issue always has a resolution note. Times are UTC.
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

-- The thread under an issue (007). Comments are never changed or removed by the app.
CREATE TABLE IF NOT EXISTS issue_comments (
    id SERIAL PRIMARY KEY,
    issue_id INTEGER NOT NULL REFERENCES issues (id) ON DELETE CASCADE,
    author_id INTEGER NOT NULL REFERENCES admin_accounts (id) ON DELETE RESTRICT,
    body TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS ix_issue_comments_issue_id ON issue_comments (issue_id);

-- Row level security switched on, with no policy, on every table (migrations 005 to 008). Supabase
-- publishes the public schema through its REST API and grants its anon and authenticated roles access
-- by default; with row level security on and no policy they get no rows (tests/test_postgres.py shows
-- it with those grants). Roles that bypass it are not affected: the tables' owner (the backend
-- connects as that), a superuser, a role with BYPASSRLS such as Supabase's service_role.
ALTER TABLE courses ENABLE ROW LEVEL SECURITY;
ALTER TABLE batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE timings ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_management ENABLE ROW LEVEL SECURITY;
ALTER TABLE face_enrollments ENABLE ROW LEVEL SECURITY;
ALTER TABLE face_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE attendance_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE attendance_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE sheet_sync_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE issue_comments ENABLE ROW LEVEL SECURITY;

-- The backend's least-privilege account (migration 009): reads and writes rows through a policy of its
-- own, cannot change the schema, and may only add to the audit log. Created without a login: see 009.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vernex_app') THEN
        CREATE ROLE vernex_app NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO vernex_app;

DO $$
DECLARE
    name text;
BEGIN
    FOREACH name IN ARRAY ARRAY[
        'courses', 'batches', 'timings', 'user_management', 'face_enrollments', 'face_embeddings',
        'attendance_sessions', 'attendance_records', 'sheet_sync_logs',
        'admin_accounts', 'admin_sessions', 'issues', 'issue_comments', 'audit_logs'
    ]
    LOOP
        IF to_regclass('public.' || quote_ident(name)) IS NOT NULL THEN
            IF name = 'audit_logs' THEN
                EXECUTE format('GRANT SELECT, INSERT ON public.%I TO vernex_app', name);
            ELSE
                EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO vernex_app', name);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = name AND policyname = 'vernex_app_all') THEN
                EXECUTE format('CREATE POLICY vernex_app_all ON public.%I FOR ALL TO vernex_app USING (true) WITH CHECK (true)', name);
            END IF;
        END IF;
    END LOOP;
END $$;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO vernex_app;
