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
| `/health` | `ok`, `starting` (models loading, about 30 s after a start) or `unavailable` (database) |

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
  numbered files it does not have yet, in order (up to `009_app_role.sql`).
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
