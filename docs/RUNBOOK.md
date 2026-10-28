# Vernex runbook

One page for whoever keeps the system running. Commands are for Windows PowerShell, from the
repository folder.

## Start and stop

**Backend** (one process only: enrollments in progress and the scanner's tracking live in its memory):

```powershell
cd backend
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

On PostgreSQL it refuses to start, naming what is missing, if the schema is not ready (see Database).
Stop it with Ctrl+C. To restart it automatically after a crash or a reboot, run that command as a
Windows service (for example with NSSM: `nssm install Vernex <path>\backend\.venv\Scripts\python.exe
"-m uvicorn app.main:app --host 127.0.0.1 --port 8000"`, start directory `<path>\backend`).

**Console, in production**: build it, then serve it with Caddy over HTTPS (`deploy/Caddyfile`):

```powershell
cd frontend; npm run build; cd ..\deploy
$env:VERNEX_SITE = "vernex.example.org"     # your domain: Caddy gets a real certificate for it
caddy run --config Caddyfile --adapter caddyfile
```

Not the Vite development server: it is for development on a trusted network only.

## Is it up?

| Address | Answers |
| --- | --- |
| `/health/live` | `ok` while the backend process runs |
| `/health/ready` | `ok` when the database answers and the face models are loaded; 503 otherwise |
| `/health` | `ok`, `starting` (models loading, about 30 s after a start), `failed` (the models could not be loaded: the backend's output says why, for example a missing package or the wrong Python version) or `unavailable` (database) |

Point an uptime monitor at `https://<site>/api/health/ready`.

## Logs

- `backend/logs/recognition.log`: each change of the scanner's verdict for a face (numbers and ids,
  no images, no face vectors). Rotated at 2 MB, 3 kept.
- `backend/logs/timing.log`: how long each face request took. Rotated the same way.
- The backend's own output (errors with a reference such as `ab12cd34`, which the console shows to
  the user): wherever the service manager writes it.

## Database

- Check it, read-only and without showing any secret: `.venv\Scripts\python scripts\check_database.py`.
- New database: run `backend/migrations/full_schema.sql` in Supabase's SQL editor. Older database: the
  numbered files it does not have yet, in order (up to `010_attendance_codes.sql`).
- **Attendance codes** (once, after updating to the QR version). Back up first (see below). Then in
  Supabase's SQL editor, as `postgres`, run `backend/migrations/010_attendance_codes.sql`, and give
  everyone who existed before it a code:

  ```powershell
  cd backend
  $env:PYTHONUTF8="1"
  .venv\Scripts\python scripts\check_database.py                     # must say ready
  .venv\Scripts\python scripts\backfill_attendance_codes.py --dry-run # counts only, writes nothing
  .venv\Scripts\python scripts\backfill_attendance_codes.py
  ```

  The script refuses (exit 1) until 010's column and unique index exist, leaves codes that are already
  there alone, can be run again ("Nothing to do"), and prints counts only, never a code or a name.
  Exit 2 means nothing was written; run it again. New people get a code by themselves.
- The backend should connect as `vernex_app` (migration 009), not as `postgres`: in the SQL editor
  `ALTER ROLE vernex_app WITH LOGIN PASSWORD '<generated>'`, then in `backend/.env`
  `DATABASE_URL=postgresql://vernex_app.<project-ref>:<password>@<pooler host>:6543/postgres`. Run
  the check again: it must say "ready". Migrations keep running as `postgres`.

## Backups and restore

Supabase's free plan keeps no backups and pauses a project after a week without use. Upgrade to a
paid plan for production, or at least take a daily dump with PostgreSQL's own tools (version 17, to
match the server), using the owner account and the session pooler or direct connection:

```powershell
pg_dump --format=custom --file=vernex_YYYYMMDD.dump "<postgres URL of the owner>"
```

Restore into an empty database (a new Supabase project, or a local test server), then check it:

```powershell
pg_restore --dbname="<postgres URL of the empty database>" --exit-on-error vernex_YYYYMMDD.dump
.venv\Scripts\python scripts\check_database.py
```

Tested on 15 October 2026 on PostgreSQL 17.6: the restored copy had every row, the 14 row level
security settings and the 14 `vernex_app` policies, and passed the check connected as `vernex_app`.
Keep dumps somewhere other than the database's own provider, and treat them as personal data.

## QR cards and codes

