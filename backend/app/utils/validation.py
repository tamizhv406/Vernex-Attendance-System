"""Rules for values people type: contact numbers and e-mail addresses.

There is one implementation, used by the JSON API (services/person_service.py) and by spreadsheet
uploads (services/import_service.py), so a number refused in one place is refused in the other.
frontend/src/lib/phone.js follows the same rules with the same messages, and
tests/data/phone_cases.json is checked against both.
"""
import re

PHONE_DIGITS = 10
COUNTRY_CODE = "91"

# What counts as a space inside a number: space, tab, line break and the non-breaking space that
# comes along when a number is copied from a web page or a document.
_SPACES = re.compile("[ \t\r\n ]")
_NOT_ALLOWED = re.compile(r"[^0-9 -]")
# Digits, with spaces or hyphens only between them.
_GROUPED_DIGITS = re.compile(r"[0-9](?:[ -]*[0-9])*")

# The pattern browsers apply to <input type="email"> (WHATWG HTML), so the form and the API agree.
_EMAIL = re.compile(
    r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*"
)


class FieldError(ValueError):
    """A value that cannot be accepted, and the field it was given for."""

    def __init__(self, field, message, status=400):
        super().__init__(message)
        self.field = field
        self.message = message
        self.status = status


def text_limit(model, field):
    """How many characters the database column behind a model field holds, or None if it has no limit."""
    column = model.__table__.columns.get(field)
    return getattr(column.type, "length", None) if column is not None else None


def limited_text(model, field, text, label):
    # SQLite stores a longer value without complaint and PostgreSQL refuses it with a database
    # error, so the length is checked here, where it can be explained.
    limit = text_limit(model, field)
    if limit and len(text) > limit:
        raise FieldError(field, f"{label} must be at most {limit} characters")
    return text


def required_text(model, field, value, label):
    text = (value or "").strip()
    if not text:
        raise FieldError(field, f"{label} is required")
    return limited_text(model, field, text, label)


def normalize_phone(value):
    """Return the ten digits of a contact number, or raise ValueError saying what is wrong with it.

    Accepted: ten digits, optionally grouped with spaces or hyphens ("98765 43210", "98765-43210"),
    optionally preceded by the India country code written as +91 ("+91 98765 43210").
    Everything else is refused rather than repaired: letters, other symbols, other country codes,
    a "+" anywhere but the start, and any other number of digits. A number is never shortened or
    padded to make it fit.
    """
    text = "" if value is None else _SPACES.sub(" ", str(value)).strip(" ")
    if not text:
        raise ValueError("Enter a phone number")
    has_country_code = text.startswith("+")
    body = text[1:] if has_country_code else text
    if "+" in body:
        raise ValueError("A + is only allowed at the start, as +91")
    if _NOT_ALLOWED.search(body):
        raise ValueError("Phone number can only contain digits, spaces and hyphens, with an optional +91 in front")
    digits = body.replace(" ", "").replace("-", "")
    if not digits:
        raise ValueError(_length_message(0))
    if has_country_code and not body[0].isdigit():
        raise ValueError("Write the country code as +91, with nothing between + and 91")
    if not _GROUPED_DIGITS.fullmatch(body):
        raise ValueError("Spaces and hyphens are only allowed between digits")
    if has_country_code:
        if not digits.startswith(COUNTRY_CODE):
            raise ValueError("Only the +91 country code is supported")
        national = digits[len(COUNTRY_CODE):]
        if len(national) != PHONE_DIGITS:
            raise ValueError(f"Phone number must have exactly {PHONE_DIGITS} digits after +91 (found {len(national)})")
        return national
    if len(digits) != PHONE_DIGITS:
        raise ValueError(_length_message(len(digits), digits))
    return digits


def _length_message(found, digits=""):
    message = f"Phone number must have exactly {PHONE_DIGITS} digits (found {found})"
    # Twelve digits starting with 91 is almost certainly a country code without its "+". It is still
    # refused, because guessing which two digits to drop is how a wrong number gets stored.
    if found == PHONE_DIGITS + len(COUNTRY_CODE) and digits.startswith(COUNTRY_CODE):
        message += ". To include the country code, write it as +91"
    return message


def normalize_email(value):
    """Return the address without surrounding spaces, or raise ValueError if it is not an address."""
    text = str(value).strip()
    if not _EMAIL.fullmatch(text):
        raise ValueError("Enter a valid email address, like name@example.com")
    return text
