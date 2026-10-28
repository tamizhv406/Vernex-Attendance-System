"""Which database the backend opens, and when it refuses to start on one.

Until October 2026 a relative SQLite path was the current folder's, and SQLite creates a file that is
not there: the backend started from another folder (or with DATABASE_URL lost) opened a new, empty
database, and every password was "incorrect". create_super_admin.py, run from the project folder as
setup.bat says, wrote its account into yet another file. Every database here is a temporary file.
"""
import importlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import BACKEND_DIR, Base, clean_database_url, require_database_file, require_login_accounts
from conftest import add_account


@pytest.mark.parametrize("folder", ["backend", "project", "elsewhere"])
def test_a_relative_sqlite_path_is_the_backend_folders_wherever_the_process_starts(monkeypatch, tmp_path, folder):
    monkeypatch.chdir({"backend": BACKEND_DIR, "project": BACKEND_DIR.parent, "elsewhere": tmp_path}[folder])

    assert clean_database_url("sqlite:///./vernex_local_test.db") == f"sqlite:///{BACKEND_DIR / 'vernex_local_test.db'}"
    assert clean_database_url("sqlite:///vernex_attendance.db") == f"sqlite:///{BACKEND_DIR / 'vernex_attendance.db'}"


@pytest.mark.parametrize("url", ["sqlite:///:memory:", "sqlite://", "postgresql://vernex_app:secret@db.example.org:6543/postgres"])
def test_other_urls_are_left_as_they_are(url):
    assert clean_database_url(url) == url


def test_an_absolute_sqlite_path_is_kept(tmp_path):
    path = tmp_path / "school.db"

    assert clean_database_url(f"sqlite:///{path}") == f"sqlite:///{path}"


def test_a_missing_sqlite_file_is_refused_and_not_created(tmp_path):
    path = tmp_path / "typo.db"

    with pytest.raises(RuntimeError) as refused:
        require_database_file(f"sqlite:///{path}")

    assert str(path) in str(refused.value) and "DATABASE_URL" in str(refused.value)
    assert not path.exists()


def test_an_existing_file_and_a_database_in_memory_are_accepted(tmp_path):
    path = tmp_path / "school.db"
    path.touch()

    require_database_file(f"sqlite:///{path}")
    require_database_file("sqlite:///:memory:")


def sqlite_database(path, accounts):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine)
    with sessionmaker(bind=engine)() as db:
        for number in range(accounts):
            add_account(db, f"admin{number}@example.com")
    return engine


def test_a_database_without_a_login_account_is_refused(tmp_path):
    engine = sqlite_database(tmp_path / "empty.db", accounts=0)
    try:
        with pytest.raises(RuntimeError, match="has no login accounts"):
            require_login_accounts(engine)
    finally:
        engine.dispose()


def test_a_database_with_an_account_is_accepted(tmp_path):
    engine = sqlite_database(tmp_path / "school.db", accounts=1)
    try:
        require_login_accounts(engine)
    finally:
        engine.dispose()


def test_the_backend_refuses_to_start_on_a_missing_database_and_touches_nothing(monkeypatch, tmp_path):
    from app import database
    main = importlib.import_module("app.main")

    touched = []
    missing = tmp_path / "vernex_attendance.db"
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{missing}")
    monkeypatch.setattr(main, "init_database_schema", lambda: touched.append("database"))
    monkeypatch.setattr(main, "warm_up", lambda: touched.append("models"))

    with pytest.raises(RuntimeError, match="does not exist"):
        main.startup()

    assert touched == [] and not missing.exists()


def test_the_backend_refuses_to_start_on_a_database_nobody_can_log_in_to(monkeypatch, tmp_path):
    main = importlib.import_module("app.main")

    touched = []
    engine = sqlite_database(tmp_path / "empty.db", accounts=0)
    monkeypatch.setattr(main, "require_database_file", lambda: None)
    monkeypatch.setattr(main, "init_database_schema", lambda: None)
    monkeypatch.setattr(main, "require_login_accounts", lambda: require_login_accounts(engine))
    monkeypatch.setattr(main, "warm_up", lambda: touched.append("models"))
    try:
        with pytest.raises(RuntimeError, match="has no login accounts"):
            main.startup()
    finally:
        engine.dispose()

    assert touched == []


def test_the_template_and_the_guides_name_the_database_the_backend_opens():
    # The documented default is backend\vernex_attendance.db; it now is, wherever the backend starts.
    assert clean_database_url("sqlite:///./vernex_attendance.db").endswith(str(Path("backend") / "vernex_attendance.db"))
