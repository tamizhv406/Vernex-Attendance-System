import json
from pathlib import Path

import pytest

from app.models.person import Person
from app.utils.validation import normalize_phone

# The frontend's checkPhone is tested with this same file (frontend/src/lib/phone.test.js).
CASES = json.loads((Path(__file__).parent / "data" / "phone_cases.json").read_text(encoding="utf-8"))


def case_id(case):
    return ascii(case["input"])


@pytest.mark.parametrize("case", CASES["accepted"], ids=case_id)
def test_an_accepted_number_becomes_its_ten_digits(case):
    assert normalize_phone(case["input"]) == case["value"]


@pytest.mark.parametrize("case", CASES["rejected"], ids=case_id)
def test_a_refused_number_says_what_is_wrong_with_it(case):
    with pytest.raises(ValueError) as error:
        normalize_phone(case["input"])
    assert str(error.value) == case["error"]


def test_a_three_digit_number_is_rejected():
    with pytest.raises(ValueError, match="exactly 10 digits .found 3."):
        normalize_phone("123")


def test_a_nine_digit_number_is_rejected():
    with pytest.raises(ValueError, match="exactly 10 digits .found 9."):
        normalize_phone("987654321")


def test_an_eleven_digit_number_is_rejected_not_shortened():
    with pytest.raises(ValueError, match="exactly 10 digits .found 11."):
        normalize_phone("98765432101")


def test_a_ten_digit_number_is_accepted_as_it_is():
    assert normalize_phone("9876543210") == "9876543210"


@pytest.mark.parametrize("written", ["98765 43210", "98765-43210", "987-654-3210", " 9876543210 "])
def test_spaces_and_hyphens_between_the_digits_are_taken_out(written):
    assert normalize_phone(written) == "9876543210"


@pytest.mark.parametrize("written", ["+91 98765 43210", "+919876543210", "+91-98765-43210"])
def test_the_india_country_code_is_taken_off(written):
    assert normalize_phone(written) == "9876543210"


@pytest.mark.parametrize("written", ["+1 98765 43210", "+91 98765 4321", "+ 91 98765 43210", "++919876543210", "91+9876543210", "919876543210", "0091 98765 43210"])
def test_a_country_code_written_any_other_way_is_rejected(written):
    with pytest.raises(ValueError):
        normalize_phone(written)


@pytest.mark.parametrize("written", ["abcdefghij", "98765abc10", "call me", "9876543210 (home)", "98765#43210"])
def test_letters_and_other_symbols_are_rejected_not_removed(written):
    with pytest.raises(ValueError, match="can only contain digits, spaces and hyphens"):
        normalize_phone(written)


def test_nothing_is_not_a_number():
    for nothing in (None, "", "   "):
        with pytest.raises(ValueError, match="Enter a phone number"):
            normalize_phone(nothing)


# ---- through the API ----------------------------------------------------------------------------

def staff(**fields):
    return {"person_code": "STF-1", "full_name": "Sample Staff", "person_type": "admin", **fields}


def stored_phones(client):
    with client.db() as db:
        return [(person.person_code, person.phone, person.guardian_phone) for person in db.query(Person).order_by(Person.id)]


@pytest.mark.parametrize("path", ["/users/create", "/people/create"])
def test_creating_a_person_with_a_three_digit_number_is_refused_and_nothing_is_saved(client, path):
    response = client.post(path, json=staff(phone="123"))

    assert response.status_code == 400
    assert response.json() == {"detail": "Contact number: Phone number must have exactly 10 digits (found 3)"}
    assert stored_phones(client) == []


def test_creating_a_person_stores_the_ten_digits_however_the_number_was_written(client):
    response = client.post("/users/create", json=staff(phone="+91 98765 43210"))

    assert response.status_code == 200
    assert response.json()["data"]["phone"] == "9876543210"
    assert stored_phones(client) == [("STF-1", "9876543210", None)]


