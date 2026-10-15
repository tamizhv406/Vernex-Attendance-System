from sqlalchemy import inspect, text

from app.database import Base, engine
from app.models.admin_account import AdminAccount, AdminSession
from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.audit_log import AuditLog
from app.models.course import Course, CourseBatch
from app.models.face_embedding import FaceEmbedding, FaceEnrollment
from app.models.issue import Issue, IssueComment
from app.models.person import Person
from app.models.sync_log import SheetSyncLog
from app.models.timing import Timing


POSTGRES_REPAIR_STATEMENTS = [
    """
    ALTER TABLE courses ADD COLUMN IF NOT EXISTS course_code VARCHAR(40)
    """,
    """
    ALTER TABLE courses ADD COLUMN IF NOT EXISTS course_name VARCHAR(120)
    """,
    """
    ALTER TABLE courses ADD COLUMN IF NOT EXISTS description TEXT
    """,
    """
    ALTER TABLE courses ADD COLUMN IF NOT EXISTS status VARCHAR(30) NOT NULL DEFAULT 'active'
    """,
    """
    ALTER TABLE courses ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    """,
    """
    ALTER TABLE courses ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    """,
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'courses'
              AND column_name = 'name'
        ) THEN
            UPDATE courses
            SET
                course_name = COALESCE(course_name, name, 'Course ' || id::text),
                course_code = COALESCE(
                    course_code,
                    upper(regexp_replace(COALESCE(name, 'COURSE'), '[^a-zA-Z0-9]+', '-', 'g')) || '-' || id::text
                )
            WHERE course_name IS NULL OR course_code IS NULL;
        ELSE
            UPDATE courses
            SET
                course_name = COALESCE(course_name, 'Course ' || id::text),
                course_code = COALESCE(course_code, 'COURSE-' || id::text)
            WHERE course_name IS NULL OR course_code IS NULL;
        END IF;
    END $$;
    """,
    """
    ALTER TABLE courses ALTER COLUMN course_code SET NOT NULL
    """,
    """
    ALTER TABLE courses ALTER COLUMN course_name SET NOT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_courses_course_code_unique ON courses(course_code)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_courses_course_name ON courses(course_name)
    """,
    """
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
    )
    """,
    """
    DO $$
    BEGIN
        IF to_regclass('public.course_batches') IS NOT NULL THEN
            INSERT INTO batches (id, course_id, batch_name, status, created_at, updated_at)
            SELECT
                cb.id,
                cb.course_id,
                cb.name,
                COALESCE(cb.status, 'active'),
                COALESCE(cb.created_at, CURRENT_TIMESTAMP),
                COALESCE(cb.updated_at, CURRENT_TIMESTAMP)
            FROM course_batches cb
            WHERE cb.course_id IS NOT NULL
              AND cb.name IS NOT NULL
            ON CONFLICT DO NOTHING;
        END IF;
    END $$;
    """,
    """
    SELECT setval(pg_get_serial_sequence('batches', 'id'), COALESCE((SELECT MAX(id) FROM batches), 1), true)
    """,
    """
    ALTER TABLE user_management ADD COLUMN IF NOT EXISTS course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL
    """,
    """
    ALTER TABLE user_management ADD COLUMN IF NOT EXISTS batch_id INTEGER REFERENCES batches(id) ON DELETE SET NULL
    """,
    """
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
    """,
    """
    UPDATE user_management u
    SET course_id = c.id
    FROM courses c
    WHERE u.course_id IS NULL
      AND u.category_program IS NOT NULL
      AND lower(u.category_program) IN (lower(c.course_name), lower(c.course_code))
    """,
    """
    UPDATE user_management u
    SET batch_id = b.id
    FROM batches b
    WHERE u.batch_id IS NULL
      AND u.batch_name IS NOT NULL
      AND lower(u.batch_name) = lower(b.batch_name)
      AND (u.course_id IS NULL OR u.course_id = b.course_id)
    """,
    """
    SELECT setval(pg_get_serial_sequence('user_management', 'id'), COALESCE((SELECT MAX(id) FROM user_management), 1), true)
    """,
    """
    ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL
    """,
    """
    ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS batch_id INTEGER REFERENCES batches(id) ON DELETE SET NULL
    """,
    """
    UPDATE attendance_sessions s
    SET course_id = c.id
    FROM courses c
    WHERE s.course_id IS NULL
      AND s.category_program IS NOT NULL
      AND lower(s.category_program) IN (lower(c.course_name), lower(c.course_code))
    """,
    """
    UPDATE attendance_sessions s
    SET batch_id = b.id
    FROM batches b
    WHERE s.batch_id IS NULL
      AND s.batch_name IS NOT NULL
      AND lower(s.batch_name) = lower(b.batch_name)
      AND (s.course_id IS NULL OR s.course_id = b.course_id)
    """,
    """
    ALTER TABLE attendance_records ADD COLUMN IF NOT EXISTS course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL
    """,
    """
    ALTER TABLE attendance_records ADD COLUMN IF NOT EXISTS batch_id INTEGER REFERENCES batches(id) ON DELETE SET NULL
    """,
    """
    UPDATE attendance_records r
    SET course_id = s.course_id
    FROM attendance_sessions s
    WHERE r.course_id IS NULL
      AND r.session_id = s.id
      AND s.course_id IS NOT NULL
    """,
    """
    UPDATE attendance_records r
    SET course_id = p.course_id
    FROM user_management p
    WHERE r.course_id IS NULL
      AND r.person_id = p.id
      AND p.course_id IS NOT NULL
    """,
    """
    UPDATE attendance_records r
    SET batch_id = s.batch_id
    FROM attendance_sessions s
    WHERE r.batch_id IS NULL
      AND r.session_id = s.id
      AND s.batch_id IS NOT NULL
    """,
    """
    UPDATE attendance_records r
    SET batch_id = p.batch_id
    FROM user_management p
    WHERE r.batch_id IS NULL
      AND r.person_id = p.id
      AND p.batch_id IS NOT NULL
    """,
    """
    DO $$
    BEGIN
        ALTER TABLE face_enrollments DROP CONSTRAINT IF EXISTS face_enrollments_person_id_fkey;
        ALTER TABLE face_enrollments ADD CONSTRAINT face_enrollments_person_id_fkey
            FOREIGN KEY (person_id) REFERENCES user_management(id) ON DELETE CASCADE NOT VALID;
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END $$;
    """,
    """
    DO $$
    BEGIN
        ALTER TABLE face_embeddings DROP CONSTRAINT IF EXISTS face_embeddings_person_id_fkey;
        ALTER TABLE face_embeddings ADD CONSTRAINT face_embeddings_person_id_fkey
            FOREIGN KEY (person_id) REFERENCES user_management(id) ON DELETE CASCADE NOT VALID;
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END $$;
    """,
    """
    DO $$
    BEGIN
        ALTER TABLE attendance_records DROP CONSTRAINT IF EXISTS attendance_records_person_id_fkey;
        ALTER TABLE attendance_records ADD CONSTRAINT attendance_records_person_id_fkey
            FOREIGN KEY (person_id) REFERENCES user_management(id) ON DELETE SET NULL NOT VALID;
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END $$;
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_batches_course_id ON batches(course_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_user_management_course_id ON user_management(course_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_user_management_batch_id ON user_management(batch_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_attendance_sessions_course_batch ON attendance_sessions(course_id, batch_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_attendance_records_course_batch ON attendance_records(course_id, batch_id)
    """,
    # Row level security switched on, with no policy, for the login tables, the audit log and the
    # reported issues. It is meant to keep Supabase's own REST API (the anon and authenticated roles)
    # away from them, so that this backend is the way in; switching it on does not show by itself that
    # they are kept out. Roles that bypass it (the tables' owner, which this backend connects as, a
    # superuser, Supabase's service_role) are not affected, and what each role is granted is checked
    # on the real database in Phase 4 (S-02). Switching it on again where it is on changes nothing.
    """
    ALTER TABLE admin_accounts ENABLE ROW LEVEL SECURITY
    """,
    """
    ALTER TABLE admin_sessions ENABLE ROW LEVEL SECURITY
    """,
    """
    ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY
    """,
    """
    ALTER TABLE issues ENABLE ROW LEVEL SECURITY
    """,
    """
    ALTER TABLE issue_comments ENABLE ROW LEVEL SECURITY
    """,
]


def init_database_schema(bind=None) -> None:
    bind = bind or engine
    Base.metadata.create_all(bind=bind)

    if bind.dialect.name == "postgresql":
        with bind.begin() as connection:
            for statement in POSTGRES_REPAIR_STATEMENTS:
                connection.execute(text(statement))
    upgrade_existing_tables(bind)


def upgrade_existing_tables(bind) -> None:
    # create_all only makes missing tables. A database made by an earlier version gets the newer
    # columns and index here. Every step adds something; the one that changes existing rows is the
    # has_been_super_admin backfill below, which only ever sets that flag on current super admins.
    with bind.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("face_embeddings")}
        if "capture_meta" not in columns:
            connection.execute(text("ALTER TABLE face_embeddings ADD COLUMN capture_meta TEXT"))
        # Login accounts made before temporary passwords expired. Empty for all of them: a password
        # given out before this existed keeps working until it is changed, as it always did.
        columns = {column["name"] for column in inspect(connection).get_columns("admin_accounts")}
        if "temporary_password_expires_at" not in columns:
            connection.execute(text("ALTER TABLE admin_accounts ADD COLUMN temporary_password_expires_at TIMESTAMP"))
        # Accounts that are or have been a super admin, whose password the portal never resets.
        if "has_been_super_admin" not in columns:
            no = "0" if connection.dialect.name == "sqlite" else "FALSE"
            connection.execute(text(f"ALTER TABLE admin_accounts ADD COLUMN has_been_super_admin BOOLEAN NOT NULL DEFAULT {no}"))
        # Every super admin has held the role: the ones from before the column existed, and any written
        # into the table by hand. It only ever sets the flag, so running it on every start changes nothing more.
        connection.execute(
            text("UPDATE admin_accounts SET has_been_super_admin = :yes WHERE role = 'super_admin' AND has_been_super_admin = :no"),
            {"yes": True, "no": False},
        )

        index = next(item for item in AttendanceRecord.__table__.indexes if item.name == "uq_attendance_session_person_date")
        if index.name in {item["name"] for item in inspect(connection).get_indexes("attendance_records")}:
            return
        duplicates = connection.execute(text(
            "SELECT COUNT(*) FROM (SELECT 1 FROM attendance_records WHERE session_id IS NOT NULL AND person_id IS NOT NULL "
            "GROUP BY session_id, person_id, attendance_date HAVING COUNT(*) > 1) AS repeated"
        )).scalar()
        if duplicates:
            # Never deleted automatically: someone has to decide which of the records is the real one.
            print(f"WARNING: {duplicates} person/session/day combinations have more than one attendance record. "
                  "The duplicate-protection index was NOT created. Remove the extra records and restart.")
            return
        index.create(bind=connection)
