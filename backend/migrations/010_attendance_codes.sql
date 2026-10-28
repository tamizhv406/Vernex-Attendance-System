-- Attendance codes for QR attendance. Applied automatically at startup on SQLite (app/schema.py:
-- upgrade_existing_tables); on PostgreSQL apply it by hand, as the owner, after 009. Both statements
-- add something and change no existing row. Can be run again safely.
--
-- Then give every existing person a code (the codes are random, so SQL does not make them):
--     python scripts/backfill_attendance_codes.py --dry-run
--     python scripts/backfill_attendance_codes.py
--
-- Row level security (008) and the vernex_app role (009) are per table, so the new column needs
-- nothing more from them.

-- The random code a person's QR card holds, uppercase without the hyphen (K7M29QXD). Empty until the
-- backfill (or the backend, for a new person) gives one.
ALTER TABLE user_management ADD COLUMN IF NOT EXISTS attendance_code VARCHAR(16);

-- One person per code. Rows without a code yet (NULL) do not conflict with each other.
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_management_attendance_code
    ON user_management (attendance_code);
