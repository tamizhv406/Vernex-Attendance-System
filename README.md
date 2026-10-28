# Vernex Smart Attendance

Face-recognition and QR-code attendance for courses and batches, staff and members. A phone (or any
webcam) streams live video to the backend, which finds every face in the frame, matches it against the
enrolled people of the session, and marks attendance. Everyone also has a QR card with a random
attendance code, which the QR Attendance page scans (or a desk types) into the same register.

- `backend/` — FastAPI + SQLAlchemy, Supabase PostgreSQL, DeepFace (YOLOv8 face detector + Facenet512)
- `frontend/` — React + Vite admin dashboard, enrollment camera and live scanner

## Run it

You need Python 3.10, Node 20+, and the PC and phone on the same Wi-Fi.

### 1. Backend (first terminal)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create `backend/.env` (never committed):

```env
DATABASE_URL=postgresql://postgres.PROJECT_REF:ENCODED_PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres
DEFAULT_TIMEZONE=Asia/Kolkata
```

Copy the host from Supabase → Connect → Transaction pooler; the region must be your project's.
In the password, write `@` as `%40` and `%` as `%25`. Without `DATABASE_URL` the app uses a local SQLite file.

```powershell
python scripts/create_jwt_secret.py          # writes JWT_SECRET into backend/.env without showing it
python scripts/check_database.py             # read-only: connection, schema, row level security (no secrets shown)
python scripts/create_super_admin.py         # asks for an email, a name and a password: the first login
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

On the local SQLite file the tables are created automatically on startup. On PostgreSQL (Supabase)
the backend creates and changes nothing: run `backend/migrations/full_schema.sql` once on a new, empty
database (in Supabase's SQL editor), or the numbered files it does not have yet (up to
`008_row_level_security.sql`) on an older one. If anything is missing, the backend refuses to start
and names it; `scripts/check_database.py` shows the same without starting anything. Run the backend
as **one** process (no `--workers`): enrollments in progress and the scanner's tracking are kept in
its memory. For use beyond your own computer, serve the built console with `deploy/Caddyfile`
(HTTPS, security headers) instead of the development server; `docs/RUNBOOK.md` has the steps,
backups, secret rotation and the least-privilege database account. Wait for `face models ready` in the log (about 30 seconds;
the first ever start also downloads ~100 MB of model weights). http://localhost:8000/health answers
`"status":"starting"` until then and `"status":"ok"` after, or `"status":"failed"` if the models could not be loaded (the log says why). The backend refuses to start without a
`JWT_SECRET`, and nobody can log in before a super admin exists: see "Logging in and accounts".

### 2. Frontend (second terminal)

```powershell
cd frontend
npm install
npm run dev:https
```

HTTPS is required because browsers only open the camera on secure pages. The terminal prints the links;
use the one that starts with your Wi-Fi address, for example `https://192.168.1.11:5173`.

### 3. Connect the phone

1. Open `https://<PC Wi-Fi address>:5173/attendance-scanner` in the phone's browser.
2. The certificate is self-signed, so accept the warning (Advanced → Proceed).
3. Log in, then allow camera access when asked.

If the page does not load: confirm both devices are on the same Wi-Fi, and allow Node.js through
Windows Firewall for your network type. The phone only talks to the frontend; Vite forwards `/api`
calls to the backend, so port 8000 does not need to be reachable from the phone.

## Logging in and accounts

Every page and every API route needs a login. The accounts that can log in are kept in their own
table, `admin_accounts`. They are **not** the people under Staff: in `user_management`,
`person_type='admin'` means a staff member whose attendance is taken, and such a row opens nothing.

There are two roles. An **admin** uses the console (courses, batches, people, enrollment, scanner,
reports); a phone that runs the scanner logs in as one. A **super admin** can do the same and lands
on the **Super Admin portal** (`/super-admin`), where the admin accounts are managed and the audit
log is read: see "The Super Admin portal" below. The first super admin is made with the script below;
every other account is best created in the portal.

### The first super admin

There is no default account and no default password. Create the first login on the machine that
runs the backend, after `DATABASE_URL` points at the database you will use:

```powershell
cd backend
.venv\Scripts\python scripts\create_super_admin.py
```

It says which database it will write to, then asks for the email, the name and the password. The
password is typed hidden, twice, and cannot be passed on the command line, in a file or through a
pipe. If a super admin already exists it changes nothing and says so. With `--force` it goes on:

- for a **new email** it adds another super admin;
- for an email that **is already a super admin** it asks you to type the email again, and then
  replaces that account's password, unlocks and enables it, and logs it out on every device. This
  is how a forgotten password or a locked-out super admin is recovered;
- for an admin that **was a super admin before** it does the same, and the account stays an admin.
  The portal never resets such an account's password (see "The Super Admin portal"), so this is its
  way back in;
- for the email of an admin that has never been a super admin it refuses: its password is reset in
  the portal.

### Passwords, lockout and sessions

- A password has at least 10 characters (128 at most), is not the account's email, and is not one
  of the commonly used ones in `backend/app/data/common_passwords.txt`. It is stored as an Argon2id
  hash and never written to a log.
- Five wrong passwords in a row lock an email for 15 minutes; the right password does not open it
  during that time. One device gets ten login attempts a minute. A wrong password and an email
  that has no account get exactly the same answers, lock included.
- Logging in gives the browser an access token that lasts 15 minutes and is kept in memory only,
  and a refresh cookie that lasts 7 days and that scripts cannot read (`HttpOnly`, `Secure`,
  `SameSite=Strict`). The page renews the access token by itself; reloading the page keeps you
  logged in; **Log out** ends that device's session at once. Only a hash of the refresh token is stored.
- **Settings → Change password** asks for the current password and logs the account out on every
  device. An account with a temporary password sees nothing but that form until it has been used.
- Because the cookie is `Secure`, log in through the `https://` links (the ones the camera needs
  anyway). On the PC itself `http://localhost:5173` also works in Chrome, Edge and Firefox.
- Renewing and logging out work on the cookie alone, so the backend accepts them only from the
  console: the request must carry the header `X-Requested-With: vernex`, which the console sends and
  a page on another site or another port of this machine cannot add. Such a request is refused with
  `403` and the login is left as it was.

### The Super Admin portal

Super admins only: an admin who types one of its addresses sees "Not allowed", and the backend
answers every `/super-admin/...` request from an admin with `403`. It has its own navigation
(Dashboard, Admins, Issues, Audit Log, and Back to console) on a computer and on a phone.

