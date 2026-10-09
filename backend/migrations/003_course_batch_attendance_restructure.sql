ALTER TABLE courses ADD COLUMN IF NOT EXISTS course_code VARCHAR(40);
ALTER TABLE courses ADD COLUMN IF NOT EXISTS course_name VARCHAR(120);
ALTER TABLE courses ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE courses ADD COLUMN IF NOT EXISTS status VARCHAR(30) NOT NULL DEFAULT 'active';
ALTER TABLE courses ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE courses ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

UPDATE courses
SET
    course_name = COALESCE(course_name, name, course_code),
    course_code = COALESCE(course_code, upper(regexp_replace(COALESCE(name, 'COURSE-' || id::text), '[^a-zA-Z0-9]+', '-', 'g')))
WHERE course_name IS NULL OR course_code IS NULL;

ALTER TABLE courses ALTER COLUMN course_code SET NOT NULL;
ALTER TABLE courses ALTER COLUMN course_name SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_courses_course_code_unique ON courses (course_code);
CREATE INDEX IF NOT EXISTS idx_courses_course_name ON courses (course_name);

CREATE TABLE IF NOT EXISTS batches (
    id SERIAL PRIMARY KEY,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    batch_name VARCHAR(120) NOT NULL,
    batch_level VARCHAR(120),
    timing_id INTEGER REFERENCES timings(id) ON DELETE SET NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_batches_course_name UNIQUE (course_id, batch_name)
);

INSERT INTO batches (id, course_id, batch_name, status, created_at, updated_at)
SELECT
    cb.id,
    COALESCE(cb.course_id, c.id),
    cb.name,
    COALESCE(cb.status, 'active'),
    COALESCE(cb.created_at, CURRENT_TIMESTAMP),
    COALESCE(cb.updated_at, CURRENT_TIMESTAMP)
FROM course_batches cb
LEFT JOIN courses c ON lower(c.course_name) = lower(cb.name) OR lower(c.course_code) = lower(cb.name)
WHERE to_regclass('public.course_batches') IS NOT NULL
  AND cb.name IS NOT NULL
  AND COALESCE(cb.course_id, c.id) IS NOT NULL
ON CONFLICT (id) DO NOTHING;

SELECT setval(pg_get_serial_sequence('batches', 'id'), COALESCE((SELECT MAX(id) FROM batches), 1), true);

ALTER TABLE user_management ADD COLUMN IF NOT EXISTS course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL;
ALTER TABLE user_management ADD COLUMN IF NOT EXISTS batch_id INTEGER REFERENCES batches(id) ON DELETE SET NULL;

UPDATE user_management u
SET course_id = c.id
FROM courses c
WHERE u.course_id IS NULL
  AND u.category_program IS NOT NULL
  AND lower(u.category_program) IN (lower(c.course_name), lower(c.course_code));

UPDATE user_management u
SET batch_id = b.id
FROM batches b
WHERE u.batch_id IS NULL
  AND u.batch_name IS NOT NULL
  AND lower(u.batch_name) = lower(b.batch_name)
  AND (u.course_id IS NULL OR u.course_id = b.course_id);

ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL;
ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS batch_id INTEGER REFERENCES batches(id) ON DELETE SET NULL;

UPDATE attendance_sessions s
SET course_id = c.id
FROM courses c
WHERE s.course_id IS NULL
  AND s.category_program IS NOT NULL
  AND lower(s.category_program) IN (lower(c.course_name), lower(c.course_code));

UPDATE attendance_sessions s
SET batch_id = b.id
FROM batches b
WHERE s.batch_id IS NULL
  AND s.batch_name IS NOT NULL
  AND lower(s.batch_name) = lower(b.batch_name)
  AND (s.course_id IS NULL OR s.course_id = b.course_id);

ALTER TABLE attendance_records ADD COLUMN IF NOT EXISTS course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL;
ALTER TABLE attendance_records ADD COLUMN IF NOT EXISTS batch_id INTEGER REFERENCES batches(id) ON DELETE SET NULL;

UPDATE attendance_records r
SET course_id = COALESCE(s.course_id, p.course_id)
FROM attendance_sessions s
LEFT JOIN user_management p ON p.id = r.person_id
WHERE r.course_id IS NULL
  AND r.session_id = s.id;

UPDATE attendance_records r
SET batch_id = COALESCE(s.batch_id, p.batch_id)
FROM attendance_sessions s
LEFT JOIN user_management p ON p.id = r.person_id
WHERE r.batch_id IS NULL
  AND r.session_id = s.id;

CREATE INDEX IF NOT EXISTS idx_batches_course_id ON batches(course_id);
CREATE INDEX IF NOT EXISTS idx_user_management_course_id ON user_management(course_id);
CREATE INDEX IF NOT EXISTS idx_user_management_batch_id ON user_management(batch_id);
CREATE INDEX IF NOT EXISTS idx_attendance_sessions_course_batch ON attendance_sessions(course_id, batch_id);
CREATE INDEX IF NOT EXISTS idx_attendance_records_course_batch ON attendance_records(course_id, batch_id);
