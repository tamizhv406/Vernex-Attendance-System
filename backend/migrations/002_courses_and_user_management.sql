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

DO $$
BEGIN
    IF to_regclass('public.people') IS NOT NULL THEN
        INSERT INTO user_management (
            id, person_code, full_name, phone, email, person_type, gender, guardian_name, guardian_phone,
            category_program, batch_name, level_class, designation, department, membership_type, plan_name,
            timing_id, joining_date, status, face_enrollment_status, notes, created_at, updated_at
        )
        SELECT
            id, person_code, full_name, phone, email,
            CASE WHEN lower(person_type) = 'staff' THEN 'admin' ELSE lower(person_type) END,
            gender, guardian_name, guardian_phone, category_program, batch_name, level_class, designation,
            department, membership_type, plan_name, timing_id, joining_date, status, face_enrollment_status,
            notes, created_at, updated_at
        FROM people
        ON CONFLICT (person_code) DO NOTHING;
    END IF;
END $$;

INSERT INTO courses (name)
SELECT DISTINCT category_program FROM user_management
WHERE category_program IS NOT NULL AND trim(category_program) <> ''
ON CONFLICT (name) DO NOTHING;

INSERT INTO course_batches (name)
SELECT DISTINCT batch_name FROM user_management
WHERE batch_name IS NOT NULL AND trim(batch_name) <> ''
ON CONFLICT (name) DO NOTHING;

SELECT setval(pg_get_serial_sequence('user_management', 'id'), COALESCE((SELECT MAX(id) FROM user_management), 1), true);

DO $$
BEGIN
    ALTER TABLE face_enrollments DROP CONSTRAINT IF EXISTS face_enrollments_person_id_fkey;
    ALTER TABLE face_enrollments ADD CONSTRAINT face_enrollments_person_id_fkey
        FOREIGN KEY (person_id) REFERENCES user_management(id) ON DELETE CASCADE;

    ALTER TABLE face_embeddings DROP CONSTRAINT IF EXISTS face_embeddings_person_id_fkey;
    ALTER TABLE face_embeddings ADD CONSTRAINT face_embeddings_person_id_fkey
        FOREIGN KEY (person_id) REFERENCES user_management(id) ON DELETE CASCADE;

    ALTER TABLE attendance_records DROP CONSTRAINT IF EXISTS attendance_records_person_id_fkey;
    ALTER TABLE attendance_records ADD CONSTRAINT attendance_records_person_id_fkey
        FOREIGN KEY (person_id) REFERENCES user_management(id) ON DELETE SET NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_courses_name ON courses(name);
CREATE INDEX IF NOT EXISTS idx_course_batches_name ON course_batches(name);
CREATE INDEX IF NOT EXISTS idx_user_management_type ON user_management(person_type);
CREATE INDEX IF NOT EXISTS idx_user_management_category ON user_management(category_program);
CREATE INDEX IF NOT EXISTS idx_user_management_batch ON user_management(batch_name);