- **Dashboard**: active, disabled and locked-out accounts, accounts still on a temporary password,
  today's attendance totals, the newest audit entries, open issues by severity, issues resolved this
  week (Monday to Sunday, in the school's time zone) and links to the five newest open issues, all
  counted from the database. "Open" means open or in progress, here and on the badge.
- **Admins**: search by name or email, filter by status and role, add, edit, disable, enable and
  reset a password.
  - A new account and a reset get a **temporary password**, generated by the backend and shown to
    the super admin once. It is not stored anywhere readable, and the person must replace it at
    their first login. A super admin never chooses or sees anyone's own password.
  - A temporary password works for **72 hours**. After that it opens nothing, a login made with it
    ends, and the person is told how to get a new one ("This temporary password has expired..."); the
    Admins list marks it as expired. For an admin, a reset gives a new one for 72 hours. An account
    that is or has been a super admin (also one just created in the portal) cannot be reset here:
    whoever runs the backend sets a new password with `create_super_admin.py --force`. A password
    the person chose has no such limit, and neither has one typed on the server with `create_super_admin.py`.
  - Disabling an account or resetting its password logs it out on every device at once. So does a
    new role, so that the account comes back with the pages of that role. A reset leaves a disabled
    account disabled.
  - Nobody can disable themself, change their own role, or reset their own password here (Settings
    has Change password). The last active super admin cannot be disabled or demoted, also when two
    super admins try it at the same moment.
  - **Only the password of an admin that has never been a super admin is reset here.** Whoever
    resets a password is shown the new one and could log in with it first, which would let one super
    admin act under another's name. So every account that is or has ever been a super admin is marked
    for good (`has_been_super_admin`), and the portal refuses to reset its password, also after it
    was made an admin: taking the role away first is no way into someone's account. Such an account
    is recovered on the server: `backend\.venv\Scripts\python backend\scripts\create_super_admin.py --force`,
    type that account's email twice, then the new password (see "The first super admin"). A super
    admin stays a super admin and a former one stays an admin. It is written to the audit log as done
    on the command line. The Admins list switches the Reset button off for these accounts and says why.
  - Two super admins adding the same email at the same moment get one account; the other is told
    the email is taken (`409`), and nothing of their attempt is kept.
- **Issues**: every problem admins and super admins reported (see "Reporting a problem" below), 25 to
  a page. It opens on open and in-progress issues; one choice shows all statuses. Filter by status,
  severity, category, who reported it and the days it was reported; sort by newest or by severity
  (critical first). The list and the number next to Issues in the portal's navigation ask again every
  45 seconds while the page can be seen, and at once when the tab is shown again, so a new report
  turns up within the minute without pressing anything. They do not ask while the tab is hidden or
  outside the portal.
  - One issue's page (`/super-admin/issues/<number>`) has everything that was reported, the page it
    came from and the device, the thread of comments, and the status and who it is assigned to.
  - Any status may follow any other. **Resolving needs a resolution note** (1 to 4000 characters),
    which the reporter reads. Resolving sets the time it was resolved; closing a resolved issue keeps
    that time; opening it again (open or in progress) clears it. An issue opened again keeps its old
    note out of sight, and resolving it again asks for a note again (the old one is filled in to start from).
  - An issue is assigned to an active super admin only, or to nobody.
  - Comments are 1 to 4000 characters, cannot be changed or deleted, and a closed issue takes none.
    Nothing in an issue can be deleted through the app.
- **Audit Log**: who did what and when, newest first, filtered by person, action and days, 25 to a
  page. Recorded: logins (and failed logins, without the email that was typed), logouts, password
  changes, every change to an account, deleted people, courses and batches, attendance marked by hand,
  face enrollments started, completed or cancelled, bulk uploads, issues reported and every change of
  an issue's status, and what `create_super_admin.py` does. Assigning an issue and commenting are not
  recorded. No password, token, hash or face data is ever written to it. There is no way to change or
  delete an entry through the app.
  - Each action is saved in the same database transaction as its entry: both, or neither. If the
    entry cannot be written, the action is not saved and the person is told it failed. Two
    exceptions, on purpose: a **refused login** is still answered as refused (the refusal was
    decided first), and a **logout** still ends the login. In both cases the backend's log says
    which entry is missing, without the email or the password.
  - Searches and filters are sent in the address, and the backend's access log keeps every
    request's address: it keeps the names of those parameters but replaces their values with
    `[hidden]`, so an email typed into the search is not written to the log.

### Reporting a problem

Anyone who is logged in, admin or super admin, can report a problem from any page: **Report a
problem** is in the top bar on a computer, and under **More** on a phone or tablet (the scanner page
included). The form asks for a title (5 to 120 characters), a category (bug, face recognition,
attendance data, camera or device, login or access, other), a severity (low, medium, high, critical)
and what happened (10 to 4000 characters).

- Two things go with it, shown on the form before it is sent: the page it was reported from, as a
  path inside the console (`/attendance-scanner`, never the rest of the address), and the browser,
  the system and the screen size (`Edge 141 · Windows · 1920x1080`), nothing else about the device.
- Who reported it is the account that is logged in; the backend never takes it from the request.
- **My reports** (under System) lists one's own reports with their status. Each has its own page
  (`/my-reports/<number>`) with the thread: the reporter reads what super admins wrote and answers,
  and sees the resolution note once the issue is resolved. The reporter cannot change the status.
- Someone else's issue is "not found", by its number in the address or through the API (`404`, the
  same answer as for a number that does not exist).
- Everything typed is shown as plain text everywhere: `<script>` or HTML in a title, a description or
  a comment appears as those characters and is never run.
