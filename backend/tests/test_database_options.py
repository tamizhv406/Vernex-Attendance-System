"""How the backend connects to its database (app/database.py)."""
import pytest

from app.database import clean_database_url, connection_options


def test_sqlite_is_one_file_shared_by_the_threads():
    assert connection_options("sqlite:///./vernex_attendance.db") == {"connect_args": {"check_same_thread": False}}


@pytest.mark.parametrize("url", [
    "postgresql://postgres.ref:secret@aws-0-ap-south-1.pooler.supabase.com:6543/postgres",
    "postgresql://app@db.example.org:5432/vernex",
])
def test_a_remote_postgresql_server_is_always_reached_encrypted(url):
    options = connection_options(url)

    assert options["connect_args"] == {"connect_timeout": 10, "sslmode": "require"}
    # Connections are checked and replaced before Supabase's pooler drops them.
    assert (options["pool_size"], options["max_overflow"], options["pool_recycle"]) == (5, 10, 300)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_a_server_on_this_computer_needs_no_encryption(host):
    assert connection_options(f"postgresql://vxadmin@{host}:5432/postgres")["connect_args"] == {"connect_timeout": 10}


def test_a_url_that_names_its_own_sslmode_keeps_it():
    options = connection_options("postgresql://app@db.example.org:5432/vernex?sslmode=verify-full")

    assert "sslmode" not in options["connect_args"]


@pytest.mark.parametrize("url, message", [
    ("postgresql://u:p@host:6543/postgres?pgbouncer=true", "pgbouncer"),
    ("postgresql://u:p@ss@host:6543/postgres", "@"),
])
def test_urls_that_cannot_work_are_explained(url, message):
    with pytest.raises(ValueError) as refused:
        clean_database_url(url)

    assert message in str(refused.value)