def test_a_parent_contact_is_checked_like_any_other_number(client):
    course = client.post("/courses/create", json={"course_code": "CS101", "course_name": "Computer Science"}).json()["data"]
    batch = client.post("/batches/create", json={"course_id": course["id"], "batch_name": "Morning A"}).json()["data"]
    student = {"person_code": "STU-1", "full_name": "Sample Student", "person_type": "student", "course_id": course["id"], "batch_id": batch["id"]}

    refused = client.post("/users/create", json={**student, "guardian_phone": "98765 4321"})
    accepted = client.post("/users/create", json={**student, "guardian_phone": "98765-43210"})

    assert refused.status_code == 400
    assert refused.json()["detail"] == "Parent contact: Phone number must have exactly 10 digits (found 9)"
    assert accepted.status_code == 200
    assert stored_phones(client) == [("STU-1", None, "9876543210")]


def test_changing_a_number_to_a_wrong_one_is_refused_and_the_old_number_stays(client):
    person_id = client.post("/users/create", json=staff(phone="9876543210")).json()["data"]["id"]

    refused = client.put(f"/users/{person_id}", json={"phone": "98765x3210"})
    changed = client.put(f"/users/{person_id}", json={"phone": "+91 91234 56789"})

    assert refused.status_code == 400
    assert "can only contain digits" in refused.json()["detail"]
    assert changed.status_code == 200
    assert stored_phones(client) == [("STF-1", "9123456789", None)]


def test_an_update_that_does_not_mention_the_number_leaves_it_alone(client):
    # A number saved before this check existed must not stop the person's other details being edited.
    with client.db() as db:
        db.add(Person(person_code="OLD-1", full_name="Saved Earlier", person_type="member", phone="123"))
        db.commit()
        person_id = db.query(Person).one().id

    response = client.put(f"/users/{person_id}", json={"notes": "called on Monday"})

    assert response.status_code == 200
    assert stored_phones(client) == [("OLD-1", "123", None)]


def test_a_person_without_any_number_is_still_accepted_by_the_api(client):
    # The forms and the uploads require a contact number. The API itself never did, and still
    # does not: what it refuses is a number that is wrong.
    response = client.post("/users/create", json=staff(phone=None))
    blank = client.post("/users/create", json=staff(person_code="STF-2", phone="   "))

    assert response.status_code == 200
    assert blank.status_code == 200
    assert stored_phones(client) == [("STF-1", None, None), ("STF-2", None, None)]


@pytest.mark.parametrize("case", [case for case in CASES["rejected"] if case["input"].strip()], ids=case_id)
def test_the_api_and_an_upload_refuse_the_same_number_for_the_same_reason(client, make_csv, case):
    api = client.post("/users/create", json=staff(phone=case["input"]))
    upload = client.post("/users/upload?person_type=admin", files={"file": ("staff.csv", make_csv([
        ["staff_id", "full_name", "contact_number"],
        ["STF-9", "Sample Staff", case["input"]],
    ]))})

    assert api.status_code == 400
    assert api.json()["detail"] == f"Contact number: {case['error']}"
    assert upload.status_code == 200
    assert upload.json()["data"]["imported"] == 0
    assert [(error["column"], error["message"]) for error in upload.json()["data"]["errors"]] == [("contact_number", case["error"])]
    assert stored_phones(client) == []


@pytest.mark.parametrize("case", CASES["accepted"], ids=case_id)
def test_the_api_and_an_upload_store_the_same_ten_digits(client, make_csv, case):
    api = client.post("/users/create", json=staff(phone=case["input"]))
    upload = client.post("/users/upload?person_type=admin", files={"file": ("staff.csv", make_csv([
        ["staff_id", "full_name", "contact_number"],
        ["STF-9", "Sample Staff", case["input"]],
    ]))})

    assert api.status_code == 200
    assert upload.json()["data"]["imported"] == 1
    assert stored_phones(client) == [("STF-1", case["value"], None), ("STF-9", case["value"], None)]