- Screenshots cannot be attached (the task sheet's optional v1.1 item is not built).

### What stays open

Without a login the backend answers only `GET /health` (one word: `ok`, `starting`, `failed` or `unavailable`)
and the login routes. Everything else answers `401`. `GET /health/details` (database and face
models) needs a login. `/docs` and `/openapi.json` are switched off unless `API_DOCS=true` is set in
`backend/.env`. An error nobody expected is answered with a generic sentence and a reference; what
went wrong is written to the backend's log under that reference, without the data involved.

### Settings in `backend/.env`

| Setting | Meaning |
| --- | --- |
| `JWT_SECRET` | Signs the access tokens. Required, 32 characters or more. `scripts\create_jwt_secret.py` writes a random one without showing it; `setup.bat` runs that. Never commit or share it. To replace it, delete the line, run the script again and restart the backend: the tokens in use stop working at once, and browsers that are logged in get new ones by themselves. |
| `AUTH_ACCESS_MINUTES`, `AUTH_REFRESH_DAYS` | How long the access token and the session last (15 and 7). |
| `AUTH_COOKIE_PATH` | The path the browser uses for the auth routes. `/api/auth` (the default) when the frontend forwards `/api` to the backend; `/auth` only if browsers call the backend's address directly. |
| `FRONTEND_ORIGIN` | Empty by default, and it should stay empty: the console reaches the backend through `/api` on its own address. Set it only if a page on another origin must call the backend directly, to that page's exact address (several are separated by commas), for example `https://console.example.com`. Patterns, `*` and `null` are ignored, because a page that may read the answers could take over the login of anyone who opens it. An older `backend/.env` may still have `FRONTEND_ORIGIN=http://localhost:5173` from the earlier template: remove that line. |
| `API_DOCS` | `true` serves `/docs` and `/openapi.json`. For your own machine only. |

## Workflow

1. **Courses → Batches → Students.** Create a course, a batch under it, then students assigned to both.
2. **Face Enrollment.** Choose **Students**, **Staff** or **Members**. For students pick course,
   batch and student; staff and members are listed in full (no course or batch), with a search by name
   or ID. Tick the consent box (the person, or for a minor a parent or guardian, agreed), choose the
   enrollment type and press Start Enrollment. **Quick** (the default) takes three poses: look straight, turn left, turn right.
   **Full** takes five (front, left, right, close, far). Only the student being enrolled may be in view.
   Capture starts as soon as the camera delivers a picture. A pose is taken from a short burst: the
   face has to stay in the oval, in place, through three good frames in a row, and the sharpest of
   them is kept. Every frame is checked for one face, position, size, light, sharpness and pose first;
   only frames that pass go on to the liveness check and the embedding model, and then must be the
   same person as the frames before. A refused frame says why ("Move closer", "Improve lighting",
   "One person at a time", "Pose not accepted" ...). Nothing is saved until every pose passes, and the
   previous enrollment stays in use until then. A face that is already enrolled under another person is refused.
3. **Attendance Scanner.** Choose the session: a **Batch class** (pick course and batch), **Staff** (every
   staff member) or **Members** (every member, marked `visited`). Optionally a "Late after" time (otherwise the batch's
   timetable decides, if it has one), press Start Session, and point the camera at the class.
   Every face in the frame gets its own box and its own verdict: green = identity verified,
   amber = still being verified, red = not verified (unknown person, "Unable to verify identity", or a
   photo), grey = too small, dark or blurred to judge. A camera that faces the person (a webcam, a
   front camera) is shown like a mirror, as in enrollment; a phone's rear camera is shown as it is.
4. **Marking.** A student is marked only after the same face has been identified as that student in
   3 separate looks in a row, all of them live, with an average score of at least 0.75, **and** has
   followed the head-turn instruction shown on its box (blue: "hold still, facing the camera", then
   "turn head to YOUR LEFT" or "RIGHT"): `present`,
   `late` after the session's grace time, `absent` after its end time. One record per student, session
   and day, enforced by the database. A session from an earlier day that was never stopped accepts no
   more scans: start a new one.
5. **Marking by hand.** Below the camera, every student of the batch has Present / Late / Absent
   buttons while the session runs: for a student who is locked, not recognized or has no face
   enrolled, and to correct a mark. Later, **Attendance Records** with a course, a batch and a date
   lists that day's sessions with the same register. A hand mark always belongs to a session and its
   date, is stored as "By hand" (never as a face scan) and is written to the audit log with who made it
   and what it was before.
6. **Stop Session**, then see **Attendance Records** for the records by date, course and batch. Staff
   and member records have no course or batch: leave "All courses" and use the **Who** filter
   (All / Students / Staff / Members).

**Who belongs to a session** (one rule for face scans, hand marks and codes, in
`attendance_service.person_in_session`): a batch class takes the people assigned to its course and
batch (staff and members only when assigned to that batch); a staff session takes staff only; a member
session takes members only. Anyone else is refused with a sentence saying why, and the face scanner
only compares faces of the people the session is for.

## Attendance codes and QR cards

Every student, staff member and member has an **attendance code**: 8 random characters (`K7M2-9QXD`,
from `0-9` and `A-Z` without I, L, O, U), made with Python's `secrets`. It is not the person ID, which is
short and sequential. A new person gets one at once, by the form or by a spreadsheet upload; people from
before this version get theirs from the backfill script (see "Database"). The QR on a card holds only
`VNXATT:` and the code: no name, no ID, nothing else.

- **People pages** (Students, Staff, Members): the code is shown under the person ID. The **QR** button
  on a row opens the card: download it as `<ID>-qr.png`, print it, or **Replace code** for a lost or
  shared card. The old code and its QR stop working at once; the audit log says "Attendance code
  replaced", without either code. A person without a code gets a **Create code** button.
- **Print QR cards (N)** prints the list as it is filtered (search, course, face): ID-card size
  (85.6 x 54 mm), 10 to an A4 page, through the browser's print dialog ("Save as PDF" works). More than
  300 cards asks first.
- **QR Attendance** (Attendance menu, and the phone's bottom bar): start a batch class, staff or members
  session, or **join** one already running today for the same scope (for example the face scanner's, on
  another device). Then scan cards with the camera (back camera first; the QR is read on the device,
  no picture is sent), or type a code (`XXXX-XXXX`, lowercase and without the hyphen also work; a USB
  or Bluetooth QR reader types into the same field). Green: marked; blue: already marked; red: the
  backend's reason (not in this batch, inactive, unknown or replaced code, session stopped); amber: no
  connection. Nothing is queued to send later. A typed code is written to the audit log like a hand
  mark; a scanned QR is not, like a face scan. Records say **QR scan** or **Code typed**.
- `POST /attendance/code/mark` (login required, 120 codes per account per minute) checks the session
  (running, today), the code, that the person is active and belongs to the session, and writes through
  the same one-record-per-person rule as the face scanner. Its answers never contain the code.
- Printed cards work like ID badges: someone holding another person's card can mark them. Face scans,
  spot checks and **Replace code** keep that in check.

Courses, batches and people can also be added many at a time from a spreadsheet: see
"Bulk upload" below.

Editing: the pencil on a row of Courses or Batches opens that record in the form above the list.
Changing a batch's **Course** moves the batch, and the people assigned to it move with it (the form
says how many before you save). Renaming a course or a batch changes the name shown for its people
from then on. Attendance that is already recorded keeps the course, batch and names it was taken under.

## Bulk upload from Excel or CSV

The Courses, Batches, Students, Staff and Members pages each have an **Upload** button. It takes
one `.xlsx` or `.csv` file of up to **5 MB** and **2,000 data rows**.

1. Press **Upload**, then **Download template**. The template is a workbook with the right column
   names in its first sheet (which is otherwise empty) and an `Instructions` sheet that explains
   every column and shows made-up example rows.
2. Type or paste your rows under the header row and save.
3. Choose the file and press **Upload**.

Upload courses first, then batches, then people: a batch needs its course to exist, and a student
needs both.

### Columns

The first row of the file must hold the column names. Capitals, spaces and hyphens do not matter
(`Course Code`, `course-code` and `course_code` are the same column), the order of the columns does
not matter, and in a workbook only the first sheet is read.

| Upload | Required columns | Optional columns |
| --- | --- | --- |
| Courses | `course_code`, `course_name` | `description` |
| Batches | `batch_name`, `course_code` | `batch_level` |
| Students | `student_id`, `full_name`, `parent_contact`, `course_code`, `batch_name` | `parent_name`, `level_class`, `joining_date`, `notes` |
| Staff | `staff_id`, `full_name`, `contact_number` | `email`, `course_code`, `batch_name`, `level_class`, `joining_date`, `notes` |
| Members | `member_id`, `full_name`, `contact_number` | `email`, `course_code`, `batch_name`, `level_class`, `joining_date`, `notes` |

- `course_code` is saved in capital letters and matched without regard to case. In the Batches,
  Students, Staff and Members files it must be the code of a course that already exists.
- `batch_name` in a people file must be a batch **of that course**. For staff and members both are
  optional, but a `batch_name` needs its `course_code`.
- `student_id`, `staff_id` and `member_id` are one kind of ID: no two people may share one, whatever
  they are, and `stu-001` is the same ID as `STU-001`.
- `parent_contact` and `contact_number` follow the rules under "Contact numbers" below.
- `joining_date` is written `2024-06-15` (year-month-day). `15-06-2024`, `15/06/2024` and
  `15-Jun-2024` are read as day-month-year, and a real Excel date cell is read as it is. Anything
  else, `06/15/2024` and two-digit years included, is reported instead of guessed.
- A number typed into Excel is read as the number it shows: `9876543210`, never `9876543210.0`.
  Excel drops leading zeros and a leading `+` from cells it treats as numbers; the template's
  columns are formatted as text so that what you type is kept.
- Any other column is not read. The result names the columns that were left out.

### What happens to a file

**The file as a whole is checked first.** A file of another type, an empty or damaged file, a file
over the size or row limit, a file without all the required columns, or one with no data rows is
refused (HTTP 400) with the reason, and **nothing from it is imported**.

**Then every row stands on its own.** Valid rows are imported; a row with a problem is skipped and
the other rows are not affected. Completely empty rows are ignored. The result shows how many rows
the file had, how many were imported and how many were skipped, and for every skipped row its row
number as the spreadsheet shows it, the column, the value that was given and the reason, for example:

| Row | Column | Value | Problem |
| --- | --- | --- | --- |
| 3 | `course_code` | | course_code is required |
| 5 | `parent_contact` | 123 | Phone number must have exactly 10 digits (found 3) |
| 6 | `batch_name` | Lab Group | This batch belongs to a different course (PHY101), not CS101 |
| 8 | `student_id` | stu-001 | Duplicate of row 2 in this file |
| 9 | `student_id` | STU-014 | Already exists: this ID belongs to a student |

A row is counted as imported only once the database has saved it, and the rows of one file are
saved together at the end: if the import fails part-way, none of them is left behind.

**Download skipped rows (CSV)** gives the skipped rows with their original values, their row numbers
and their problems. Correct them in that file and upload it again as it is: its `row` and `problem`
columns are not read. Uploading a file twice is harmless; the second time every row is reported as
already existing.

**What is saved.** An imported course or batch gets the status **Pending**, whatever a `status`
column in the file says, so that it can be reviewed; the Courses and Batches pages show the badge
and, once a list holds more than one status, a filter for it. Editing the record and choosing
Active clears it. An imported student, staff member or member is **Active**, with face enrollment
not started, exactly like one added through the form.

### Contact numbers

The same rule is applied by the forms, by the API and by uploads. A number is stored as exactly
**10 digits**.

| Written as | Result |
| --- | --- |
| `9876543210` | stored as `9876543210` |
| `98765 43210`, `98765-43210`, `987-654-3210` | stored as `9876543210` |
| `+91 98765 43210`, `+919876543210`, `+91-98765-43210` | stored as `9876543210` |
| `123`, `987654321`, `98765432101` | refused: not 10 digits |
| `919876543210`, `09876543210` | refused: 12 and 11 digits. Write the country code as `+91` |
| `+1 98765 43210`, `+ 91 98765 43210`, `91+9876543210` | refused: only `+91`, written at the start, is a country code |
| `98765abc10`, `(98765) 43210`, `98765.43210` | refused: letters and other symbols are not removed |

A number is never shortened, padded or stripped of characters to make it fit. The Students, Staff
and Members forms and all three people uploads require a contact number. The API itself still
accepts a person with no number at all, as it always did; what it refuses is a number that is wrong.

### The upload API

| Request | Purpose |
| --- | --- |
| `POST /courses/upload` | Import courses |
| `POST /batches/upload` | Import batches |
| `POST /users/upload?person_type=student` (or `admin` for staff, or `member`) | Import people |
| `GET /courses/upload/template`, `GET /batches/upload/template`, `GET /users/upload/template?person_type=...` | The template; add `format=csv` for a header-only CSV |

The file goes in a multipart form field named `file`. Like the rest of the API these addresses need
a login: the access token that `POST /auth/login` returns goes in the `Authorization` header.

```powershell
curl.exe -H "Authorization: Bearer ACCESS_TOKEN" -F "file=@students.xlsx" "http://localhost:8000/users/upload?person_type=student"
```

The answer has `total_rows`, `imported`, `skipped`, `errors` (one entry per problem: `row`,
`column`, `value`, `message`), `skipped_rows` (the skipped rows as they were given), `columns` and
`ignored_columns`.

## How recognition works

1. YOLOv8 finds every face in the frame; faces under 50 px, or too dark, bright or blurred, are not matched.
2. Facenet512 turns each face into a 512-number vector. Enrollment and the scanner prepare the face
   the same way (same crop, alignment, colour order and scaling), and that preparation is stored with
   every enrolled vector so vectors from different preparations are never compared.
3. The vector is compared (cosine similarity) with the enrolled students of that session's batch only,
   each represented by the average of their five poses.
4. A match needs similarity >= 0.60 **and** a lead of >= 0.05 over the next most similar student.
   Below the threshold the face is "Unknown"; too close to a second student it is "Unable to verify
   identity". The closest student is never assumed.
5. Faces are followed from frame to frame. What is collected for one face never counts for another:
   not for a second face that looks similar, not for whoever steps into the same spot, not on another
   camera. A different name, no name, or a photo on the same face starts the count again.
6. A liveness model (MiniFASNet) checks that a matched face is a real person and not a printed photo
   or a screen. Liveness is only ever a reason to refuse. It is never a reason to accept: a live face
   that does not match an enrolled student is not marked.
7. Each face is processed on its own. One student's poor, unknown or refused face does not hold up the
   others in the frame.

Decisions (who, score, runner-up, why refused) are written to `backend/logs/recognition.log` as ids
and numbers only. No camera frames and no face vectors are stored there.

Settings in `backend/.env`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `FACE_MATCH_THRESHOLD` | `0.60` | Raise to be stricter (fewer wrong names, more "Unknown") |
| `FACE_MATCH_MARGIN` | `0.05` | Required lead over the second-best student |
| `FACE_CONFIRM_FRAMES` | `3` | Separate looks at one face, in a row, needed before attendance is written |
| `FACE_CONFIRM_SCORE` | `0.75` | Average score those looks must reach |
| `FACE_GALLERY` | `centroid` | `centroid` matches the average of a student's poses; `individual` is best-of-five and measurably less safe |
| `FACE_ENROLL_MODE` | `quick` | Enrollment type when the page does not choose: `quick` or `guided` (five poses) |
| `FACE_ENROLL_QUICK_STEPS` | `front,left,right` | Poses of a quick enrollment. `front` alone is fastest and measurably weaker, see "Quick enrollment" |
| `FACE_ENROLL_BURST_FRAMES` | `3` | Good frames in a row a pose is taken from; `1` keeps the first good frame |
| `FACE_ENROLL_DUPLICATE_SCORE` | `0.85` | An enrollment this similar to another enrolled person is refused; above `1` switches the check off |
| `FACE_LIVENESS` | `true` | Set `false` to turn the photo/screen check off |
| `FACE_LIVENESS_THRESHOLD` | `0.50` | Below this "real face" score a face is a photo or a screen |
| `FACE_LIVENESS_CONFIDENT` | `0.70` | From this score a face is live; in between it is "uncertain" and never counted. Not validated on your camera yet, see Anti-spoofing |
| `FACE_CHALLENGE` | `always` | Head-turn instruction before marking. `off` leaves the passive check alone, which is much weaker |
| `FACE_SCAN_LOG` | `true` | Write scanner decisions to `logs/recognition.log` |
| `FACE_TIMING_LOG` | `true` | Write how long each stage of every face request took to `logs/timing.log` (durations, sizes and outcomes only). `GET /face/timings` gives the median, p95 and p99 |
| `FACE_TF_THREADS` | `4` | Threads TensorFlow may use per operation. `0` is TensorFlow's default, which made one-face frames about twice as slow on the laptop this was measured on. Measure with `scripts/benchmark_latency.py --tf-threads N` |
| `FACE_DETECTOR` | `yolov8n` | DeepFace detector name |
| `FACE_MODEL` | `Facenet512` | Changing it requires enrolling everyone again |
| `FACE_NORMALIZATION` | `Facenet2018` | Input scaling for the model; changing it also requires enrolling again |

## Anti-spoofing: is a real person there, right now?

Two separate questions are asked of every face, and both must be answered before a record is written:
*who is this* (identity, above) and *is this a live person answering now* (below). Neither can stand
in for the other. A live person who is not the enrolled student stays "Unknown"; the enrolled
student's photo fails the second question.

**1. Passive check (MiniFASNet), on every face that is about to count.** Each face gets one of three
verdicts from its own score: `spoof` (below 0.50: what was collected for that face is wiped and the
student is paused for 3 seconds), `uncertain` (0.50 to 0.70: the frame counts for nothing, not as an
identity look and not as an answer to the challenge) and `live`. If the model cannot run, the frame
fails and nobody is marked. Enrollment stores a reference face only from `live` frames.

**2. Head-turn challenge, on the same tracked face.** Each student is given one direction per session,
drawn at random (left or right). The face must first hold still (for about half a second, roughly
facing the camera), then turn that way by at least 0.08 **from where it was**, within 10 seconds,
while it stays on the same track, keeps matching the same student and keeps looking live. Until
October 2026 the start had to be an absolute "straight" (turn under 0.04); the only real attempt
measured 0.17 to 0.24 the whole time (a student reading the screen beside the camera), so nobody could
be marked. Coming back towards the camera from an angled start is a new start, not a wrong answer.

- A still picture, printed or on a screen, cannot do this at all.
- Tilting a flat picture shifts the eyes a little like a turn does, so a "turn" only counts if the
  face box keeps its shape (within 10%). A tilted picture's box gets narrower.
- Turning the wrong way is a failed challenge: the collected looks are wiped, and after 3 failures the
  student is locked for 2 minutes on every camera ("mark by hand").
- The direction is fixed per student and session, so walking to another camera or coming back later
  does not get a second draw.
- Every face has its own instruction and its own answer. One student's turn, or one student's
  liveness verdict, does nothing for anyone else in the frame.

What was measured (no real camera was available for this work, see "not verified" below):

- The MiniFASNet code is the same computation as DeepFace's reference: on 300 faces the class agreed
  300/300 and the scores differed by at most 0.000002.
- The passive model alone is **not** enough. Given 300 ordinary image files of faces, it called 91%
  of them real. In `benchmark_multiface.py`, with the challenge switched off, 16 of 100 still photos
  pasted into frames were marked present. With the challenge on (the default), 0 of 44 were.
- Tilted flat photos (simulated tilts of 20 to 70 degrees at three distances, 4,895 trials): eye
  shift alone would have accepted 30.0% of them as a turn; the rule in use (shift of at least 0.08
  and box shape within 10%) accepts 0.4%, 3.7% in the worst case (30 degrees, very close to the lens).
  Of 850 photos of people whose heads really are turned, 93.1% keep the box shape within 10%.

What the challenge does **not** stop:

- A video in which the person happens to turn the right way at the right moment. With one direction
  out of two, an attacker with a single clip has an even chance; one who can pick between prepared
  clips while watching the instruction can answer it. The passive check is then the only barrier, and
  its strength against screens in your room is unmeasured.
- A camera feed that is replaced before it reaches the server (a virtual camera, or images posted
  straight to the API). Posting frames now takes a logged-in account, and the record is signed with
  it (`marked_by`), but the server still cannot tell such frames from a camera.
- 3D masks and real-time face-swap video.

So: printed photos and photos on phones are stopped by design. Prerecorded video and replayed feeds
are made harder, not impossible. A person should supervise the scanner when it matters.

### Measuring the liveness check with your camera

This is the part only you can do, and the thresholds above are provisional until it is done. With
people who have agreed to take part:

```powershell
cd backend
.venv\Scripts\python scripts\liveness_camera_test.py record live   --note "Arun, classroom light"
.venv\Scripts\python scripts\liveness_camera_test.py record print  --note "A4 colour print"
.venv\Scripts\python scripts\liveness_camera_test.py record screen --note "phone, full brightness"
.venv\Scripts\python scripts\liveness_camera_test.py record video  --note "phone video, head moving"
.venv\Scripts\python scripts\liveness_camera_test.py report
```

Record at least three runs of each kind with different people, prints and devices. Only scores are
written (`backend/logs/liveness_test.csv`); no picture is saved and nothing leaves the computer. The
report shows, per kind of attack, the share of frames the passive check accepted, and what other
values of `FACE_LIVENESS_CONFIDENT` would have done. Set that value from the report.

Then test the whole thing in the scanner, and count the outcomes:

| Attempt | Must happen |
| --- | --- |
| Real enrolled student follows the instruction | Blue box, then green, one record |
| Printed photo of an enrolled student | Never green, no record |
| Photo of an enrolled student on a phone or tablet | Never green, no record |
| Video of an enrolled student on a screen (try one where they turn their head) | No record. If one gets through, note the liveness scores in `logs/recognition.log` and raise `FACE_LIVENESS_CONFIDENT` |
| A different person follows the instruction | Stays "Unknown", no record |
| Student turns the wrong way three times | "Locked, mark by hand" for 2 minutes |
| Two students, only one follows the instruction | Only that one is marked |

## Accuracy and limits

No face recognition system is 100% accurate. These are measurements, not guarantees, and they come
from a public photo dataset (LFW: press photos of public figures), not from your students or camera.

`python scripts/evaluate_recognition.py eval_data/lfw/lfw_funneled` with the default settings,
158 people enrolled from 5 photos each, 1379 other photos of them, 500 people who are not enrolled:

- One frame: an enrolled face is named correctly 99.27% of the time, as another enrolled person 0.00%,
  left unknown 0.73%. A person who is not enrolled is given somebody's name on 7.40% of single frames,
  which is why one frame is never enough to mark.
- Marking decision, class of 30, someone who is not in the class standing in front of the camera:
  marked present in 0.38% of attempts when the three looks are different photos and 0.37% when they
  are the same photo (video frames are nearly the same). A class member is marked in 96.1% / 93.5% of
  attempts and never as someone else. With the previous setting (0.70) the figures were 0.54% / 0.74%
  and 97.8% / 96.9%. Section 5 of the report lists the other settings.
- Best-of-five matching (`FACE_GALLERY=individual`) names 11.20% of unknown faces on a single frame
  instead of 7.40%, and recognizes no more enrolled faces.

`python scripts/benchmark_multiface.py eval_data/lfw/lfw_funneled` (the real scanner code on frames
with several pasted photos, Intel Core 5 120U, no GPU, 960x540 frames):

| Faces in frame | Found | Named correctly | Named as someone else | Time per frame (median) |
| --- | --- | --- | --- | --- |
| 1 | 6/6 | 6/6 | 0 | about 0.4 s |
| 2 | 12/12 | 12/12 | 0 | about 0.3 s |
| 5 | 30/30 | 30/30 | 0 | about 0.6 s |
| 10 | 60/60 | 60/60 | 0 | about 0.55 s |
| 10 (7 enrolled, 3 strangers) | 60/60 | 42/42 | 0, and 0/18 strangers named or marked | about 0.55 s |

So roughly two frames per second, and a student has to stay in view for about two seconds to be marked.

What has not been verified, because it needs real people in front of a real camera:

- Accuracy on your own students, cameras and rooms, including siblings and look-alikes.
- Ten real people in one frame: movement, people partly hidden behind each other, faces turned away.
- Anything about spoofing with a physical print, phone, tablet or video in front of a real camera,
  and how often real faces are called "uncertain" in your lighting. See "Anti-spoofing" for the
  procedure and the tool.
- The head-turn challenge with real people: how easily students follow it, and how often a natural
  glance the wrong way fails it.
- Covered faces. Sunglasses are refused at enrollment by a simple darkness check; masks and hands are
  not detected as such (the detector's landmark confidences were tested for this and do not respond to them).

Other limits:

- Identical twins and very similar faces cannot be told apart reliably by any face model. The system
  answers "Unable to verify identity" when it can see the conflict, but twins should be marked by hand.
- Logging in is real (see "Logging in and accounts"), but the rest of what an open network needs is
  not done: the frontend is still the development server with a self-signed certificate, the
  backend accepts browsers from any private-network address, there are no security headers, and
  port 8000 is reachable directly. Use it on a trusted network only.
- The models run on the CPU, one frame at a time. More than four scanner frames waiting are answered
  "busy" and skipped (and shown as skipped) instead of queued.

### Checking it with a camera

1. Enroll at least three people. Try to enroll one of them a second time under another student's name:
   it must be refused.
2. Start a session and let one enrolled person stand in view: amber "Verifying 1/3, 2/3", then green.
3. A person who is not enrolled stands in view for 30 seconds: must stay red "Unknown", no record.
4. An enrolled student holds up a phone showing a classmate's photo: must be refused, no record.
5. A student from another batch stands in: must stay "Unknown" in this session.
6. Two, then five, then as many people as fit: every face keeps its own box and name while people move
   and swap places; each is marked once.
7. Check Reports: one record per student. Then look at `backend/logs/recognition.log` for any face that
   was marked wrongly or refused wrongly; the scores there say which setting was too loose or too strict.

Count the results (how many of how many) before trusting the system with a real class.

## Quick enrollment: what was measured

`python scripts/compare_enrollment.py eval_data/lfw/lfw_funneled` times an enrollment with the real
models and compares recognition for different numbers of enrollment captures on the same probes.

**Time.** Model and image work for one frame that is kept, on an Intel Core 5 120U without a GPU:
detector 45–210 ms, liveness 80–300 ms, FaceNet512 140–380 ms, everything else under 10 ms. The spread
is the machine being idle or busy with other programs; the same script gave 0.28 s and 0.76 s per
frame through the enrollment endpoint on the same day.

| Flow | Frames | Least possible time, idle machine | Same, busy machine |
| --- | --- | --- | --- |
| Five poses, as it was (2.5 s pause before every pose) | 15 | 20.4 s | 28.0 s |
| Five poses, now | 15 | 10.4 s | 18.0 s |
| Quick: front, left, right | 9 | 6.0 s | 10.5 s |
| Quick with `FACE_ENROLL_QUICK_STEPS=front` | 3 | 1.6 s | 3.1 s |

"Least possible" means every frame is good at the first try and the student needs no time to turn or
move; the network and the camera starting are not included. Enrollment with a real person was not
timed, and will be longer, most of all for the close and far poses, where the student has to move.

Where the time went, and what changed:

- Half of the old floor was the browser waiting 2.5 s before every pose. The first pose now starts
  as soon as the camera delivers a picture and later poses wait 1.2 s.
- The embedding model, the most expensive step, ran on every frame and its result was thrown away
  for every refused frame. It now runs only on frames that pass the cheap checks: a refused frame
  costs about 50–220 ms instead of 190–510 ms, so "move closer" style feedback comes back faster.
- A picture sent twice within 0.2 s is answered from the clock alone, without running any model.
- The models were already loaded once at startup and reused; that was not a cost.

**Recognition.** 158 people, 1379 probe photos of them, 500 photos of people who are not enrolled,
default thresholds. "Marked" is the attendance decision for a class of 30, for three different photos
and for the same photo three times.

| Enrollment | One frame named right | Class member marked (FRR is the rest) | Non-member marked (FAR) |
| --- | --- | --- | --- |
| 1 photo, the most frontal and sharpest | 92.39% | 66.8% / 65.5% | 0.34% / 0.37% |
| The same, averaged over a 3-frame burst | 92.02% | 67.2% / 66.1% | 0.36% / 0.39% |
| The same view at 3 sizes (as close and far are) | 92.46% | 67.3% / 66.1% | 0.35% / 0.37% |
| 2 photos: frontal and the most turned | 96.23% | 87.4% / 83.9% | 0.42% / 0.44% |
| 3 photos: frontal, left, right | 98.91% | 93.2% / 90.5% | 0.37% / 0.43% |
| 5 photos | 99.27% | 96.1% / 93.5% | 0.38% / 0.37% |

What this says:

- One frontal capture is not enough at these thresholds. It does not let more wrong people in, but a
  real student would fail to be marked in about one attempt in three, and 0.3% of single frames were
  named as another enrolled person (0% with three or more).
- More frames of the same moment do not help. A burst is worth having to pick a sharp frame and to
  check that the face is steady and the same; it is not a second capture.
- Close and far add nothing that the frontal view does not already give. Different views do.
- Front, left and right recover most of the gap, which is why they are the quick flow. The two head
  turns are also the part of enrollment a still picture cannot do.

How far to trust it: the photos of one person in this dataset were taken on different days, so five of
them say more than five poses from one minute, and one of them says less than one frame that passed
the enrollment checks. The real difference between quick and full enrollment is therefore probably
smaller than 93% against 96%, but that has not been measured on students with your camera. Until it
has, keep the full enrollment available and compare: enroll some students each way and see in
`logs/recognition.log` how their scores and "Verifying" times differ.

## Database, backups and upgrades

- The app uses the local SQLite file `backend/vernex_attendance.db` unless `DATABASE_URL` is set. A relative
  SQLite path is the `backend` folder's, wherever the process starts. The backend refuses to start on a
  SQLite file that does not exist or has no login account (a wrong `DATABASE_URL`), instead of opening
  an empty database; `create_super_admin.py` makes a new one with its first account.
- **PostgreSQL / Supabase (since October 2026).** The backend no longer creates or changes anything
  when it starts on PostgreSQL. It checks, with reads only, that every table and column it needs is
  there, that the duplicate-attendance index exists, that row level security is on for every table,
  and that its own account is not shut out by it; if not, it refuses to start and names what is
  missing. The schema comes from `backend/migrations`: `full_schema.sql` for a new, empty database,
  otherwise the numbered files the database does not have yet, in order. `DATABASE_AUTO_UPGRADE=true`
  (or `python scripts/init_db.py` once) brings back the old behaviour of changing the schema at every
  start, which needs an account that owns the tables. `python scripts/check_database.py` prints the
  same check plus which rights the account has, in a read-only transaction, without the address, the
  user or the password.
- `008_row_level_security.sql` switches row level security on for **every** table. Supabase gives its
  public `anon` role rights on the tables of the `public` schema; a table without row level security
  could be read and changed by anyone with the project's URL and its public key: students, phone
  numbers, attendance, face vectors. Shown on PostgreSQL 16 with those grants in `tests/test_postgres.py`.
- `003_course_batch_attendance_restructure.sql` failed on PostgreSQL ("invalid reference to
  FROM-clause entry for table r") until October 2026; it now runs, and all of 001 to 008 run in order
  and a second time.
- Attendance times (`marked_time`) are the school's clock (`DEFAULT_TIMEZONE`). On a PostgreSQL server
  set to UTC, as Supabase is, they were stored 5.5 hours early until October 2026; SQLite was right.
- `009_app_role.sql` creates `vernex_app`, the account the backend should use: it reads and writes rows
  through a row level security policy of its own, cannot create, change or drop anything, and may only
  add to the audit log. Supabase's public roles still get nothing. Connections to a remote PostgreSQL
  server are always encrypted. Backups and restore: `docs/RUNBOOK.md` (tested with PostgreSQL 17.6).
- `tests/test_postgres.py` runs the schema files, the start-up check, row level security, the
  `vernex_app` account, concurrent marking, the issue row lock and the console over HTTP (as the owner
  and as `vernex_app`) on a real PostgreSQL; checked on 16.2 and on 17.6, Supabase's version. It runs only when
  `VERNEX_TEST_POSTGRES_URL` points to a server on this computer (it creates and drops its own
  databases, and refuses any other host); otherwise it is skipped.
- Back it up before any upgrade by copying that file while the backend is stopped. Copies made during
  this work are in `backend/backups/`. To go back, stop the backend and copy a backup over the file.
- **Attendance codes (migration 010).** On PostgreSQL apply `backend/migrations/010_attendance_codes.sql`
  (a nullable `attendance_code` column on `user_management` and the unique index
  `uq_user_management_attendance_code`; it changes no row), then give existing people a code:
  `python scripts/backfill_attendance_codes.py --dry-run`, then without `--dry-run`. The script refuses
  to run before 010 is in place, never changes a code someone already has, can be run again, and prints
  counts only. Until 010 is applied the backend refuses to start and names it.
- On start (SQLite, or PostgreSQL with `DATABASE_AUTO_UPGRADE=true`) the backend adds what a newer
  version needs (the `capture_meta` column on `face_embeddings`, a unique index on attendance
  records, and the `attendance_code` column with its unique index, after which everyone without a code
  gets one) and changes no other existing row. If the index cannot be created
  because duplicate records already exist, it says so at startup and leaves the records alone.
  `backend/migrations/004_capture_meta_and_unique_attendance.sql` is the same change as SQL for PostgreSQL.
- Bulk upload, the contact-number rule and the editing fixes add no table and no column, and change
  no existing row. Numbers saved before the rule existed stay as they are until someone edits them.
- Logins add two tables, `admin_accounts` and `admin_sessions`, created on start like the others.
  No existing table or row is changed and no account is created: the tables start empty. On
  PostgreSQL the start also switches row level security on for both, with no policy, so they cannot
  be read through Supabase's REST API. `backend/migrations/005_admin_accounts.sql` is the same
  change as SQL, and `backend/migrations/full_schema.sql` includes it. These have been run on
  SQLite only; see "Tests".
- The Super Admin portal adds one table, `audit_logs`, created on start in the same way, empty, with
  row level security switched on on PostgreSQL. `backend/migrations/006_audit_logs.sql` is the same
  change as SQL (it needs 005 first), and `full_schema.sql` includes it. Run on SQLite only so far.
- Temporary passwords that run out add one column, `admin_accounts.temporary_password_expires_at`.
  On start it is added to an existing table, empty for every account, and nothing else changes:
  a password given out before this existed keeps working until it is changed. `005_admin_accounts.sql`
  adds it too (`ADD COLUMN IF NOT EXISTS`), and `full_schema.sql` has it.
- Accounts that are or have been a super admin add one more column, `admin_accounts.has_been_super_admin`
  (true or false, false by default). On start it is added to an existing table, and every account that
  is a super admin at that moment is marked; that marking runs on every start and only ever sets the
  flag, so it changes nothing more the second time. No other value is touched. `005_admin_accounts.sql`
  does the same (`ADD COLUMN IF NOT EXISTS`, then the one `UPDATE` that marks the super admins), and
  `full_schema.sql` has the column.
- Reporting a problem adds two tables, `issues` and `issue_comments`, created on start in the same
  way and empty. No existing table or row is changed. The database itself refuses a category, a
  severity or a status outside the lists, and a resolved issue without a resolution note (`CHECK`
  constraints). An account that reported an issue or wrote a comment cannot be deleted while those
  stay (`ON DELETE RESTRICT`): accounts are disabled, never deleted. Deleting an issue by hand takes
  its comments with it; deleting an account that has issues assigned to it leaves them unassigned.
  On PostgreSQL the start switches row level security on for both tables, with no policy.
  `backend/migrations/007_issues.sql` is the same change as SQL (it needs 005 first), and
  `full_schema.sql` includes it. Checked on a local PostgreSQL 16 (`tests/test_postgres.py`), not yet
  on Supabase. On PostgreSQL the backend no longer creates them itself: apply 007 (and 008).
- Logins need two more Python packages, `argon2-cffi` and `pyjwt` (both in
  `backend/requirements.txt`), and a `JWT_SECRET` in `backend/.env`. In an installation made
  before they were added:

  ```powershell
  cd backend
  .venv\Scripts\python -m pip install -r requirements.txt
  .venv\Scripts\python scripts\create_jwt_secret.py
  .venv\Scripts\python scripts\create_super_admin.py
  ```
- Bulk upload needs one more Python package, `openpyxl`, to read and write `.xlsx` files (and the
  tests need `httpx2`). Both are in `backend/requirements.txt`. In an installation made before
  they were added, install them once:

  ```powershell
  cd backend
  .venv\Scripts\python -m pip install -r requirements.txt
  ```

  Until then the backend still starts and everything else works; an `.xlsx` upload or template is
  answered with a message saying what is missing, and `.csv` files are accepted as usual.

## Tests

```powershell
cd backend
.venv\Scripts\python -m pytest
```

The tests replace the camera and the models with known faces, so they prove the decision logic
(who is marked, who is not, that faces do not affect each other, that records are never doubled).
They do not measure how well real people are told apart; the two scripts above and the camera
checklist are for that.

Bulk upload, the contact-number rule and the editing of courses, batches and people are tested
through the real routes, each test on its own empty in-memory SQLite database: files are uploaded
as a browser uploads them, and what was saved is read back from the database. They have not been
run against PostgreSQL.

Logins are tested the same way, through the real routes: the right and the wrong password, an
unknown email, the lockout, a disabled account, an expired and a forged token, renewing and logging
out, and changing the password. One test walks every route the application has and requires `401`
without a login for all but the four public ones, so a route added later is covered without a new
test. The tests set their own database and signing secret: whatever `backend/.env` says, no test
connects to it. What they cannot show is PostgreSQL itself: that the two tables are created there
and that row level security is on has to be checked on the real database.

The Super Admin portal is tested the same way (`tests/test_super_admin.py`): each account action and
its refusals, that a new admin logs in with the temporary password, must change it and then gets the
console, that disabling and resetting end logins at once, exactly one audit entry for each recorded
action and none with a secret in it, the audit log's filters and pages, and the dashboard's numbers.
The walk over every route also requires `403` for an admin on every portal route. Two super admins
removing each other at the same moment is tested on a SQLite file with real connections; on
PostgreSQL the same guard uses row locks, which have not been run there.

Reporting a problem is tested the same way. `tests/test_issues_schema.py`: the two tables and their
columns, the values and the missing note the database itself refuses, and that the SQL files describe
the same tables with row level security on. `tests/test_issues_api.py`: the reporter's side, with
the limits of every field at their edges, the page and the device, refusals that repeat nothing that
was typed, `<script>` and HTML kept as typed, comments, and an admin asking for or commenting on
someone else's issue (`404`, the same as for a number that does not exist). `tests/test_issue_inbox.py`:
the inbox's filters, sorting and pages, every change of status and what it does to the resolution
time and note, assigning, the badge's count, the dashboard's numbers with the week turning at
midnight between Sunday and Monday, and that a report or a change of status whose audit entry cannot
be written is not saved either. Two requests on one issue at the same moment (two changes of status,
or a comment and a close) are tested on a SQLite file with real connections: the second waits for the
first and decides on what it saved. On PostgreSQL the same is done with a row lock
(`SELECT ... FOR UPDATE`), which has not been run there.

Staff and member enrollment, session scopes and QR attendance are tested the same way:
`tests/test_face_routes.py` (who face enrollment lists), `tests/test_session_scopes.py` (starting each kind
of session, who belongs, the face gallery of each scope and an empty one without a scope),
`tests/test_attendance_codes.py` (the code's format and normalisation, codes on create and import,
collisions retried against the unique index, replacing a code and its audit entry, who may do it, the
SQLite upgrade and the backfill script) and `tests/test_code_marking.py` (every answer of
`/attendance/code/mark`: marked, late, already marked, out of scope, inactive, unknown, not a code,
stopped or old session, the audit rule, the rate limit, no code in answers or logs).
`tests/test_postgres.py` checks migration 010 and the backfill on PostgreSQL; it runs in CI, or locally
with `VERNEX_TEST_POSTGRES_URL`. Camera scanning, printing, PNG downloads and the pages themselves are
not covered by tests: see the manual checks in `docs/RUNBOOK.md`.

```powershell
cd frontend
npm test
```

This runs the frontend's rules with Node's own test runner (nothing extra to install): the
contact-number check, what the Courses and Batches forms do when a record is opened, changed,
cancelled and saved, what the upload dialog makes of the backend's answer, and the session (logging
in, renewing the token, being sent back to the login page, which page each role may open), and the
portal's rules (who reaches its pages, what each account screen offers, how long a temporary password
is held, the audit log's filters and pages), and issue reporting (the report form's limits, which
are read from the backend's code so that the two cannot differ, what is attached about the page and
the device, the status form, the inbox's filters and the address of one issue). Two lists are shared
with the backend's tests so that the two sides cannot drift apart: `backend/tests/data/phone_cases.json`
(numbers and what must become of them) and `backend/tests/data/import_columns.json` (the column names).
The screens themselves are not covered by automated tests.