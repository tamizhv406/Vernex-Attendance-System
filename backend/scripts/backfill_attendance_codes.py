"""Give every person without an attendance code one. Run once on PostgreSQL after migration 010.

    python scripts/backfill_attendance_codes.py --dry-run    # only counts, writes nothing
    python scripts/backfill_attendance_codes.py

DATABASE_URL is read the way the backend reads it (backend/.env, then the environment). Codes that
people already have are never changed, so running it again changes nothing. It refuses to run until
migration 010 is in place: without its unique index two people could end up with one code.

Printed: counts only. Never a code, a name, the address, the user name or the password.

Exit code: 0 done (or nothing to do), 1 migration 010 is missing, 2 the codes could not be written.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker

from app.models.person import Person
from app.schema import ATTENDANCE_CODE_INDEX
from app.services.attendance_code_service import fill_missing_codes


def migration_problem(connection):
    # What is missing for codes to be written safely, or None.
    inspector = inspect(connection)
    if "user_management" not in inspector.get_table_names():
        return "table user_management is missing"
    if "attendance_code" not in {column["name"] for column in inspector.get_columns("user_management")}:
        return "user_management has no attendance_code column"
    if ATTENDANCE_CODE_INDEX not in {index["name"] for index in inspector.get_indexes("user_management")}:
        return f"user_management has no {ATTENDANCE_CODE_INDEX} index"
    return None


def run(engine, dry_run=False, out=print):
    with engine.connect() as connection:
        problem = migration_problem(connection)
    if problem:
        out(f"Not ready: {problem}. Apply backend/migrations/010_attendance_codes.sql first. Nothing was changed.")
        return 1
    session = sessionmaker(bind=engine)()
    try:
        total = session.query(Person).count()
        missing = session.query(Person).filter(Person.attendance_code.is_(None)).count()
        if dry_run:
            out(f"Dry run: {missing} of {total} people have no attendance code and would get one. Nothing was changed.")
            return 0
        if not missing:
            out(f"Nothing to do: all {total} people already have an attendance code.")
            return 0
        filled = fill_missing_codes(session)
    except Exception as error:
        session.rollback()
        # The error's own text can quote rows; only its kind is shown.
        out(f"The codes could not be written ({type(error).__name__}). Nothing was changed.")
        return 2
    finally:
        session.close()
    out(f"Gave {filled} people an attendance code. {total - missing} already had one and were left as they were.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Give every person without an attendance code one.")
    parser.add_argument("--dry-run", action="store_true", help="only count the people without a code; write nothing")
    args = parser.parse_args()
    from app.database import engine

    sys.exit(run(engine, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
