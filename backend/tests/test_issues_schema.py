"""The issues and their comments as tables (IR-01): the columns the task sheet names, the values the
database itself refuses, row level security, and the SQL files that describe the same tables.

PostgreSQL is not available to these tests, so what only PostgreSQL runs (the SQL files, row level
security, ON DELETE rules, which SQLite does not enforce here) is checked as text.
"""
import re
import typing
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.admin_account import AdminAccount
from app.models.course import Course
from app.models.issue import CATEGORIES, SEVERITIES, STATUSES, UNRESOLVED, Issue, IssueComment
from app.schema import POSTGRES_REPAIR_STATEMENTS, init_database_schema
from app.schemas import issue_schema
from app.utils.time_utils import utc_now

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
# In the order the task sheet lists them.
ISSUE_COLUMNS = ["id", "title", "description", "category", "severity", "status", "page_url", "device_info", "reported_by",
                 "assigned_to", "resolution_note", "created_at", "updated_at", "resolved_at"]
COMMENT_COLUMNS = ["id", "issue_id", "author_id", "body", "created_at"]


@pytest.fixture()
def reporter(db_session, make_account):
    return make_account(db_session, "asha@example.com").id


def issue(reporter_id, **fields):
    return Issue(**{"title": "The scanner froze", "description": "It stopped after the third face.", "category": "bug",
                    "severity": "medium", "reported_by": reporter_id, **fields})


def refused(db_session, row):
    db_session.add(row)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# ---- the tables ---------------------------------------------------------------------------------

def test_both_tables_have_the_columns_the_task_sheet_names(db_session):
    tables = inspect(db_session.get_bind())

    assert [column["name"] for column in tables.get_columns("issues")] == ISSUE_COLUMNS
    assert [column["name"] for column in tables.get_columns("issue_comments")] == COMMENT_COLUMNS
    assert [column.name for column in Issue.__table__.columns] == ISSUE_COLUMNS
    assert [column.name for column in IssueComment.__table__.columns] == COMMENT_COLUMNS


def test_the_allowed_values_are_the_task_sheets_and_the_api_checks_the_same_ones():
    assert CATEGORIES == ("bug", "face_recognition", "attendance_data", "camera_device", "login_access", "other")
    assert SEVERITIES == ("low", "medium", "high", "critical")
    assert STATUSES == ("open", "in_progress", "resolved", "closed")
    assert UNRESOLVED == ("open", "in_progress")
    assert typing.get_args(issue_schema.Category) == CATEGORIES
    assert typing.get_args(issue_schema.Severity) == SEVERITIES
    assert typing.get_args(issue_schema.Status) == STATUSES


def test_a_new_issue_is_open_and_its_times_are_utc(db_session, reporter):
    db_session.add(issue(reporter))
    db_session.commit()

    saved = db_session.query(Issue).one()
    assert (saved.status, saved.assigned_to, saved.resolution_note, saved.resolved_at, saved.page_url, saved.device_info) == ("open", None, None, None, None, None)
    assert abs((saved.created_at - utc_now()).total_seconds()) < 5 and saved.updated_at is not None


def test_an_issue_without_device_information_has_sql_null_not_the_json_value_null(db_session, reporter):
    db_session.add(issue(reporter, title="Without a device", device_info=None))
    db_session.add(issue(reporter, title="With a device", device_info={"browser": "Edge 141"}))
    db_session.commit()
    # The JSON value null, written by hand: a different thing, which IS NULL does not find.
    db_session.execute(text("INSERT INTO issues (title, description, category, severity, reported_by, device_info) "
                            "VALUES ('JSON null', 'Written straight into the table.', 'other', 'low', :who, 'null')"), {"who": reporter})
    db_session.commit()

    stored = dict(db_session.execute(text("SELECT title, device_info IS NULL FROM issues")).all())
    assert stored == {"Without a device": 1, "With a device": 0, "JSON null": 0}
    assert Issue.__table__.c.device_info.type.none_as_null is True
    # Read back, both empty kinds are None to the code.
    assert [row.device_info for row in db_session.query(Issue).order_by(Issue.id)] == [None, {"browser": "Edge 141"}, None]


def test_the_database_itself_fills_in_the_status_for_a_row_written_by_hand(db_session, reporter):
    db_session.execute(text("INSERT INTO issues (title, description, category, severity, reported_by) "
                            "VALUES ('By hand', 'Written straight into the table.', 'other', 'low', :who)"), {"who": reporter})
    db_session.commit()

    assert db_session.query(Issue).one().status == "open"


@pytest.mark.parametrize("fields", [{"category": "feature_request"}, {"category": "Bug"}, {"severity": "urgent"}, {"severity": ""},
                                    {"status": "done"}, {"status": "In Progress"}])
