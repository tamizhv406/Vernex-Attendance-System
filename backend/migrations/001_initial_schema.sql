CREATE TABLE IF NOT EXISTS courses (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) UNIQUE NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS course_batches (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) UNIQUE NOT NULL,
    course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_management (
    id SERIAL PRIMARY KEY,
    person_code VARCHAR(80) UNIQUE NOT NULL,
    full_name VARCHAR(160) NOT NULL,
    phone VARCHAR(20),
    email VARCHAR(160),
    person_type VARCHAR(30) NOT NULL CHECK (person_type IN ('student', 'member', 'admin')),
    gender VARCHAR(30),
    guardian_name VARCHAR(160),
    guardian_phone VARCHAR(20),
    category_program VARCHAR(120),
    batch_name VARCHAR(120),
    level_class VARCHAR(120),
    designation VARCHAR(120),
    department VARCHAR(120),
    membership_type VARCHAR(120),
    plan_name VARCHAR(120),
    timing_id INTEGER REFERENCES timings(id),
    joining_date DATE,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    face_enrollment_status VARCHAR(40) NOT NULL DEFAULT 'not_started',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS face_enrollments (
    id SERIAL PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES user_management(id) ON DELETE CASCADE,
    enrollment_status VARCHAR(50) NOT NULL DEFAULT 'not_started',
    current_step VARCHAR(40),
    total_steps INTEGER NOT NULL DEFAULT 5,
    completed_steps INTEGER NOT NULL DEFAULT 0,
    quality_score DOUBLE PRECISION,
    has_specs_reference BOOLEAN NOT NULL DEFAULT FALSE,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS face_embeddings (
    id SERIAL PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES user_management(id) ON DELETE CASCADE,
    embedding_vector TEXT NOT NULL,
    pose_type VARCHAR(40) NOT NULL,
    model_name VARCHAR(80) NOT NULL DEFAULT 'DeepFace',
    quality_score DOUBLE PRECISION,
    brightness_score DOUBLE PRECISION,
    blur_score DOUBLE PRECISION,
    face_angle DOUBLE PRECISION,
    has_specs BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attendance_sessions (
    id SERIAL PRIMARY KEY,
    session_name VARCHAR(140) NOT NULL,
    session_type VARCHAR(40) NOT NULL,
    category_program VARCHAR(120),
    batch_name VARCHAR(120),
    timing_id INTEGER REFERENCES timings(id),
    session_date DATE NOT NULL,
    start_time TIME,
    grace_time TIME,
    end_time TIME,
    status VARCHAR(30) NOT NULL DEFAULT 'scheduled',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attendance_records (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES attendance_sessions(id),
    person_id INTEGER REFERENCES user_management(id) ON DELETE SET NULL,
    person_code VARCHAR(80),
    person_name VARCHAR(160),
    person_type VARCHAR(30),
    category_program VARCHAR(120),
    batch_name VARCHAR(120),
    level_class VARCHAR(120),
    attendance_date DATE NOT NULL,
    marked_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(40) NOT NULL,
    confidence_score DOUBLE PRECISION,
    recognition_method VARCHAR(40) NOT NULL DEFAULT 'face_ai',
    device_name VARCHAR(120),
    marked_by VARCHAR(120),
    duplicate_flag BOOLEAN NOT NULL DEFAULT FALSE,
    sync_status VARCHAR(30) NOT NULL DEFAULT 'pending',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sheet_sync_logs (
    id SERIAL PRIMARY KEY,
    attendance_record_id INTEGER REFERENCES attendance_records(id),
    sheet_name VARCHAR(140),
    sync_status VARCHAR(30) NOT NULL,
    request_payload TEXT,
    response_message TEXT,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_courses_name ON courses(name);
CREATE INDEX IF NOT EXISTS idx_course_batches_name ON course_batches(name);
CREATE INDEX IF NOT EXISTS idx_user_management_type ON user_management(person_type);
CREATE INDEX IF NOT EXISTS idx_user_management_category ON user_management(category_program);
CREATE INDEX IF NOT EXISTS idx_user_management_batch ON user_management(batch_name);
CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance_records(attendance_date);
CREATE INDEX IF NOT EXISTS idx_attendance_person ON attendance_records(person_id);
