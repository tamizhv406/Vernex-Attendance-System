import base64
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.models.admin_account import AdminAccount, AdminSession
from app.models.person import Person
from app.services import auth_service
from app.services.auth_service import AuthError

PASSWORD = "correct horse battery staple"
OTHER_PASSWORD = "another fine long password"
WRONG = {"detail": "Incorrect email or password."}
LOCKED = {"detail": "Too many failed attempts. Try again in 15 minutes."}
ENDED = {"detail": "Your session has ended. Log in again."}


class Time:
    # The clock of everything to do with logging in. A test moves it forward instead of waiting.
    def __init__(self):
        self.now = datetime(2026, 1, 5, 9, 0, 0)

    def __call__(self):
        return self.now

    def advance(self, **amount):
        self.now += timedelta(**amount)


@pytest.fixture()
def time(monkeypatch):
    clock = Time()
    monkeypatch.setattr(auth_service, "clock", clock)
    return clock


@pytest.fixture()
def asha(backend, make_account, time):
    with backend.db() as db:
        return make_account(db, "asha@example.com", PASSWORD, full_name="Asha Example").id


def sign_in(client, email="asha@example.com", password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def bearer(response):
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def stored(backend, email="asha@example.com"):
    with backend.db() as db:
        account = db.query(AdminAccount).filter_by(email=email).one()
        db.expunge(account)
        return account


def logins(backend):
    with backend.db() as db:
        return [(row.account_id, row.revoked_at is not None) for row in db.query(AdminSession).order_by(AdminSession.id)]


# ---- success ------------------------------------------------------------------------------------

def test_the_right_password_logs_in_and_returns_a_short_lived_token(backend, anon_client, asha, time):
    response = sign_in(anon_client)

    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["token_type"], data["expires_in"]) == ("bearer", 15 * 60)
    assert data["account"] == {
        "id": asha, "email": "asha@example.com", "full_name": "Asha Example", "role": "admin", "status": "active",
        "must_change_password": False, "last_login_at": "2026-01-05T09:00:00Z","created_at": data["account"]["created_at"],
        "updated_at": data["account"]["updated_at"],
    }
    assert response.headers["cache-control"] == "no-store"
    assert anon_client.get("/courses", headers=bearer(response)).status_code == 200
    assert anon_client.get("/auth/me", headers=bearer(response)).json()["data"]["email"] == "asha@example.com"
    assert (stored(backend).failed_login_count, stored(backend).last_login_at) == (0, datetime(2026, 1, 5, 9, 0, 0))


def test_the_refresh_token_is_a_cookie_scripts_cannot_read_and_only_https_carries(anon_client, asha):
    cookie = sign_in(anon_client).headers["set-cookie"]
    attributes = {part.strip().lower() for part in cookie.split(";")[1:]}

    assert cookie.startswith("vx_refresh=")
    assert {"httponly", "secure", "samesite=strict", "max-age=604800"} <= attributes
    # The test settings put the backend's own path here; through the frontend it is /api/auth.
    assert "path=/auth" in attributes and settings.auth_cookie_path == "/auth"
    assert not any(part.startswith("domain=") for part in attributes)


def test_the_cookie_path_is_the_one_the_browser_uses_unless_set_otherwise():
    # Read from the class, which holds what the settings are when backend/.env does not say.
    import inspect

    from app import config

    assert 'os.getenv("AUTH_COOKIE_PATH", "/api/auth")' in inspect.getsource(config.Settings)


def test_only_a_hash_of_the_refresh_token_is_stored(backend, anon_client, asha):
    sign_in(anon_client)
    token = anon_client.cookies["vx_refresh"]

    with backend.db() as db:
        session = db.query(AdminSession).one()
        assert session.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in [str(value) for value in vars(session).values()]
        assert (session.account_id, session.revoked_at, session.expires_at) == (asha, None, datetime(2026, 1, 12, 9, 0, 0))


def test_the_access_token_says_who_and_which_login_and_nothing_else(anon_client, asha):
    token = sign_in(anon_client).json()["data"]["access_token"]
    header, claims = (json.loads(base64.urlsafe_b64decode(part + "==")) for part in token.split(".")[:2])

    assert header == {"alg": "HS256", "typ": "JWT"}
    assert set(claims) == {"sub", "sid", "role", "iat", "exp"}
    assert (claims["sub"], claims["role"], claims["exp"] - claims["iat"]) == (str(asha), "admin", 900)


@pytest.mark.parametrize("typed", ["Asha@Example.com", "ASHA@EXAMPLE.COM", "  asha@example.com  "])
def test_the_email_is_matched_however_it_is_typed(anon_client, asha, typed):
    assert sign_in(anon_client, email=typed).status_code == 200


# ---- wrong password, unknown email --------------------------------------------------------------

def test_a_wrong_password_and_an_unknown_email_get_the_same_answer(backend, anon_client, asha):
    wrong_password = sign_in(anon_client, password="not the password!")
    unknown_email = sign_in(anon_client, email="nobody@example.com")

    for response in (wrong_password, unknown_email):
        assert (response.status_code, response.json()) == (401, WRONG)
        assert "set-cookie" not in response.headers
    assert dict(wrong_password.headers) == dict(unknown_email.headers)
    assert stored(backend).failed_login_count == 1
    assert logins(backend) == []


@pytest.mark.parametrize("email, password", [("", PASSWORD), ("asha@example.com", ""), ("", ""), ("not an email", PASSWORD), ("asha@example.com", "p" * 5000), ("a" * 5000 + "@example.com", PASSWORD)])
def test_anything_that_cannot_be_right_is_answered_like_a_wrong_password(anon_client, asha, email, password):
    response = sign_in(anon_client, email=email, password=password)

    assert (response.status_code, response.json()) == (401, WRONG)