def test_a_value_outside_the_lists_is_refused_by_the_database(db_session, reporter, fields):
    refused(db_session, issue(reporter, **fields))

    assert db_session.query(Issue).count() == 0


@pytest.mark.parametrize("category", CATEGORIES)
@pytest.mark.parametrize("severity", SEVERITIES)
def test_every_category_and_severity_is_accepted(db_session, reporter, category, severity):
    db_session.add(issue(reporter, category=category, severity=severity))
    db_session.commit()


@pytest.mark.parametrize("note", [None, "", "   "])
def test_the_database_refuses_a_resolved_issue_without_a_note(db_session, reporter, note):
    refused(db_session, issue(reporter, status="resolved", resolution_note=note, resolved_at=utc_now()))


@pytest.mark.parametrize("status", STATUSES)
def test_with_a_note_any_status_is_accepted_and_without_one_any_but_resolved(db_session, reporter, status):
    db_session.add(issue(reporter, status=status, resolution_note="Restarted the camera service."))
    if status != "resolved":
        db_session.add(issue(reporter, status=status))
    db_session.commit()


def test_a_reported_issue_keeps_its_reporter_and_comments_go_with_their_issue():
    reporter = Issue.__table__.c.reported_by
    assignee = Issue.__table__.c.assigned_to
    comment_issue = IssueComment.__table__.c.issue_id
    author = IssueComment.__table__.c.author_id

    # Accounts are disabled, never deleted: one that reported or wrote something cannot be deleted
    # by hand either. Who an issue is assigned to is simply forgotten.
    assert (reporter.nullable, next(iter(reporter.foreign_keys)).ondelete) == (False, "RESTRICT")
    assert (author.nullable, next(iter(author.foreign_keys)).ondelete) == (False, "RESTRICT")
    assert (assignee.nullable, next(iter(assignee.foreign_keys)).ondelete) == (True, "SET NULL")
    assert (comment_issue.nullable, next(iter(comment_issue.foreign_keys)).ondelete) == (False, "CASCADE")
    for column in (reporter, assignee, author):
        assert next(iter(column.foreign_keys)).column.table.name == "admin_accounts"


def test_a_comment_belongs_to_an_issue_and_an_author(db_session, reporter):
    db_session.add(issue(reporter))
    db_session.commit()
    saved = db_session.query(Issue).one()
    db_session.add(IssueComment(issue_id=saved.id, author_id=reporter, body="Still happening."))
    db_session.commit()

    comment = db_session.query(IssueComment).one()
    assert (comment.issue_id, comment.author.email, comment.body) == (saved.id, "asha@example.com", "Still happening.")
    assert abs((comment.created_at - utc_now()).total_seconds()) < 5


@pytest.mark.parametrize("missing", ["title", "description", "category", "severity", "reported_by"])
def test_what_every_issue_has_cannot_be_left_out(db_session, reporter, missing):
    row = issue(reporter)
    setattr(row, missing, None)

    refused(db_session, row)


def test_the_tables_are_not_kept_with_the_people_whose_attendance_is_taken():
    assert {foreign.column.table.name for column in Issue.__table__.columns for foreign in column.foreign_keys} == {"admin_accounts"}


def test_a_database_from_an_earlier_version_gains_both_tables_and_keeps_its_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'older.db'}")
    older = [table for name, table in Base.metadata.tables.items() if name not in ("issues", "issue_comments")]
    Base.metadata.create_all(bind=engine, tables=older)
    with sessionmaker(bind=engine)() as db:
        db.add(Course(course_code="CS101", course_name="Computer Science"))
        db.add(AdminAccount(email="owner@example.com", full_name="Olivia Owner", password_hash="x", role="super_admin"))
        db.commit()

    init_database_schema(engine)
    init_database_schema(engine)  # every start of the backend runs it again

    assert {"issues", "issue_comments"} <= set(inspect(engine).get_table_names())
    with sessionmaker(bind=engine)() as db:
        assert [course.course_code for course in db.query(Course)] == ["CS101"]
        assert [account.email for account in db.query(AdminAccount)] == ["owner@example.com"]
        assert db.query(Issue).count() == 0
    engine.dispose()


# ---- PostgreSQL: checked as text, because these tests run on SQLite -----------------------------

def statements(sql):
    return [" ".join(statement.split()) for statement in re.sub(r"--[^\n]*", "", sql).split(";") if statement.strip()]


def table_body(sql, table):
    body = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", sql, re.S).group(1)
    lines = [line.strip().rstrip(",") for line in body.splitlines() if line.strip()]
    columns = {line.split()[0]: line for line in lines if not line.startswith("CONSTRAINT")}
    constraints = [" ".join(line.split()) for line in lines if line.startswith("CONSTRAINT")]
    return columns, constraints


