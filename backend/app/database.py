from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
MISSING_DATABASE = (
    "The database file {path} does not exist, and the backend does not create an empty one: nobody could "
    "log in to it. Check DATABASE_URL in backend\\.env. For a new installation, create the database and its "
    "first super admin with:  .venv\\Scripts\\python scripts\\create_super_admin.py  (in backend\\)"
)
NO_LOGIN_ACCOUNTS = (
    "The database {path} has no login accounts, so nobody could log in. If it is not the database you "
    "use, correct DATABASE_URL in backend\\.env. If it is a new one, create its first super admin with:  "
    ".venv\\Scripts\\python scripts\\create_super_admin.py  (in backend\\)"
)


def sqlite_file(url: str) -> Path | None:
    """The file a SQLite URL opens, or None: another kind of database, or one in memory."""
    parsed = make_url(url)
    if not parsed.drivername.startswith("sqlite") or parsed.database in (None, "", ":memory:") or parsed.database.startswith("file:"):
        return None
    return Path(parsed.database)


def clean_database_url(raw_url: str) -> str:
    url = (raw_url or "").strip().strip("\"'")
    if "pgbouncer=true" in url.lower():
        raise ValueError("Remove '?pgbouncer=true' from DATABASE_URL. Use the Supabase pooler host/port directly.")
    parsed = make_url(url)
    if parsed.host and "@" in parsed.host:
        raise ValueError("DATABASE_URL host contains '@'. Your password likely has an unencoded '@'. Encode '@' as '%40' and '%' as '%25'.")
    path = sqlite_file(url)
    if path is not None and not path.is_absolute():
        # A relative SQLite path is the backend folder's, wherever the process starts. Until October 2026
        # it was the current folder's: the backend (started in backend\) and create_super_admin.py (run
        # from the project folder, as setup.bat says) each opened a file of their own.
        url = parsed.set(database=str((BACKEND_DIR / path).resolve())).render_as_string(hide_password=False)
    return url


LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def connection_options(url: str) -> dict:
    # How the engine connects. SQLite: one file, shared by the threads of the one process.
    # PostgreSQL: give up after 10 seconds, and always encrypted (task S-14) unless the server is on
    # this computer or the URL names its own sslmode. Connections are checked before use and replaced
    # after 5 minutes: Supabase's pooler closes connections that sit idle.
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    parsed = make_url(url)
    connect_args = {"connect_timeout": 10}
    if parsed.host not in LOCAL_HOSTS and "sslmode" not in parsed.query:
        connect_args["sslmode"] = "require"
    return {"connect_args": connect_args, "pool_size": 5, "max_overflow": 10, "pool_timeout": 30, "pool_recycle": 300}


DATABASE_URL = clean_database_url(settings.database_url)
# hide_parameters: a database error names the statement that failed but never the values that were
# in it. Those values are people's names and numbers and, for the login tables, password hashes.
engine = create_engine(DATABASE_URL, pool_pre_ping=True, hide_parameters=True, **connection_options(DATABASE_URL))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def require_database_file(url: str | None = None):
    """When the backend starts: a SQLite file that is not there is a wrong DATABASE_URL, not a new database.

    SQLite would create it empty, and the backend would start on it with nobody able to log in. The
    setup scripts (create_super_admin.py, init_db.py) still create a new database; the backend does not.
    """
    path = sqlite_file(url or DATABASE_URL)
    if path is not None and not path.exists():
        raise RuntimeError(MISSING_DATABASE.format(path=path))


def require_login_accounts(bind=None):
    """When the backend starts, after the schema: a SQLite database without one login account is refused.

    Only SQLite: a PostgreSQL database is set up with migrations and its own checks (scripts/check_database.py).
    """
    bind = bind or engine
    path = sqlite_file(bind.url.render_as_string(hide_password=False))
    if path is None:
        return
    with bind.connect() as connection:
        found = inspect(connection).has_table("admin_accounts") and connection.execute(text("SELECT 1 FROM admin_accounts LIMIT 1")).first()
    if not found:
        raise RuntimeError(NO_LOGIN_ACCOUNTS.format(path=path))


def get_db():
    db = SessionLocal()
    try:
        yield db
    except SQLAlchemyError:
        db.rollback()
        raise
    finally:
        db.close()
