-- Complete current schema in one file, for creating a NEW empty PostgreSQL/Supabase database by hand.
-- It matches the SQLAlchemy models in app/models (generated from them) plus the foreign-key rules that
-- app/schema.py enforces on PostgreSQL.
--
-- You normally don't need to run anything: the backend creates and upgrades all tables on startup.
-- A database created by an older version is upgraded by 001 -> 004 (also applied automatically);
-- don't run this file on such a database. Every statement uses IF NOT EXISTS, so re-running it is safe.

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
