"""Check the database the backend is set up for, without changing anything and without showing secrets.

    python scripts/check_database.py

DATABASE_URL is read the way the backend reads it (backend/.env, then the environment). What is
printed: the kind of database and its version, whether the connection works, whether the schema is
what this version of the backend needs (the check the backend runs when it starts, app/schema.py),
and on PostgreSQL whether the account it connects as can see every table and whether Supabase's
public roles (anon, authenticated) could reach a table that row level security does not protect.

Never printed: the address, the user name, the password, any row. Everything is read inside one
READ ONLY transaction, which the database itself refuses to write in, and it is rolled back.

Exit code: 0 ready, 1 the schema needs one of the files in backend/migrations, 2 no connection.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import settings
from app.database import clean_database_url, connection_options
from app.schema import ROW_SECURITY_TABLES, schema_problems

# Why a connection failed, in words, from what the driver said. The driver's own text names the
# host and the user, so it is never printed; only which of these it was.
CONNECTION_FAILURES = (
    ("password authentication failed", "the user name or the password was refused"),
    ("no pg_hba.conf entry", "the server does not accept connections from this computer"),
    ("could not translate host name", "the host name could not be found (check the address, or the internet connection)"),
    ("name or service not known", "the host name could not be found (check the address, or the internet connection)"),
    ("timeout", "the server did not answer in time"),
    ("timed out", "the server did not answer in time"),
    ("connection refused", "nothing is listening at that address and port"),
    ("does not exist", "the database or the user does not exist"),
    ("ssl", "the encrypted connection could not be set up"),
    ("tenant or user not found", "the Supabase pooler does not know that project or user"),
)


def why(error) -> str:
    said = str(getattr(error, "orig", None) or error).lower()
    return next((reason for clue, reason in CONNECTION_FAILURES if clue in said), f"connection failed ({type(error).__name__})")


def main() -> int:
    try:
        raw = clean_database_url(settings.database_url)
        url = make_url(raw)
    except Exception as error:
        print(f"DATABASE_URL cannot be used: {error if isinstance(error, ValueError) else type(error).__name__}")
        return 2
    kind = url.get_backend_name()
    print(f"Database kind: {kind}" + (" (local file)" if kind == "sqlite" else ""))
    # Connected the way the backend connects: encrypted to a remote PostgreSQL server.
    engine = create_engine(url, hide_parameters=True, **connection_options(raw))
    try:
        with engine.connect() as connection:
            if kind == "postgresql":
                # First statement of the transaction: from here on the server refuses any write.
                connection.execute(text("SET TRANSACTION READ ONLY"))
                version = connection.execute(text("SHOW server_version")).scalar()
            else:
                version = connection.execute(text("SELECT sqlite_version()")).scalar()
            print(f"Connection: works (server version {version})")
            problems = schema_problems(connection)
            if kind == "postgresql":
                report_roles(connection)
            connection.rollback()
    except Exception as error:
        print(f"Connection: failed, {why(error)}. Nothing was read or changed.")
        return 2
    finally:
        engine.dispose()
    if problems:
        print("Schema: NOT ready for this version of the backend:")
        for problem in problems:
            print(f"  - {problem}")
        print("Apply the SQL files in backend/migrations that this database does not have yet, in order "
              "(full_schema.sql for a new, empty database). This check changed nothing.")
        return 1
    print("Schema: ready (every table and column, the duplicate-attendance index"
          + (", row level security on every table" if kind == "postgresql" else "") + ").")
    return 0


def report_roles(connection):
    # The account the backend connects as, by its rights only, and the public roles of Supabase.
    me = connection.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
    owned = connection.execute(text(
        "SELECT count(*) FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' "
        "AND relname = ANY(:names) AND pg_has_role(current_user, relowner, 'USAGE')"
    ), {"names": list(ROW_SECURITY_TABLES)}).scalar()
    print(f"Backend account: superuser {'yes' if me.rolsuper else 'no'}, bypasses row level security "
          f"{'yes' if me.rolbypassrls else 'no'}, owns {owned} of the {len(ROW_SECURITY_TABLES)} tables")
    for role in ("anon", "authenticated"):
        if not connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}).first():
            continue
        reachable = connection.execute(text(
            "SELECT c.relname FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' "
            "AND NOT c.relrowsecurity AND (has_table_privilege(:role, c.oid, 'SELECT') "
            "OR has_table_privilege(:role, c.oid, 'INSERT') OR has_table_privilege(:role, c.oid, 'UPDATE') "
            "OR has_table_privilege(:role, c.oid, 'DELETE')) ORDER BY c.relname"
        ), {"role": role}).scalars().all()
        if reachable:
            print(f"Supabase role {role}: CAN reach {len(reachable)} table(s) without row level security: {', '.join(reachable)}")
        else:
            print(f"Supabase role {role}: no table without row level security is open to it")


if __name__ == "__main__":
    sys.exit(main())
