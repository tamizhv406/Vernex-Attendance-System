"""Passwords of the login accounts: how they are stored and which ones are accepted.

A password is kept only as an Argon2id hash. Nothing in this file writes a password, or a hash, to
a log or into an error message.
"""
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 10
# Long enough for any passphrase, short enough that hashing what someone sends is never a burden.
MAX_LENGTH = 128
COMMON_PASSWORDS_FILE = Path(__file__).resolve().parents[1] / "data" / "common_passwords.txt"

# The library's own settings (64 MiB of memory, 3 passes, 4 lanes), which are the second profile
# RFC 9106 recommends. They are written into every hash, so they can be raised later: an older
# hash still verifies and is replaced the next time its owner logs in (needs_rehash).
_hasher = PasswordHasher(type=Type.ID)


class PasswordPolicyError(ValueError):
    """A password that may not be used, with the reason in words for the person choosing it."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """True only if the password is the one the hash was made from. Anything else, a damaged hash included, is False."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


@lru_cache(maxsize=1)
def common_passwords() -> frozenset:
    lines = COMMON_PASSWORDS_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip().lower() for line in lines if line.strip() and not line.startswith("#"))


def check_password(password: str, email: str | None = None) -> None:
    """Raises PasswordPolicyError unless the password may be used by the account with this email."""
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"Password must have at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(f"Password must have at most {MAX_LENGTH} characters")
    if email and password.strip().lower() == email.strip().lower():
        raise PasswordPolicyError("Password must not be the same as the email address")
    if password.lower() in common_passwords():
        raise PasswordPolicyError("This password is one of the most commonly used. Choose another one")
