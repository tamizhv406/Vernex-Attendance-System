-- Row level security on EVERY table of this application, not only the login, audit and issue tables
-- (005 to 007). Supabase publishes the tables of the public schema through its REST API and, by
-- default, grants its anon and authenticated roles access to them, so a table without row level
-- security can be read and changed by anyone who has the project's URL and its public (anon) key:
-- students' names and phone numbers, attendance, and the face vectors in face_embeddings. With row
-- level security on and no policy, those roles get no rows at all.
--
-- The backend is not affected when it connects as the owner of the tables (it created them, or the
-- SQL editor did with the same role), as a superuser, or as a role with BYPASSRLS. Before applying
-- this to a database whose tables were created by another role, run scripts/check_database.py: it
-- says, without changing anything, whether the backend's role would still see the rows.
--
-- Can be run again safely; tables of earlier versions (people, course_batches) are included where
-- they still exist.
DO $$
DECLARE
    name text;
BEGIN
    FOREACH name IN ARRAY ARRAY[
        'courses', 'batches', 'timings', 'user_management', 'face_enrollments', 'face_embeddings',
        'attendance_sessions', 'attendance_records', 'sheet_sync_logs',
        'admin_accounts', 'admin_sessions', 'audit_logs', 'issues', 'issue_comments',
        'people', 'course_batches'
    ]
    LOOP
        IF to_regclass('public.' || quote_ident(name)) IS NOT NULL THEN
            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', name);
        END IF;
    END LOOP;
END $$;
