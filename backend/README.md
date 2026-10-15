# Vernex Smart Attendance AI Backend

FastAPI backend for a local-first attendance MVP using Supabase PostgreSQL.

## Structure

```text
backend/
├── app/
├── migrations/
├── scripts/
├── .env
├── requirements.txt
└── README.md
```

## Setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## .env

Use your Supabase PostgreSQL connection string:

```env
DATABASE_URL=postgresql://postgres.PROJECT_REF:ENCODED_PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres
FACE_MATCH_THRESHOLD=0.60
GOOGLE_SCRIPT_URL=
DEFAULT_TIMEZONE=Asia/Kolkata
JWT_SECRET=
```

If `DATABASE_URL` is missing, the app falls back to local SQLite for quick testing.

`JWT_SECRET` signs the login tokens and the backend does not start without one of at least 32
characters. Do not type it: this writes a random one into `.env` without showing it.

```powershell
python scripts/create_jwt_secret.py
```

The other login settings (`AUTH_ACCESS_MINUTES`, `AUTH_REFRESH_DAYS`, `AUTH_COOKIE_PATH`, `API_DOCS`)
are optional and explained in `.env.example`.

Important password encoding rule:

- Every `@` in the password must be encoded as `%40`.
- Every `%` in the password must be encoded as `%25`.
- Do not add `?pgbouncer=true` to `DATABASE_URL`.
- Use Python to encode the password:

```python
from urllib.parse import quote
encoded = quote(password, safe="")
```

If the backend says the host contains `@`, your password was not URL-encoded.

## Initialize Tables

Option 1: Run SQL in Supabase SQL Editor:

```text
migrations/001_initial_schema.sql
```

and then the later migrations in order (`002` to `007`; `007_issues.sql` adds the reported issues
and their comments). For a new, empty database `migrations/full_schema.sql` is all of them in one file.

Option 2: Use SQLAlchemy:

```powershell
python scripts/init_db.py
```

## Test Supabase Connection

```powershell
python scripts/test_supabase_connection.py
```

## Create the first super admin

Nobody can log in until an account exists, and none is created by default.

```powershell
python scripts/create_super_admin.py           # the first super admin
python scripts/create_super_admin.py --force   # another one, or a new password for one that is or was a super admin
```

The email, name and password are asked for at the prompt (the password hidden, twice). No option,
file or pipe supplies a password. With `--force`, an email that is already a super admin is
confirmed by typing it again; its password is then replaced, the account unlocked and enabled, and
all its logins ended. The root `README.md` has the details under "Logging in and accounts".

## Run

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Docs (only when `API_DOCS=true` is set in `.env`; off by default):

```text
http://localhost:8000/docs
```

Health (public; answers `ok`, `starting` or `unavailable` and nothing else):

```text
http://localhost:8000/health
```

## Main APIs

Every route needs a login except `GET /health`, `POST /auth/login`, `POST /auth/refresh` and
`POST /auth/logout`. Send the access token as `Authorization: Bearer ...`.

- `POST /auth/login` email and password → access token (15 minutes) and the refresh cookie (7 days)
- `POST /auth/refresh` the cookie → a new access token
- `POST /auth/logout` ends that login
- Both of these need the header `X-Requested-With: vernex` (the console sends it); without it they
  answer `403` and change nothing, so that a page on another origin cannot use the cookie
- A temporary password from the portal works for 72 hours; after that `POST /auth/login` answers
  `403` ("This temporary password has expired...") and a login opened with it ends
