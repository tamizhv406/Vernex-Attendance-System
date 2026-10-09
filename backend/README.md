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
FRONTEND_ORIGIN=http://localhost:5173
FACE_MATCH_THRESHOLD=0.60
GOOGLE_SCRIPT_URL=
DEFAULT_TIMEZONE=Asia/Kolkata
```

If `DATABASE_URL` is missing, the app falls back to local SQLite for quick testing.

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

Option 2: Use SQLAlchemy:

```powershell
python scripts/init_db.py
```

## Test Supabase Connection

```powershell
python scripts/test_supabase_connection.py
```

## Run

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Docs:

```text
http://localhost:8000/docs
```

Health:

```text
http://localhost:8000/health
```

## Main APIs

- `GET /`
- `GET /health`
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
- `POST /attendance/mark`
- `POST /face/enrollment/start/{person_id}`
- `POST /face/enrollment/frame`
- `POST /face/enrollment/complete/{person_id}`
- `GET /face/enrollment/status/{person_id}`
- `POST /face/recognize`
- `POST /sheet/sync-pending`
- `GET /sheet/status`

The face endpoints run DeepFace (YOLOv8 detector + Facenet512). See the root `README.md` for the full run guide, workflow and face settings.
