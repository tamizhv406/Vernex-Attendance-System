import logging

import pytest
from argon2 import PasswordHasher

from app.services import password_service
from app.services.password_service import (
    COMMON_PASSWORDS_FILE, MAX_LENGTH, MIN_LENGTH, PasswordPolicyError, check_password, common_passwords, hash_password,
    needs_rehash, verify_password,
)

GOOD = "correct horse battery staple"


# ---- hashing ------------------------------------------------------------------------------------

def test_a_password_is_stored_as_an_argon2id_hash_with_the_recommended_cost(production_hashing):
    stored = hash_password(GOOD)

    # 64 MiB of memory, 3 passes, 4 lanes: the second profile of RFC 9106.
    assert stored.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert GOOD not in stored and "horse" not in stored
    assert verify_password(stored, GOOD) is True


def test_the_same_password_gives_a_different_hash_every_time():
    first, second = hash_password(GOOD), hash_password(GOOD)

    assert first != second
    assert verify_password(first, GOOD) and verify_password(second, GOOD)


@pytest.mark.parametrize("attempt", ["correct horse battery stapl", "Correct horse battery staple", GOOD + " ", " " + GOOD, "", "x", GOOD * 2])
def test_any_other_password_is_rejected(attempt):
    assert verify_password(hash_password(GOOD), attempt) is False


@pytest.mark.parametrize("damaged", ["", "not-a-hash", "$argon2id$", "$argon2id$v=19$m=65536,t=3,p=4$AAAA$BBBB", "$2b$12$abcdefghijklmnopqrstuv", GOOD])
def test_a_damaged_or_foreign_hash_matches_nothing_and_raises_nothing(damaged):
    assert verify_password(damaged, GOOD) is False
    assert verify_password(damaged, damaged) is False


def test_a_password_in_another_script_is_hashed_and_verified_like_any_other():
    password = "கடவுச்சொல் பத்து"

    assert verify_password(hash_password(password), password) is True
    assert verify_password(hash_password(password), "கடவுச்சொல் பத்த") is False


def test_a_hash_made_with_weaker_settings_still_verifies_and_is_marked_for_replacement(production_hashing):
    older = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1).hash(GOOD)

    assert verify_password(older, GOOD) is True
    assert needs_rehash(older) is True
    assert needs_rehash(hash_password(GOOD)) is False
    assert needs_rehash("not-a-hash") is True


def test_hashing_and_checking_write_nothing_to_the_log(caplog):
    with caplog.at_level(logging.DEBUG):
        stored = hash_password(GOOD)
        verify_password(stored, GOOD)
        verify_password(stored, "wrong password")
        with pytest.raises(PasswordPolicyError):
            check_password("short")

    assert caplog.records == []


# ---- policy -------------------------------------------------------------------------------------

def refusal(password, email=None):
    with pytest.raises(PasswordPolicyError) as error:
        check_password(password, email)
    # Whatever is wrong with a password, the message never repeats it.
    assert password not in str(error.value) or len(password) < 3
    return str(error.value)


def test_the_minimum_is_ten_characters():
    assert MIN_LENGTH == 10
    assert refusal("nine char") == "Password must have at least 10 characters"
    assert refusal("") == "Password must have at least 10 characters"
    check_password("ten chars!")


def test_a_very_long_password_is_refused_instead_of_hashed():
    check_password("p" * (MAX_LENGTH - 1) + "!")
    assert refusal("p" * MAX_LENGTH + "!") == f"Password must have at most {MAX_LENGTH} characters"


@pytest.mark.parametrize("password", ["asha.kumar@example.com", "ASHA.KUMAR@EXAMPLE.COM", "  asha.kumar@example.com ", "Asha.Kumar@Example.com"])
def test_the_email_address_cannot_be_the_password(password):
    assert refusal(password, "asha.kumar@example.com") == "Password must not be the same as the email address"


def test_another_accounts_email_is_just_a_password():
    check_password("asha.kumar@example.com", "someone.else@example.com")
    check_password("asha.kumar@example.com")


def test_the_list_of_common_passwords_is_the_published_one():
    listed = common_passwords()
    lines = COMMON_PASSWORDS_FILE.read_text(encoding="utf-8").splitlines()
    part_two = lines.index("# Part 2")
    first = [line for line in lines[:part_two] if line and not line.startswith("#")]
    second = [line for line in lines[part_two:] if line and not line.startswith("#")]

    # The 100 most common, of which the published list's 43rd is the empty password.
    assert len(first) == 99 and first[:5] == ["123456", "password", "12345678", "qwerty", "123456789"]
    assert len(second) == 100 and all(len(entry) >= MIN_LENGTH for entry in second)
    assert len(listed) == 199
    assert all(entry == entry.lower().strip() and entry.isascii() for entry in listed)


def test_every_common_password_that_is_long_enough_is_refused_in_any_capitals():
    long_enough = [entry for entry in common_passwords() if len(entry) >= MIN_LENGTH]

    # Of the 100 most common only these two reach ten characters; the rest fail on length.
    assert {"qwertyuiop", "1234567890"} <= set(long_enough)
    assert len(long_enough) == 102
    for entry in long_enough:
        for written in (entry, entry.upper(), entry.capitalize()):
            assert refusal(written) == "This password is one of the most commonly used. Choose another one"


@pytest.mark.parametrize("password", ["123456", "password", "qwerty", "iloveyou"])
def test_a_short_common_password_is_refused_for_its_length(password):
    assert password in common_passwords()
    assert refusal(password) == "Password must have at least 10 characters"


@pytest.mark.parametrize("password", [GOOD, "Tr4vel-light-2026", "qwertyuiop-and-more", "ten chars!", "p@ss wörd with spaces"])
def test_an_uncommon_password_of_ten_or_more_characters_is_accepted(password):
    check_password(password, "asha.kumar@example.com")