- `GET /auth/me` the logged-in account
- `POST /auth/change-password` current and new password; ends every login of the account
- Super admins only (an admin gets `403`):
  - `GET /super-admin/dashboard` account counts, today's attendance, the newest audit entries, open
    issues by severity, issues resolved this week (Monday to Sunday) and the five newest open issues
  - `GET /super-admin/admins?search=&status=&role=`, `POST /super-admin/admins` (email, full_name,
    role; answered with a temporary password, once)
  - `GET|PUT /super-admin/admins/{id}` (email, full_name, role)
  - `POST /super-admin/admins/{id}/disable`, `/enable`, `/reset-password` (a new temporary password,
    for 72 hours; only for an admin that has never been a super admin: the password of an account
    that is or was one is reset with `scripts/create_super_admin.py --force`)
  - `GET /super-admin/audit-logs?actor_id=&action=&target_type=&date_from=&date_to=&page=&page_size=`,
    `GET /super-admin/audit-logs/actions`. There is no route that changes or deletes an entry.
  - `GET /super-admin/issues?status=&severity=&category=&reporter_id=&date_from=&date_to=&sort=&page=&page_size=`
    every reported issue. `status` is one status or `unresolved` (open and in progress); `sort` is
    `newest` or `severity`; the dates are days in the school's time zone
  - `GET /super-admin/issues/open-count` how many are open or in progress (the portal's badge)
  - `GET /super-admin/issues/{id}` one issue with its comments
  - `PUT /super-admin/issues/{id}` any of `status`, `resolution_note`, `assigned_to`. Resolving needs
    a note; `assigned_to` is an active super admin or `null`. A change of status is written to the
    audit log together with it
  - `POST /super-admin/issues/{id}/comments` (`body`); `409` on a closed issue
- Issues, for any account that is logged in, about its own issues only (someone else's is `404`, the
  same as a number that does not exist):
  - `POST /issues` title (5 to 120 characters), description (10 to 4000), category (`bug`,
    `face_recognition`, `attendance_data`, `camera_device`, `login_access`, `other`), severity (`low`,
    `medium`, `high`, `critical`), `page_url` (a path inside the console, like `/dashboard`) and
    `device_info` (`browser`, `os`, `screen`, up to 100 characters each). Anything else, such as who
    reported it or a status, is refused (`422`). Written to the audit log together with it
  - `GET /issues?status=&page=&page_size=`, `GET /issues/{id}` (with its comments; the resolution
    note once it is resolved)
  - `POST /issues/{id}/comments` (`body`, 1 to 4000 characters); `409` on a closed issue
  - No route deletes an issue or changes or deletes a comment. A refused request on `/issues` (like
    `/auth` and `/super-admin`) says what is wrong without repeating what was sent
- Paged lists (`/issues`, `/super-admin/issues`, `/super-admin/audit-logs`): `page` is 1 to 10,000 and
  `page_size` 1 to 100 (`app/routes/paging.py`); anything else is refused with `422`
- `GET /`
- `GET /health`, `GET /health/details` (database and face models; needs a login)
- `GET /courses`, `POST /courses/create`, `GET|PUT|DELETE /courses/{course_id}`
- `GET /batches`, `POST /batches/create`, `GET|PUT|DELETE /batches/{batch_id}`
- `GET /users`, `POST /users/create`, `GET|PUT|DELETE /users/{person_id}`
- `POST /courses/upload`, `GET /courses/upload/template`
- `POST /batches/upload`, `GET /batches/upload/template`
- `POST /users/upload?person_type=student|admin|member`, `GET /users/upload/template?person_type=...`
- `POST /people/create`
- `GET /people`
- `GET /people/{person_id}`
- `PUT /people/{person_id}`
- `DELETE /people/{person_id}`
- `POST /timings/create`
- `GET /timings`
- `GET /timings/{timing_id}`
- `PUT /timings/{timing_id}`
- `DELETE /timings/{timing_id}`
- `POST /attendance/session/start`
- `GET /attendance/sessions`
- `GET /attendance/today`
- `POST /attendance/mark`, `POST /attendance/mark-absent` (marked by hand; written to the audit log).
  `recognition_method: "auto_absent"` means absent, in every kind of session; the mark-absent route
  sets it. Any other method follows the session: `visited` for a member visit, otherwise `present`,
  or `late`/`absent` by the session's times
- `POST /face/enrollment/start/{person_id}`
- `POST /face/enrollment/frame`
- `POST /face/enrollment/complete/{person_id}`
- `GET /face/enrollment/status/{person_id}`
- `POST /face/recognize`
- `POST /sheet/sync-pending`
- `GET /sheet/status`

The face endpoints run DeepFace (YOLOv8 detector + Facenet512). See the root `README.md` for the full run guide, workflow and face settings.

## Answers and errors

A request that succeeds is answered `{"success": true, "message": "...", "data": ...}`. One that is
refused is answered with the HTTP status and `{"detail": "why"}`:

- `401` not logged in, or the login has ended (`"Not logged in."`, `"Your session has ended. Log in again."`)
- `403` logged in but not allowed: a disabled account, a page for super admins, or an account that
  must change its temporary password first
- `400`/`409` from the portal: disabling, demoting or resetting yourself, removing the last active
  super admin, an email another account has, disabling an account that already is
- `429` too many failed logins for an email (locked for 15 minutes) or too many login attempts from
  one address in a minute; `Retry-After` says how long to wait
- `400` a value that cannot be used: an empty course code, a contact number that is not ten digits
  (`"Contact number: Phone number must have exactly 10 digits (found 3)"`), an upload that cannot be
  read as a whole (wrong type, too large, a required column missing)
- `404` the course, batch or person does not exist
- `409` it would be a duplicate: `"Course code already exists"`, `"Batch already exists under this course"`,
  `"ID already exists"` (a person's ID, across students, staff and members)
- `500` something nobody expected. The answer is `{"success": false, "message": "Something went
  wrong on the server... reference: ab12cd34"}` and nothing else; the backend's log has a line with
  the same reference saying which request it was, what kind of error and where, without the
  values involved

## Bulk upload

`POST /courses/upload`, `/batches/upload` and `/users/upload?person_type=...` take a `.xlsx` or
`.csv` file in a multipart field named `file` (5 MB, 2,000 data rows). Valid rows are saved, the
others are reported with their row number, column, value and reason. The column names, the rules
for contact numbers and what the answer contains are in the root `README.md`, under "Bulk upload
from Excel or CSV". Reading and writing `.xlsx` needs `openpyxl` (in `requirements.txt`).

## Tests

```powershell
.venv\Scripts\python -m pytest
```
