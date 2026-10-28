"""Attendance codes: the random code each person's QR card holds.

A code is 8 characters of the Crockford Base32 alphabet (no I, L, O or U), drawn with the secrets
module: 40 bits, so a working code cannot be guessed the way the sequential person IDs could. It is
stored uppercase without separators (K7M29QXD), shown as K7M2-9QXD, and a QR holds it as
VNXATT:K7M29QXD so the scanner can tell our QR codes from any other.

A code is never printed, logged or written into an audit entry. The frontend (src/lib/qr.js)
normalizes typed and scanned text with exactly the same rules as normalize_code here.
"""
import re
import secrets

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.person import Person
from app.services import audit_service

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 8
QR_PREFIX = "VNXATT:"
# Letters people type for the digits they look like. U is not in the alphabet and has no stand-in.
LOOKALIKES = str.maketrans({"O": "0", "I": "1", "L": "1"})
SEPARATORS = re.compile(r"[\s-]+")
CODE = re.compile(f"[{ALPHABET}]{{{CODE_LENGTH}}}")
# A new code is drawn again when it is taken. With 2^40 codes a second draw is already rare; running
# out of tries means something else is wrong, and that is said instead of looping.
MAX_ATTEMPTS = 5


class CodeUnavailable(RuntimeError):
    """No free attendance code was found in MAX_ATTEMPTS draws."""


def generate_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(text) -> str | None:
    # What a person typed or a scanner read, as a stored code, or None when it is not a code at all.
    # Trim, uppercase, drop the QR prefix, drop spaces and hyphens, read O as 0 and I or L as 1.
    if not isinstance(text, str):
        return None
    value = text.strip().upper()
    if value.startswith(QR_PREFIX):
        value = value[len(QR_PREFIX):]
    value = SEPARATORS.sub("", value).translate(LOOKALIKES)
    return value if CODE.fullmatch(value) else None


def format_code(code) -> str:
    # As people read it: K7M2-9QXD.
    return f"{code[:4]}-{code[4:]}" if code else ""


def qr_payload(code) -> str:
    return f"{QR_PREFIX}{code}"


def code_in_use(db: Session, code: str) -> bool:
    return db.query(Person.id).filter(Person.attendance_code == code).first() is not None


def _free_code(db: Session, taken: set | None, check_db: bool) -> str:
    # A code that neither the database nor this batch (taken) has given out yet. The database's unique
    # index stays the real guard: two requests can draw the same code at the same moment, and the
    # callers retry when the index refuses one of them.
    for _ in range(MAX_ATTEMPTS):
        code = generate_code()
        if taken is not None and code in taken:
            continue
        if check_db and code_in_use(db, code):
            continue
        if taken is not None:
            taken.add(code)
        return code
    raise CodeUnavailable("No free attendance code was found. Try again.")


def assign_code(db: Session, person: Person, taken: set | None = None, check_db: bool = True) -> str:
    """Gives a person without a code a new one. Writes nothing; the caller commits.

    taken: codes already given out in this batch (an import), kept so two rows of one upload never
    get the same code. check_db=False when taken already holds every code in the database.
    """
    if not person.attendance_code:
        person.attendance_code = _free_code(db, taken, check_db)
    return person.attendance_code


def add_with_code(db: Session, person: Person, conflict=None) -> Person:
    """Adds a new person with a new code and commits, drawing another code if the index refuses it.

    conflict(db) is asked after a refusal: when it raises (an ID that is taken, say), that answer
    stands; when it returns, the refusal was the code, and a new one is drawn.
    """
    for attempt in range(MAX_ATTEMPTS):
        person.attendance_code = None
        assign_code(db, person)
        db.add(person)
        try:
            db.commit()
            return person
        except IntegrityError:
            db.rollback()
            if conflict:
                conflict(db)
            if attempt == MAX_ATTEMPTS - 1:
                raise
    raise CodeUnavailable("No free attendance code was found. Try again.")


def regenerate_code(db: Session, person: Person) -> str:
    """A new code replaces the old one (or the first one is made) and the audit log says so. Commits.

    The old code stops working at once: it is no longer anyone's. The audit entry names the person,
    never either code.
    """
    person_id = person.id
    for attempt in range(MAX_ATTEMPTS):
        old = person.attendance_code
        code = _free_code(db, {old} if old else set(), check_db=True)
        person.attendance_code = code
        audit_service.record(db, "person.attendance_code_regenerated", target_type="person", target_id=person_id,
                             details={"person_code": person.person_code, "full_name": person.full_name})
        try:
            db.commit()
            return code
        except IntegrityError:
            db.rollback()
            person = db.get(Person, person_id)
            if attempt == MAX_ATTEMPTS - 1:
                raise
    raise CodeUnavailable("No free attendance code was found. Try again.")


def fill_missing_codes(db: Session) -> int:
    """Gives every person without a code one. Returns how many were given. Commits.

    Codes already given are never changed, so running it again changes nothing. Used by the schema
    upgrade (SQLite, or DATABASE_AUTO_UPGRADE) and by scripts/backfill_attendance_codes.py.
    """
    filled = 0
    for _ in range(MAX_ATTEMPTS):
        missing = db.query(Person).filter(Person.attendance_code.is_(None)).order_by(Person.id).all()
        if not missing:
            break
        # Every code in the database, read once, instead of one query per person.
        taken = {code for (code,) in db.query(Person.attendance_code).filter(Person.attendance_code.is_not(None))}
        try:
            with db.begin_nested():
                for person in missing:
                    assign_code(db, person, taken, check_db=False)
                db.flush()
        except IntegrityError:
            # Someone else gave out one of these codes meanwhile (another backfill, a new person).
            # The savepoint took this round back; the rows still without a code are read again.
            continue
        filled += len(missing)
        break
    else:
        raise CodeUnavailable("Attendance codes could not be given out. Run it again.")
    db.commit()
    return filled
