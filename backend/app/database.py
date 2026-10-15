from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


def clean_database_url(raw_url: str) -> str:
    url = (raw_url or "").strip().strip("\"'")
    if "pgbouncer=true" in url.lower():
        raise ValueError("Remove '?pgbouncer=true' from DATABASE_URL. Use the Supabase pooler host/port directly.")
    parsed = make_url(url)
    if parsed.host and "@" in parsed.host:
        raise ValueError("DATABASE_URL host contains '@'. Your password likely has an unencoded '@'. Encode '@' as '%40' and '%' as '%25'.")
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


def get_db():
    db = SessionLocal()
    try:
        yield db
    except SQLAlchemyError:
        db.rollback()
        raise
    finally:
        db.close()
