"""Creates the first super admin. With --force: another one, or a new password for one that exists,
or for an account that was a super admin and is an admin now (the portal never resets those).

    .venv\\Scripts\\python scripts\\create_super_admin.py
    .venv\\Scripts\\python scripts\\create_super_admin.py --force

Everything is asked for at the prompt, and the password is typed hidden, twice. There is no option
and no environment variable that takes a password: it would stay in the shell's history. Nothing
is created by default and no password exists anywhere in this repository.
"""
import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASSWORD_TRIES = 3


def database_label(url) -> str:
    # Where the account will be written, with nothing secret in it: no user name and no password.
    if url.get_backend_name() == "sqlite":
        return f"the local SQLite file {url.database}"
    return f"the {url.get_backend_name()} database \"{url.database}\" on {url.host}"


def run(db, force: bool, ask, ask_hidden, say, database: str = "the configured database") -> int:
    """Does the work. ask and ask_hidden put a question and return what was typed; say prints a line. Returns the exit code."""
    from app.models.admin_account import AdminAccount
    from app.services import audit_service, auth_service
    from app.services.auth_service import AuthError

    super_admins = db.query(AdminAccount).filter(AdminAccount.role == "super_admin").count()
    if super_admins and not force:
        say(f"A super admin already exists ({super_admins} in all). Nothing was changed.")
        say("To add another one, or to give one a new password, run this again with --force.")
        return 1
    say(f"This writes to {database}.")
    try:
        email = auth_service.clean_account_email(ask("Email: "))
    except AuthError as problem:
        say(f"{problem.message} Nothing was changed.")
        return 1
    existing = db.query(AdminAccount).filter(AdminAccount.email == email).first()
    # An account that was a super admin and is an admin now: the portal never resets its password
    # (AdminAccount.has_been_super_admin), so this is its way back in. It stays an admin.
    former = bool(existing and existing.role != "super_admin" and existing.has_been_super_admin)
    if existing and existing.role != "super_admin" and not former:
        say("That email belongs to an admin account that has never been a super admin. This tool creates and resets "
            "super admins (and accounts that were one) only; an admin's password is reset in the Super Admin portal. Nothing was changed.")
        return 1
    if former:
        say(f"{email} was a super admin and is an admin now. Going on replaces its password, unlocks and enables it, "
            "and logs it out on every device. It stays an admin.")
        if ask("Type the email again to confirm: ").strip().lower() != email:
            say("That is not the same email. Nothing was changed.")
            return 1
        full_name = existing.full_name
    elif existing:
        say(f"{email} is already a super admin. Going on replaces its password, unlocks and enables it, and logs it out on every device.")
        if ask("Type the email again to confirm: ").strip().lower() != email:
            say("That is not the same email. Nothing was changed.")
            return 1
        full_name = existing.full_name
    else:
        full_name = ask("Full name: ")

    for _ in range(PASSWORD_TRIES):
        password = ask_hidden("Password (at least 10 characters; what you type is not shown): ")
        try:
            auth_service.check_new_password(password, email)
        except AuthError as problem:
            say(problem.message)
            continue
        if ask_hidden("The same password again: ") != password:
            say("The two passwords are not the same.")
            continue
        break
    else:
        say("No password was accepted. Nothing was changed.")
        return 1

    try:
        # The audit log names nobody for these: the tool is run on the server, not by a logged-in account.
        if existing:
            auth_service.reset_password(db, existing, password)
            audit_service.record(db, "admin.password_reset", target_type="admin_account", target_id=existing.id, details={"via": "command line"})
        else:
            account = auth_service.create_account(db, email, full_name, password, role="super_admin")
            audit_service.record(db, "admin.created", target_type="admin_account", target_id=account.id,
                                 details={"via": "command line", "email": email, "role": "super_admin"})
        db.commit()
    except AuthError as problem:
        db.rollback()
        say(f"{problem.message} Nothing was changed.")
        return 1
    if former:
        say(f"The password of {email} (a former super admin, an admin now) was replaced.")
    else:
        say(f"The password of super admin {email} was replaced." if existing else f"Super admin created: {email}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create the first super admin of Vernex Smart Attendance. The email, name and password are asked for; none of them can be given on the command line.")
    parser.add_argument("--force", action="store_true", help="go on although a super admin exists: add another one, or (for an email that is or was a super admin, after typing it again) replace its password")
    args = parser.parse_args(argv)
    if not sys.stdin.isatty():
        print("Run this in a terminal window. The password has to be typed at the prompt; it is not read from a file or a pipe.")
        return 2

    from app.database import SessionLocal, engine
    from app.schema import init_database_schema

    # The tables may not exist yet if the backend has not been started since this version was installed.
    init_database_schema()
    with SessionLocal() as db:
        return run(db, args.force, input, getpass.getpass, print, database_label(engine.url))


if __name__ == "__main__":
    sys.exit(main())
