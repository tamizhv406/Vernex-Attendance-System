-- Applied automatically at startup (app/schema.py: upgrade_existing_tables). Kept here for databases
-- that are managed by hand. Both statements add something and change no existing row.

-- How each reference face was captured (JSON: detector, sizes, focus, consistency). No image is stored.
ALTER TABLE face_embeddings ADD COLUMN IF NOT EXISTS capture_meta TEXT;

-- One attendance record per person, session and day. Fails if duplicates already exist: find them with
--   SELECT session_id, person_id, attendance_date, COUNT(*) FROM attendance_records
--   GROUP BY 1, 2, 3 HAVING COUNT(*) > 1;
-- and remove the extra rows first.
CREATE UNIQUE INDEX IF NOT EXISTS uq_attendance_session_person_date
    ON attendance_records (session_id, person_id, attendance_date);