@pytest.mark.parametrize("table", ["issues", "issue_comments"])
def test_startup_switches_row_level_security_on_for_both_tables_on_postgresql(table):
    assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in [" ".join(statement.split()) for statement in POSTGRES_REPAIR_STATEMENTS]
    # No policy is created, so it adds nothing a role could read through. That alone does not prove the
    # REST API is kept out: the grants of the anon and authenticated roles, and the roles that bypass
    # row level security, are checked on the real database in Phase 4 (S-02).
    assert not any("CREATE POLICY" in statement.upper() for statement in POSTGRES_REPAIR_STATEMENTS)


@pytest.mark.parametrize("file", ["007_issues.sql", "full_schema.sql"])
@pytest.mark.parametrize("model", [Issue, IssueComment], ids=["issues", "issue_comments"])
def test_the_sql_files_describe_the_same_tables_as_the_models(file, model):
    sql = (MIGRATIONS / file).read_text(encoding="utf-8")
    table = model.__table__
    columns, constraints = table_body(sql, table.name)

    assert list(columns) == [column.name for column in table.columns]
    for column in table.columns:
        line = columns[column.name]
        length = getattr(column.type, "length", None)
        if length:
            assert f"VARCHAR({length})" in line, line
        assert ("NOT NULL" in line or "PRIMARY KEY" in line) == (not column.nullable), line
        for foreign in column.foreign_keys:
            assert f"REFERENCES {foreign.column.table.name} ({foreign.column.name}) ON DELETE {foreign.ondelete}" in line, line
    # The same CHECK constraints, word for word, under the same names.
    checks = [f"CONSTRAINT {check.name} CHECK ({' '.join(str(check.sqltext).split())})" for check in table.constraints if check.name and check.name.startswith("ck_")]
    assert sorted(constraints) == sorted(checks)
    listed = statements(sql)
    for index in table.indexes:
        assert f"CREATE INDEX IF NOT EXISTS {index.name} ON {table.name} ({', '.join(column.name for column in index.columns)})" in listed
    assert f"ALTER TABLE {table.name} ENABLE ROW LEVEL SECURITY" in listed


def test_the_issue_table_has_its_four_checks():
    names = sorted(check.name for check in Issue.__table__.constraints if (check.name or "").startswith("ck_"))

    assert names == ["ck_issues_category", "ck_issues_resolution_note", "ck_issues_severity", "ck_issues_status"]


def test_the_migration_can_be_run_twice_and_touches_nothing_stored():
    listed = statements((MIGRATIONS / "007_issues.sql").read_text(encoding="utf-8"))

    assert listed, "007_issues.sql is empty"
    for statement in listed:
        if statement.startswith("CREATE"):
            assert "IF NOT EXISTS" in statement, statement
        assert not re.match(r"(DROP|TRUNCATE|DELETE|UPDATE|INSERT)\b", statement), statement
        if statement.startswith("ALTER TABLE"):
            # The only change to a table: switching row level security on, for the two new ones.
            assert re.fullmatch(r"ALTER TABLE (issues|issue_comments) ENABLE ROW LEVEL SECURITY", statement), statement
    assert not any("POLICY" in statement.upper() for statement in listed)


def test_the_full_schema_says_it_follows_the_migrations_up_to_009():
    assert "001 -> 009" in (MIGRATIONS / "full_schema.sql").read_text(encoding="utf-8")


def test_every_table_gets_row_level_security_from_the_migrations_and_the_backend():
    # Supabase hands its public (anon) key access to every table of the public schema that has row
    # level security off: face vectors and students' phone numbers included (tests/test_postgres.py).
    from app.database import Base
    from app.schema import ROW_SECURITY_TABLES

    tables = sorted(table.name for table in Base.metadata.sorted_tables)
    full = statements(re.sub(r"--[^\n]*", "", (MIGRATIONS / "full_schema.sql").read_text(encoding="utf-8")))
    repair = [" ".join(statement.split()) for statement in POSTGRES_REPAIR_STATEMENTS]
    later = re.sub(r"--[^\n]*", "", (MIGRATIONS / "008_row_level_security.sql").read_text(encoding="utf-8"))

    assert sorted(ROW_SECURITY_TABLES) == tables
    for name in tables:
        assert f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY" in full, name
        assert f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY" in repair, name
        assert f"'{name}'" in later, name
    # It only switches row level security on: no policy, nothing stored is touched.
    assert "POLICY" not in later.upper() and not re.search(r"\b(DROP|TRUNCATE|DELETE|UPDATE|INSERT)\b", later.upper())


def test_the_postgresql_check_is_also_one_sqlite_runs(db_session, reporter):
    # length() and trim() mean the same on both, so the rule refused above on SQLite is PostgreSQL's too.
    rule = next(check for check in Issue.__table__.constraints if check.name == "ck_issues_resolution_note")

    assert str(rule.sqltext) == "status <> 'resolved' OR (resolution_note IS NOT NULL AND length(trim(resolution_note)) > 0)"
