-- A database account for the backend with only what it needs (task S-02). Needs 008 first.
--
-- vernex_app may read and write rows of the application's tables and use their id sequences. It may
-- not create, change or drop anything, and the audit log is add-only for it (no UPDATE or DELETE).
-- Row level security stays on for every table: vernex_app gets rows through a policy written for it
-- alone (vernex_app_all); Supabase's anon and authenticated roles still have no policy and get nothing.
-- Migrations keep running as the owner (postgres), which is the "separate role" for schema changes.
--
-- The role is created without a login. To use it, give it one yourself, with a password generated
-- for it and kept out of every file and chat:
--     ALTER ROLE vernex_app WITH LOGIN PASSWORD '...';
-- then point DATABASE_URL at it (on Supabase's pooler the user name is vernex_app.<project-ref>) and run
-- scripts/check_database.py, which says whether the account can reach every table.
-- Can be run again safely.
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