- **Print cards**: Students, Staff or Members, filter the list, then **Print QR cards (N)**: the
  browser's print dialog, A4, scale 100% (or "Save as PDF"). 10 ID-size cards a page. Print one first
  and scan it from the paper with the QR Attendance page before printing a batch.
- **Lost or shared card**: that person's **QR**, then **Replace code**, then print the new card. The old
  card is refused at once ("No one has this code"). The Audit Log shows "Attendance code replaced".
- **QR Attendance needs HTTPS for the camera**: the `https://` address (Caddy in production,
  `npm run dev:https` in development). Without a camera, typing the code still works.
- Marks need the connection: a scan that shows amber was **not** saved and is not retried. Scan again.
- Treat printed cards like ID badges: whoever holds a card can mark its owner. Before going live, remove
  the demo accounts and demo people, and print cards only for real people.

## Rotate secrets

- **Database password** (`postgres`, and `vernex_app`): change it in Supabase (or with `ALTER ROLE`),
  update `DATABASE_URL` in `backend/.env`, restart the backend.
- **Supabase service-role key**: roll it in Supabase's API settings. This application does not use it.
- **JWT_SECRET**: `.venv\Scripts\python scripts\create_jwt_secret.py`, then restart. Every login ends;
  everyone logs in again.

## Accounts

- First super admin, or a new password for one: `.venv\Scripts\python scripts\create_super_admin.py`
  (`--force` for an account that exists). Admins are managed in the console's Super Admin portal.
- Consoles log themselves out after 30 minutes without a click or a key (a running scanner keeps
  them awake); a login not renewed for 30 minutes cannot be renewed (`AUTH_IDLE_MINUTES`).

## When the scanner says

| Message | What to do |
| --- | --- |
| Turn head to YOUR LEFT / RIGHT | The student holds still, then turns that way |
| Locked, mark by hand | Three wrong turns: mark the student by hand below the camera |
| This session is for (an earlier date) | Stop it and start a new session for today |
| The server is busy / Too many requests | Fewer frames are being checked; wait, or use fewer scanners per login |
| Camera permission denied | Allow the camera for the site in the browser, then Try again |
| Only staff can be marked in a staff session / Only members can be marked... / ... is not in this batch | The person is not in this session's scope: start the right kind of session, or check their batch |
| No one has this code. It may have been replaced by a newer one. | An old (replaced) or wrong card: open the person's QR and print the current card |
| ... is inactive. Attendance was not marked. | The person's status is inactive on their People page |
| This is not a Vernex attendance code / Not a Vernex attendance QR | Not one of our cards, or a mistyped code: 8 characters, `XXXX-XXXX` |
| Not marked. Check the connection and scan again. | No answer from the backend: nothing was saved. Fix the connection, scan again |

## Manual checks after an upgrade

The tests cover the backend's rules and the pages' logic, not the camera, the printer or the pages
themselves. On the running app (backend + HTTPS frontend), on a computer and on a phone:

1. Face Enrollment: Staff and Members list everyone without a course or batch, the search works, the
   consent text does not say "student", Start stays disabled until it is ticked. Enroll one staff member.
2. Live Scanner: a **Staff** session lists staff only and marks the enrolled staff member; a student in
   front of the camera is not marked. A batch class still marks only that batch.
3. People: every person has a code after the backfill; a person added by form and one by upload get one
   at once. QR, then **Download PNG** saves `<ID>-qr.png`; **Print card** prints one card.
4. **Print QR cards** with a batch filter: only that batch, 10 cards per A4 page, and the QR scans from paper.
5. **Replace code**: the code changes; the old printed card is refused on QR Attendance.
6. QR Attendance on a phone: scan a card (green, beep, vibration); again (blue "Already marked");
   another batch's card (red); a website's QR ("Not a Vernex attendance QR"); a typed lowercase code
   without the hyphen (marked); "Late after" in the past (late); staff and members sessions; deny the
   camera (typing still works); Wi-Fi off (amber, and nothing is marked later).
7. Start a face session on the computer, **Join running session** on the phone: both marks in one
   register, nobody twice. Stop it from the phone: the computer's scanner stops marking.
8. An inactive student's card says "is inactive". Reports show "QR scan" / "Code typed" and staff
   records under Who, Staff. Hand marks still appear in the Audit Log. Logged out, `/qr-attendance`
   goes to the login page.