def test_a_staff_member_is_not_a_login_account(backend, anon_client, time):
    # In user_management, person_type "admin" means staff. Such a row opens nothing.
    with backend.db() as db:
        db.add(Person(person_code="STF-1", full_name="Sample Staff", person_type="admin", email="staff@example.com", phone="9876543210"))
        db.commit()

    for password in ("9876543210", "STF-1", "Sample Staff", PASSWORD):
        assert sign_in(anon_client, email="staff@example.com", password=password).status_code in (401, 429)
    assert logins(backend) == []


@pytest.mark.parametrize("path, body", [
    ("/auth/login", {"password": PASSWORD}),
    ("/auth/login", {"email": 5, "password": PASSWORD}),
    ("/auth/login", {"email": "asha@example.com", "password": [PASSWORD]}),
    ("/auth/login", [PASSWORD]),
    ("/auth/login", PASSWORD),
    ("/auth/change-password", {"current_password": PASSWORD}),
    ("/auth/change-password", {"new_password": PASSWORD}),
])
def test_a_malformed_request_is_refused_without_repeating_the_password_it_held(backend, anon_client, asha, log_in, path, body):
    # FastAPI's usual answer to a malformed body quotes the body. Not on these routes.
    with backend.db() as db:
        token, _refresh = log_in(db, db.get(AdminAccount, asha))

    response = anon_client.post(path, json=body, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 422
    assert PASSWORD not in response.text and "input" not in response.text
    assert all(set(problem) == {"type", "loc", "msg"} for problem in response.json()["detail"])


def test_a_malformed_request_elsewhere_is_still_explained_in_full(client):
    # Only the auth routes are special: other routes keep FastAPI's own answer, as before.
    response = client.post("/courses/create", json={"course_code": 5})

    assert response.status_code == 422
    assert {problem["loc"][-1] for problem in response.json()["detail"]} == {"course_code", "course_name"}
    assert "input" in response.json()["detail"][0]


# ---- lockout ------------------------------------------------------------------------------------

def test_five_wrong_passwords_lock_the_account_for_fifteen_minutes(backend, anon_client, asha, time):
    answers = [sign_in(anon_client, password=f"wrong password {number}") for number in range(5)]

    assert [(answer.status_code, answer.json()) for answer in answers[:4]] == [(401, WRONG)] * 4
    assert (answers[4].status_code, answers[4].json(), answers[4].headers["retry-after"]) == (429, LOCKED, "900")
    assert stored(backend).locked_until == datetime(2026, 1, 5, 9, 15, 0)
    # Locked means locked: the right password does not open it either.
    locked = sign_in(anon_client)
    assert (locked.status_code, locked.json()) == (429, LOCKED)
    assert logins(backend) == []


def test_the_lock_message_counts_down_and_the_lock_ends_by_itself(backend, anon_client, asha, time):
    for number in range(5):
        sign_in(anon_client, password=f"wrong password {number}")

    time.advance(minutes=10)
    assert sign_in(anon_client).json() == {"detail": "Too many failed attempts. Try again in 5 minutes."}
    time.advance(minutes=4, seconds=30)
    still = sign_in(anon_client)
    assert (still.json(), still.headers["retry-after"]) == ({"detail": "Too many failed attempts. Try again in 1 minute."}, "30")
    time.advance(seconds=30)

    assert sign_in(anon_client).status_code == 200
    assert (stored(backend).failed_login_count, stored(backend).locked_until) == (0, None)


def test_attempts_made_while_locked_do_not_make_the_lock_longer(backend, anon_client, asha, time):
    for number in range(5):
        sign_in(anon_client, password=f"wrong password {number}")
    time.advance(minutes=14)
    for _ in range(3):
        sign_in(anon_client, password="still guessing!")

    assert stored(backend).locked_until == datetime(2026, 1, 5, 9, 15, 0)


def test_after_a_lock_ends_there_are_five_fresh_attempts(backend, anon_client, asha, time):
    for number in range(5):
        sign_in(anon_client, password=f"wrong password {number}")
    time.advance(minutes=16)

    assert [sign_in(anon_client, password=f"second round {number}").status_code for number in range(5)] == [401, 401, 401, 401, 429]


def test_a_successful_login_clears_the_count_of_wrong_passwords(backend, anon_client, asha, time):
    for number in range(4):
        sign_in(anon_client, password=f"wrong password {number}")
    assert stored(backend).failed_login_count == 4
    assert sign_in(anon_client).status_code == 200
    assert stored(backend).failed_login_count == 0
    time.advance(minutes=2)

    assert [sign_in(anon_client, password=f"wrong again {number}").status_code for number in range(4)] == [401] * 4


def test_an_email_without_an_account_is_locked_in_exactly_the_same_way(anon_client, asha, time):
    def six_attempts(email):
        answers = [sign_in(anon_client, email=email, password=f"wrong password {number}") for number in range(6)]
        return [(answer.status_code, answer.json(), answer.headers.get("retry-after")) for answer in answers]

    known = six_attempts("asha@example.com")
    time.advance(minutes=2)  # a new minute for the per-address limit; neither lock has ended
    unknown = six_attempts("nobody@example.com")

    # Nothing in the answers tells someone who is guessing which of the two addresses has an account.
    assert known == unknown == [(401, WRONG, None)] * 4 + [(429, LOCKED, "900")] * 2


def test_locking_one_email_does_not_lock_another(backend, anon_client, asha, make_account, time):
    with backend.db() as db:
        make_account(db, "ravi@example.com", PASSWORD)
    for number in range(5):
        sign_in(anon_client, password=f"wrong password {number}")

    assert sign_in(anon_client).status_code == 429
    assert sign_in(anon_client, email="ravi@example.com").status_code == 200


def test_attempts_at_the_same_moment_cannot_all_slip_in_under_the_limit(backend, asha, time):
    # The attempt is counted in the database before the password is looked at. Five have been
    # counted here, as if five requests were all checking their password at this instant; a sixth
    # that arrives now finds no attempt left, although no lock has been written yet.
    with backend.db() as db:
        assert [auth_service._count_attempt(db, "asha@example.com") for _ in range(6)] == [True] * 5 + [False]
    assert (stored(backend).failed_login_count, stored(backend).locked_until) == (5, None)

    # Even the right password: with no attempt left it is not looked at.
    with backend.db() as db, pytest.raises(AuthError) as refused:
        auth_service.login(db, "asha@example.com", PASSWORD)

    assert refused.value.status == 429
    assert stored(backend).locked_until == datetime(2026, 1, 5, 9, 15, 0)
    assert logins(backend) == []


# ---- rate limit per address ---------------------------------------------------------------------

def test_one_address_gets_ten_login_attempts_a_minute(backend, asha, time):
    here = backend(client=("192.168.0.50", 50000))
    for number in range(10):
        assert sign_in(here, email=f"nobody{number}@example.com").status_code == 401

    blocked = sign_in(here)  # the right email and password, and still no
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many login attempts from this device. Wait a minute and try again."}
    assert blocked.headers["retry-after"] == "60"
    # Another device is not held up by it, and after a minute neither is this one.
    assert sign_in(backend(client=("192.168.0.51", 50000))).status_code == 200
    time.advance(seconds=61)
    assert sign_in(here).status_code == 200


def test_behind_the_frontend_proxy_each_browser_is_counted_by_its_own_address(backend, asha, time):
    # The frontend's proxy passes the browser's address on, and uvicorn takes it from the local
    # machine only. This wraps the application the way uvicorn does when it runs it.
    from fastapi.testclient import TestClient
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    from app.main import app

    served = ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1")

    def attempt(connected_from, says_it_is_for, email="asha@example.com"):
        browser = TestClient(served, base_url="https://testserver", client=(connected_from, 50000))
        return browser.post("/auth/login", json={"email": email, "password": PASSWORD}, headers={"X-Forwarded-For": says_it_is_for}).status_code

    for number in range(10):
        attempt("127.0.0.1", "192.168.0.60", email=f"nobody{number}@example.com")

    # One browser has used its ten attempts; another one behind the same proxy has not.
    assert attempt("127.0.0.1", "192.168.0.60") == 429
    assert attempt("127.0.0.1", "192.168.0.61") == 200
    # A device that talks to the backend directly is counted by the address it really has,
    # whatever it claims: it cannot pass itself off as someone else, nor shed its own count.
    assert attempt("192.168.0.60", "10.9.9.9") == 429


# ---- disabled accounts --------------------------------------------------------------------------

def test_a_disabled_account_cannot_log_in(backend, anon_client, make_account, time):
    with backend.db() as db:
        make_account(db, "gone@example.com", PASSWORD, status="disabled")

    right = sign_in(anon_client, email="gone@example.com")
    wrong = sign_in(anon_client, email="gone@example.com", password="not the password!")

    # Only someone who knows the password is told why. A guesser sees an ordinary wrong password.
    assert (right.status_code, right.json()) == (403, {"detail": "This account is disabled. Ask a super admin to enable it."})
    assert (wrong.status_code, wrong.json()) == (401, WRONG)
    assert "set-cookie" not in right.headers and logins(backend) == []


def test_disabling_an_account_ends_the_logins_it_already_has(backend, anon_client, asha, time):
    token = bearer(sign_in(anon_client))
    assert anon_client.get("/courses", headers=token).status_code == 200

    with backend.db() as db:
        db.get(AdminAccount, asha).status = "disabled"
        auth_service.end_logins(db, asha)
        db.commit()

    # At once, with nothing waited for: not a single further request is answered.
    assert (anon_client.get("/courses", headers=token).status_code, anon_client.get("/courses", headers=token).json()) == (401, ENDED)
    assert anon_client.post("/auth/refresh").status_code == 401
    assert sign_in(anon_client).status_code == 403


def test_a_change_made_by_another_program_is_noticed_within_seconds(backend, anon_client, asha, time):
    # The command-line tool is another process: it cannot tell this one to forget what it knows.
    token = bearer(sign_in(anon_client))
    assert anon_client.get("/courses", headers=token).status_code == 200
    with backend.db() as db:
        db.get(AdminAccount, asha).status = "disabled"
        db.commit()

    # A new access token is refused straight away; the one in use, after the short time it is trusted for.
    assert anon_client.post("/auth/refresh").status_code == 401
    time.advance(seconds=auth_service.ACTOR_CACHE_SECONDS + 1)
    assert anon_client.get("/courses", headers=token).status_code == 401


@pytest.fixture()
def two_connections(tmp_path, make_account, log_in, time):
    # A database file with real, separate connections: what one session has not committed yet, the
    # other does not see, as with two requests answered at the same moment.
    engine = create_engine(f"sqlite:///{tmp_path / 'logins.db'}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with sessions() as db:
        account = make_account(db, "asha@example.com", PASSWORD)
        token, _refresh = log_in(db, account)
        sessions.account_id, sessions.token = account.id, token
    yield sessions
    engine.dispose()


def still_open(sessions):
    with sessions() as db:
        try:
            return auth_service.actor_for(db, sessions.token).email
        except AuthError as error:
            return error.status


@pytest.mark.parametrize("how", ["end_logins", "change_password", "reset_password"])
def test_a_request_answered_while_logins_are_being_ended_does_not_keep_them_open(two_connections, how):
    writer = two_connections()
    if how == "end_logins":
        auth_service.end_logins(writer, two_connections.account_id)
    elif how == "change_password":
        actor = auth_service.actor_for(writer, two_connections.token)
        auth_service.change_password(writer, actor, PASSWORD, OTHER_PASSWORD)
    else:
        auth_service.reset_password(writer, writer.get(AdminAccount, two_connections.account_id), OTHER_PASSWORD)
    if how != "change_password":
        # A scanner frame is answered before the change is committed, from what the database says then.
        assert still_open(two_connections) == "asha@example.com"
        writer.commit()
    writer.close()

    # From the commit on, not one more request is answered for the login, without waiting.
    assert still_open(two_connections) == 401


def test_an_answer_read_before_the_commit_is_not_remembered_after_it(two_connections, monkeypatch):
    writer = two_connections()
    auth_service.end_logins(writer, two_connections.account_id)
    judged = auth_service._usable

    def commit_in_between(*args):
        # The other request has read the login (still open: nothing was committed yet) and the
        # revocation is committed before it gets to remember what it read.
        verdict = judged(*args)
        writer.commit()
        return verdict

    monkeypatch.setattr(auth_service, "_usable", commit_in_between)
    assert still_open(two_connections) == "asha@example.com"
    monkeypatch.setattr(auth_service, "_usable", judged)
    writer.close()

    assert still_open(two_connections) == 401


def test_logins_whose_end_was_rolled_back_are_still_open(two_connections):
    writer = two_connections()
    auth_service.end_logins(writer, two_connections.account_id)
    writer.rollback()
    writer.close()

    assert still_open(two_connections) == "asha@example.com"


def test_logging_out_while_another_request_is_answered_still_ends_the_login(two_connections, monkeypatch):
    refresh_token = "the refresh token of this test"
    with two_connections() as db:
        db.query(AdminSession).one().token_hash = auth_service.hash_token(refresh_token)
        db.commit()
    judged = auth_service._usable

    def log_out_in_between(*args):
        verdict = judged(*args)
        with two_connections() as other:
            auth_service.logout(other, refresh_token)
        return verdict

    monkeypatch.setattr(auth_service, "_usable", log_out_in_between)
    assert still_open(two_connections) == "asha@example.com"
    monkeypatch.setattr(auth_service, "_usable", judged)

    assert still_open(two_connections) == 401


# ---- expired and forged tokens ------------------------------------------------------------------

def test_an_access_token_stops_working_after_fifteen_minutes(anon_client, asha, time):
    token = bearer(sign_in(anon_client))

    time.advance(minutes=14, seconds=59)
    assert anon_client.get("/courses", headers=token).status_code == 200
    time.advance(seconds=1)
    expired = anon_client.get("/courses", headers=token)

    assert (expired.status_code, expired.json(), expired.headers["www-authenticate"]) == (401, ENDED, "Bearer")


def forged(claims, key, algorithm="HS256"):
    return jwt.encode(claims, key, algorithm=algorithm)


def test_a_token_that_was_not_signed_with_our_secret_is_refused(backend, anon_client, asha, time):
    good = sign_in(anon_client).json()["data"]["access_token"]
    claims = jwt.decode(good, options={"verify_signature": False})
    header, payload, signature = good.split(".")
    unsigned = f"{base64.urlsafe_b64encode(json.dumps({'alg': 'none', 'typ': 'JWT'}).encode()).decode().rstrip('=')}.{payload}."

    attempts = {
        "signed with another secret": forged(claims, "another-secret-of-thirty-two-bytes-or-more"),
        "signature cut short": f"{header}.{payload}.{signature[:-4]}",
        "claims changed after signing": f"{header}.{base64.urlsafe_b64encode(json.dumps({**claims, 'role': 'super_admin', 'sub': '999'}).encode()).decode().rstrip('=')}.{signature}",
        "no signature at all": unsigned,
        "not a token": "hello",
        "a refresh token": anon_client.cookies["vx_refresh"],
    }
    for name, token in attempts.items():
        response = anon_client.get("/courses", headers={"Authorization": f"Bearer {token}"})
        assert (response.status_code, response.json()) == (401, ENDED), name
    assert anon_client.get("/courses", headers={"Authorization": f"Bearer {good}"}).status_code == 200


def test_a_correctly_signed_token_must_still_belong_to_an_open_login_of_that_account(backend, anon_client, asha, make_account, time):
    sign_in(anon_client)
    with backend.db() as db:
        other = make_account(db, "ravi@example.com", PASSWORD).id
        session_id = db.query(AdminSession).one().id
    now = int(time.now.replace(tzinfo=timezone.utc).timestamp())

    def token(**claims):
        return forged({"sub": str(asha), "sid": session_id, "role": "admin", "iat": now, "exp": now + 900, **claims}, settings.jwt_secret)

    assert anon_client.get("/courses", headers={"Authorization": f"Bearer {token()}"}).status_code == 200
    for name, bad in {
        "another account's id on this login": token(sub=str(other)),
        "a login that does not exist": token(sid=session_id + 100),
        "no login named": jwt.encode({"sub": str(asha), "iat": now, "exp": now + 900}, settings.jwt_secret, algorithm="HS256"),
        "no expiry": jwt.encode({"sub": str(asha), "sid": session_id, "iat": now}, settings.jwt_secret, algorithm="HS256"),
        "already expired": token(exp=now - 1),
        "an id that is not a number": token(sub="asha@example.com"),
    }.items():
        assert anon_client.get("/courses", headers={"Authorization": f"Bearer {bad}"}).status_code == 401, name


@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer ", "Basic YXNoYTpwYXNz", "token abc", "abc"])
def test_a_request_without_a_bearer_token_is_not_logged_in(anon_client, header):
    response = anon_client.get("/courses", headers={"Authorization": header} if header is not None else {})

    assert (response.status_code, response.json(), response.headers["www-authenticate"]) == (401, {"detail": "Not logged in."}, "Bearer")


# ---- refresh ------------------------------------------------------------------------------------

def test_the_cookie_gets_a_new_access_token_when_the_old_one_has_run_out(backend, anon_client, asha, time):
    old = bearer(sign_in(anon_client))
    time.advance(minutes=20)
    assert anon_client.get("/courses", headers=old).status_code == 401

    renewed = anon_client.post("/auth/refresh")

    assert renewed.status_code == 200
    assert renewed.json()["data"]["account"]["email"] == "asha@example.com"
    assert renewed.json()["data"]["expires_in"] == 900 and renewed.headers["cache-control"] == "no-store"
    assert anon_client.get("/courses", headers=bearer(renewed)).status_code == 200
    # The cookie itself is not replaced, so two tabs renewing at once cannot log each other out.
    assert "set-cookie" not in renewed.headers
    with backend.db() as db:
        assert db.query(AdminSession).one().last_used_at == datetime(2026, 1, 5, 9, 20, 0)


def test_a_login_lasts_seven_days_and_no_longer(anon_client, asha, time, monkeypatch):
    # The absolute limit, for a login kept in use; the idle limit has tests of its own below.
    monkeypatch.setattr(settings, "auth_idle_minutes", 0)
    sign_in(anon_client)

    time.advance(days=6, hours=23, minutes=59)
    assert anon_client.post("/auth/refresh").status_code == 200
    time.advance(minutes=1)
    ended = anon_client.post("/auth/refresh")

    assert (ended.status_code, ended.json()) == (401, ENDED)


def test_without_the_cookie_there_is_nothing_to_renew(anon_client, asha):
    access_only = bearer(sign_in(anon_client))
    anon_client.cookies.clear()

    # The access token is not accepted in the cookie's place.
    response = anon_client.post("/auth/refresh", headers=access_only)

    assert (response.status_code, response.json()) == (401, {"detail": "Not logged in."})


def test_an_unknown_cookie_is_refused_and_taken_away(backend, anon_client, asha):
    sign_in(anon_client)
    response = backend().post("/auth/refresh", headers={"Cookie": "vx_refresh=made-up-value"})

    assert (response.status_code, response.json()) == (401, ENDED)
    cleared = response.headers["set-cookie"].lower()
    assert cleared.startswith('vx_refresh="";') and "max-age=0" in cleared and "path=/auth" in cleared
    assert logins(backend) == [(asha, False)]


# ---- logout -------------------------------------------------------------------------------------

def test_logging_out_ends_that_login_at_once(backend, anon_client, asha, time):
    token = bearer(sign_in(anon_client))
    assert anon_client.get("/courses", headers=token).status_code == 200

    response = anon_client.post("/auth/logout")

    assert (response.status_code, response.json()["message"]) == (200, "Logged out")
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert logins(backend) == [(asha, True)]
    # The access token had fourteen minutes left. It is refused all the same, without any waiting.
    assert (anon_client.get("/courses", headers=token).status_code, anon_client.get("/auth/me", headers=token).status_code) == (401, 401)
    assert anon_client.post("/auth/refresh").status_code == 401


def test_logging_out_on_one_device_leaves_the_other_logged_in(backend, asha, time):
    laptop, phone = backend(), backend()
    laptop_token, phone_token = bearer(sign_in(laptop)), bearer(sign_in(phone))

    laptop.post("/auth/logout")

    assert laptop.get("/courses", headers=laptop_token).status_code == 401
    assert phone.get("/courses", headers=phone_token).status_code == 200
    assert phone.post("/auth/refresh").status_code == 200
    assert logins(backend) == [(asha, True), (asha, False)]


def test_logging_out_works_after_the_access_token_has_run_out(backend, anon_client, asha, time):
    sign_in(anon_client)
    time.advance(hours=3)

    assert anon_client.post("/auth/logout").status_code == 200
    assert logins(backend) == [(asha, True)]


def test_logging_out_without_being_logged_in_is_not_an_error(backend, anon_client, asha):
    assert anon_client.post("/auth/logout").status_code == 200
    assert backend().post("/auth/logout", headers={"Cookie": "vx_refresh=made-up-value"}).status_code == 200


# ---- requests the console did not make ----------------------------------------------------------

NOT_FROM_THE_CONSOLE = {"detail": "Refused: this request did not come from the Vernex console."}


def outside_browser(backend):
    # A client that does not send the console's header, with the refresh cookie of a login.
    from fastapi.testclient import TestClient

    from app.main import app

    browser = TestClient(app, base_url="https://testserver")
    assert sign_in(browser).status_code == 200
    return browser


@pytest.mark.parametrize("route", ["/auth/refresh", "/auth/logout"])
@pytest.mark.parametrize("headers", [
    {},  # no header of its own: what a form or a plain fetch from another page sends
    {"X-Requested-With": "XMLHttpRequest"},
    {"X-Requested-With": "vernex", "Sec-Fetch-Site": "same-site", "Origin": "http://localhost:3999"},
    {"X-Requested-With": "vernex", "Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"},
    {"X-Requested-With": "vernex", "Sec-Fetch-Site": "cross-site"},
], ids=["no header", "another value", "another port", "another site", "another site, no origin"])
def test_a_request_another_page_makes_with_the_cookie_is_refused_and_changes_nothing(backend, asha, time, route, headers):
    browser = outside_browser(backend)

    answer = browser.post(route, headers=headers)

    assert (answer.status_code, answer.json()) == (403, NOT_FROM_THE_CONSOLE)
    # The cookie is not taken away and the login is not ended: the console goes on as before.
    assert "set-cookie" not in answer.headers
    assert browser.post("/auth/refresh", headers={"X-Requested-With": "vernex"}).status_code == 200
    assert logins(backend) == [(asha, False)]


@pytest.mark.parametrize("headers", [
    {"X-Requested-With": "vernex"},
    {"X-Requested-With": "vernex", "Sec-Fetch-Site": "same-origin", "Origin": "https://testserver"},
    {"X-Requested-With": "vernex", "Sec-Fetch-Site": "none"},
    # An origin named in FRONTEND_ORIGIN (the tests name http://localhost:5173) is let through.
    {"X-Requested-With": "vernex", "Sec-Fetch-Site": "same-site", "Origin": "http://localhost:5173"},
], ids=["no fetch metadata", "same origin", "typed by the person", "an allowed origin"])
def test_the_console_renews_and_logs_out_as_before(backend, asha, time, headers):
    browser = outside_browser(backend)

    renewed = browser.post("/auth/refresh", headers=headers)
    ended = browser.post("/auth/logout", headers=headers)

    assert (renewed.status_code, ended.status_code) == (200, 200)
    assert logins(backend) == [(asha, True)]


def test_logging_in_needs_no_header_so_scripts_can_log_in(backend, asha, time):
    from fastapi.testclient import TestClient

    from app.main import app

    assert sign_in(TestClient(app, base_url="https://testserver")).status_code == 200


# ---- a login, a logout, a password change and their audit entries -------------------------------

@pytest.fixture()
def audit_breaks(monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.services import audit_service

    writing = audit_service.record

    def for_actions(*actions):
        def record(db, action, **fields):
            if action in actions:
                raise OperationalError("INSERT INTO audit_logs (...) VALUES (...)", {}, Exception("disk I/O error"))
            return writing(db, action, **fields)
        monkeypatch.setattr(audit_service, "record", record)

    return for_actions


def audit_rows(backend):
    from app.models.audit_log import AuditLog

    with backend.db() as db:
        return [row.action for row in db.query(AuditLog).order_by(AuditLog.id)]


def test_a_login_whose_entry_cannot_be_written_is_not_made(backend, anon_client, asha, time, audit_breaks):
    audit_breaks("auth.login")

    answer = sign_in(anon_client)

    # Told it failed, and it did: no login was saved, no cookie given, no token handed out.
    assert answer.status_code == 500 and "access_token" not in answer.text and "set-cookie" not in answer.headers
    assert logins(backend) == [] and stored(backend).last_login_at is None


def test_a_refused_login_is_answered_as_refused_even_if_its_entry_cannot_be_written(backend, anon_client, asha, time, audit_breaks, caplog):
    audit_breaks("auth.login_failed")

    with caplog.at_level(logging.DEBUG):
        answer = sign_in(anon_client, password="not the password at all")

    assert (answer.status_code, answer.json()) == (401, WRONG)
    logged = [record.getMessage() for record in caplog.records if record.name == "vernex.audit"]
    assert len(logged) == 1 and "A refused login (wrong_password) was not written to the audit log: OperationalError" in logged[0]
    assert "asha@example.com" not in logged[0] and "not the password" not in logged[0]
    # The attempt was still counted towards the lock.
    assert stored(backend).failed_login_count == 1


def test_logging_out_works_even_if_its_entry_cannot_be_written(backend, anon_client, asha, time, audit_breaks, caplog):
    sign_in(anon_client)
    audit_breaks("auth.logout")

    with caplog.at_level(logging.DEBUG):
        answer = anon_client.post("/auth/logout")

    # Logging out must never depend on the audit log: the login has ended, and the log says the entry is missing.
    assert answer.status_code == 200 and logins(backend) == [(asha, True)]
    assert anon_client.post("/auth/refresh").status_code == 401
    assert audit_rows(backend) == ["auth.login"]
    assert any("Logout of account" in record.getMessage() and "not written to the audit log" in record.getMessage() for record in caplog.records)


def test_a_logout_is_written_in_the_same_commit_as_the_end_of_the_login(backend, anon_client, asha, time):
    sign_in(anon_client)
    anon_client.post("/auth/logout")

    assert audit_rows(backend) == ["auth.login", "auth.logout"]


def test_a_password_change_whose_entry_cannot_be_written_is_not_made(backend, anon_client, asha, time, audit_breaks):
    token = bearer(sign_in(anon_client))
    audit_breaks("auth.password_changed")

    answer = change(anon_client, token)

    assert answer.status_code == 500
    # The old password still works, and the logins it had are still open.
    assert anon_client.get("/courses", headers=token).status_code == 200
    assert sign_in(backend(), password=PASSWORD).status_code == 200
    assert sign_in(backend(), password=OTHER_PASSWORD).status_code == 401


# ---- who am I -----------------------------------------------------------------------------------

def test_me_needs_a_login_and_never_shows_the_hash(anon_client, asha):
    assert anon_client.get("/auth/me").status_code == 401
    answer = anon_client.get("/auth/me", headers=bearer(sign_in(anon_client)))

    assert answer.json()["data"]["full_name"] == "Asha Example"
    assert "password_hash" not in answer.text and "argon2" not in answer.text
    assert "failed_login_count" not in answer.text and "locked_until" not in answer.text


# ---- changing the password ----------------------------------------------------------------------

def change(client, token, current=PASSWORD, new=OTHER_PASSWORD):
    return client.post("/auth/change-password", json={"current_password": current, "new_password": new}, headers=token)


def test_changing_the_password_ends_every_login_and_the_old_password(backend, asha, time):
    laptop, phone = backend(), backend()
    laptop_token, phone_token = bearer(sign_in(laptop)), bearer(sign_in(phone))
    before = stored(backend).password_hash

    response = change(laptop, laptop_token)

    assert (response.status_code, response.json()["message"]) == (200, "Password changed. Log in again with the new password.")
    assert "max-age=0" in response.headers["set-cookie"].lower()
    after = stored(backend)
    assert after.password_hash != before and after.password_hash.startswith("$argon2id$") and OTHER_PASSWORD not in after.password_hash
    assert logins(backend) == [(asha, True), (asha, True)]
    for device, token in ((laptop, laptop_token), (phone, phone_token)):
        assert device.get("/courses", headers=token).status_code == 401
    assert phone.post("/auth/refresh").status_code == 401
    assert sign_in(backend()).status_code == 401
    assert sign_in(backend(), password=OTHER_PASSWORD).status_code == 200


def test_the_current_password_must_be_right(backend, anon_client, asha, time):
    token = bearer(sign_in(anon_client))
    before = stored(backend).password_hash

    response = change(anon_client, token, current="not the password!")

    assert (response.status_code, response.json()) == (400, {"detail": "The current password is incorrect."})
    assert stored(backend).password_hash == before and stored(backend).failed_login_count == 1
    assert anon_client.get("/courses", headers=token).status_code == 200


def test_guessing_the_current_password_locks_the_account_like_guessing_at_the_login(backend, anon_client, asha, time):
    token = bearer(sign_in(anon_client))

    answers = [change(anon_client, token, current=f"wrong password {number}").status_code for number in range(6)]

    assert answers == [400, 400, 400, 400, 429, 429]
    assert change(anon_client, token).status_code == 429  # the right one, too late
    assert sign_in(backend()).status_code == 429


@pytest.mark.parametrize("new, reason", [
    ("too short", "Password must have at least 10 characters."),
    ("p" * 129, "Password must have at most 128 characters."),
    ("asha@example.com", "Password must not be the same as the email address."),
    ("ASHA@Example.com", "Password must not be the same as the email address."),
    ("qwertyuiop", "This password is one of the most commonly used. Choose another one."),
    ("1234567890", "This password is one of the most commonly used. Choose another one."),
    (PASSWORD, "The new password must be different from the current one."),
])
def test_a_new_password_that_breaks_the_rules_is_refused_and_nothing_changes(backend, anon_client, asha, time, new, reason):
    token = bearer(sign_in(anon_client))
    before = stored(backend).password_hash

    response = change(anon_client, token, new=new)

    assert (response.status_code, response.json()) == (400, {"detail": reason})
    assert stored(backend).password_hash == before
    # Knowing the current password is not a failed attempt, whatever was wrong with the new one.
    assert stored(backend).failed_login_count == 0
    assert anon_client.get("/courses", headers=token).status_code == 200 and logins(backend) == [(asha, False)]


def test_changing_the_password_needs_a_login(anon_client, asha):
    assert change(anon_client, {}).status_code == 401


# ---- a temporary password -----------------------------------------------------------------------

def test_an_account_that_must_change_its_password_can_do_nothing_else_first(backend, anon_client, make_account, time):
    with backend.db() as db:
        make_account(db, "new.admin@example.com", PASSWORD, must_change_password=True)

    login = sign_in(anon_client, email="new.admin@example.com")
    token = bearer(login)

    assert login.json()["data"]["account"]["must_change_password"] is True
    for method, path in (("GET", "/courses"), ("GET", "/users"), ("POST", "/courses/create"), ("GET", "/health/details"), ("POST", "/face/recognize")):
        blocked = anon_client.request(method, path, headers=token)
        assert (blocked.status_code, blocked.json()) == (403, {"detail": "Change your password before continuing."}), path
    assert anon_client.get("/auth/me", headers=token).status_code == 200

    assert change(anon_client, token).status_code == 200
    again = sign_in(anon_client, email="new.admin@example.com", password=OTHER_PASSWORD)
    assert again.json()["data"]["account"]["must_change_password"] is False
    assert anon_client.get("/courses", headers=bearer(again)).status_code == 200


# ---- the signing secret -------------------------------------------------------------------------

@pytest.mark.parametrize("secret", ["", "zq7-tiny-value", "zq7" + "x" * 28])
def test_without_a_long_enough_secret_nothing_is_signed(monkeypatch, secret):
    monkeypatch.setattr(settings, "jwt_secret", secret)

    with pytest.raises(RuntimeError) as error:
        auth_service.signing_key()

    assert "JWT_SECRET" in str(error.value) and "create_jwt_secret.py" in str(error.value)
    # The message says what to do. It does not repeat the value that was found.
    assert "zq7" not in str(error.value)


def test_replacing_the_secret_ends_the_tokens_in_use_but_not_the_logins(anon_client, asha, time, monkeypatch):
    old = bearer(sign_in(anon_client))
    assert anon_client.get("/courses", headers=old).status_code == 200

    monkeypatch.setattr(settings, "jwt_secret", "a-new-secret-after-the-old-one-leaked-0123456789")
    auth_service.reset_memory()  # the backend is restarted to pick a new secret up

    # Whoever holds an old token, the owner included, is refused; the cookie gets the owner a new one.
    assert anon_client.get("/courses", headers=old).status_code == 401
    renewed = anon_client.post("/auth/refresh")
    assert renewed.status_code == 200 and anon_client.get("/courses", headers=bearer(renewed)).status_code == 200


def test_a_secret_of_thirty_two_bytes_is_enough(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "k" * 32)

    assert auth_service.signing_key() == "k" * 32


def test_the_backend_refuses_to_start_without_the_secret_and_touches_nothing(monkeypatch):
    from app import main

    touched = []
    monkeypatch.setattr(settings, "jwt_secret", "")
    monkeypatch.setattr(main, "init_database_schema", lambda: touched.append("database"))
    monkeypatch.setattr(main, "warm_up", lambda: touched.append("models"))

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        main.startup()

    assert touched == []


def test_there_is_no_secret_and_no_password_in_the_settings_file_or_its_template():
    from pathlib import Path

    backend_folder = Path(__file__).resolve().parents[1]
    template = (backend_folder / ".env.example").read_text(encoding="utf-8")
    settings_source = (backend_folder / "app" / "config.py").read_text(encoding="utf-8")

    # The template names the setting and leaves it empty; the code has no fallback value for it.
    assert "\nJWT_SECRET=\n" in template.replace("\r\n", "\n")
    assert 'os.getenv("JWT_SECRET", "")' in settings_source


# ---- nothing secret is logged -------------------------------------------------------------------

def test_no_password_token_or_hash_is_written_to_the_log(backend, anon_client, asha, time, caplog):
    with caplog.at_level(logging.DEBUG):
        sign_in(anon_client, password="a wrong password!")
        login = sign_in(anon_client)
        access, refresh = login.json()["data"]["access_token"], anon_client.cookies["vx_refresh"]
        anon_client.get("/courses", headers=bearer(login))
        anon_client.post("/auth/refresh")
        change(anon_client, bearer(login), current="another wrong one!")
        change(anon_client, bearer(login))
        anon_client.post("/auth/logout")
    written = "\n".join(record.getMessage() for record in caplog.records)

    for secret in (PASSWORD, OTHER_PASSWORD, "a wrong password!", "another wrong one!", access, refresh, "$argon2", settings.jwt_secret):
        assert secret not in written


# ---- housekeeping and accounts ------------------------------------------------------------------

def test_logging_in_clears_away_logins_that_ran_out_long_ago(backend, anon_client, asha, time):
    with backend.db() as db:
        db.add(AdminSession(account_id=asha, token_hash="a" * 64, expires_at=time.now - timedelta(days=2)))
        db.add(AdminSession(account_id=asha, token_hash="b" * 64, expires_at=time.now - timedelta(hours=2)))
        db.commit()

    sign_in(anon_client)

    with backend.db() as db:
        assert sorted(row.token_hash[0] for row in db.query(AdminSession) if len(set(row.token_hash)) == 1) == ["b"]
        assert db.query(AdminSession).count() == 2


def test_an_account_is_created_with_its_email_in_small_letters_and_its_password_hashed(db_session):
    account = auth_service.create_account(db_session, "  New.Admin@Example.com ", "  New   Admin ", PASSWORD, role="super_admin")
    db_session.commit()

    assert (account.email, account.full_name, account.role, account.status, account.must_change_password) == ("new.admin@example.com", "New Admin", "super_admin", "active", False)
    assert account.password_hash.startswith("$argon2id$") and PASSWORD not in account.password_hash


@pytest.mark.parametrize("fields, status, reason", [
    ({"email": "not an email"}, 400, "Enter a valid email address, like name@example.com."),
    ({"email": "a" * 115 + "@example.com"}, 400, "Email must be at most 120 characters."),
    ({"full_name": "   "}, 400, "Enter a full name (160 characters at most)."),
    ({"full_name": "n" * 161}, 400, "Enter a full name (160 characters at most)."),
    ({"role": "owner"}, 400, "Role must be super_admin or admin."),
    ({"password": "too short"}, 400, "Password must have at least 10 characters."),
    ({"password": "new.admin@example.com"}, 400, "Password must not be the same as the email address."),
    ({"email": "TAKEN@example.com"}, 409, "An account with this email already exists."),
])
def test_an_account_that_cannot_be_saved_is_refused_with_the_reason(db_session, make_account, fields, status, reason):
    make_account(db_session, "taken@example.com")
    details = {"email": "new.admin@example.com", "full_name": "New Admin", "password": PASSWORD, "role": "admin", **fields}

    with pytest.raises(AuthError) as error:
        auth_service.create_account(db_session, **details)

    assert (error.value.status, error.value.message) == (status, reason)
    assert db_session.query(AdminAccount).count() == 1


# ---- logins left unused (task S-16) ------------------------------------------------------------------
# The console renews its token every 14 minutes while it is open, and logs itself out after 30 minutes
# without a click or a key. The server's side: a login not renewed for 30 minutes cannot be renewed.

def test_a_login_unused_for_more_than_the_idle_limit_ends(anon_client, asha, time, backend):
    sign_in(anon_client)

    time.advance(minutes=settings.auth_idle_minutes, seconds=1)
    ended = anon_client.post("/auth/refresh")

    assert (ended.status_code, ended.json()) == (401, ENDED)
    with backend.db() as db:
        assert db.query(AdminSession).one().revoked_at is not None
    # Gone for good: coming back sooner does not revive it.
    assert anon_client.post("/auth/refresh").status_code == 401


def test_a_login_renewed_within_the_idle_limit_goes_on(anon_client, asha, time):
    sign_in(anon_client)

    for _ in range(12):  # three hours, renewed every 14 minutes as the console does
        time.advance(minutes=14)
        assert anon_client.post("/auth/refresh").status_code == 200


def test_an_idle_limit_of_0_switches_the_rule_off(anon_client, asha, time, monkeypatch):
    monkeypatch.setattr(settings, "auth_idle_minutes", 0)
    sign_in(anon_client)

    time.advance(hours=5)

    assert anon_client.post("/auth/refresh").status_code == 200
