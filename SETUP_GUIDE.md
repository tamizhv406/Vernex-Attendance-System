# Vernex Smart Attendance — Setup Guide

Face-recognition attendance system. A phone camera streams video to your PC, which recognizes enrolled
students and marks attendance. This guide is for Windows 10/11.

---

## 1. Install the prerequisites (one time)

| Tool | Version | Download |
| --- | --- | --- |
| Python | **3.10** (3.10.11 recommended) | https://www.python.org/downloads/release/python-31011/ → "Windows installer (64-bit)" |
| Node.js | 20 or newer (LTS) | https://nodejs.org |

When installing Python, **tick "Add python.exe to PATH"** on the first screen.

Check both in a new PowerShell or Command Prompt window:

```powershell
py -3.10 --version   # or: python --version   → Python 3.10.x
node --version       # v20 or higher
```

> Use Python 3.10. Newer versions (3.13+) may fail to install TensorFlow, which the face models need.

You also need about **3 GB of free disk space** and an internet connection for the first setup.

---

## 2. Unzip

Unzip `Vernex-Attendance-System.zip` somewhere simple, e.g. `D:\Vernex-Attendance-System`.
Avoid very long paths or folders inside OneDrive.

---

## 3. Setup (one time)

**Easy way:** double-click **`setup.bat`** in the folder. It will:

1. create a Python virtual environment in `backend\.venv`
2. install the Python packages (large download, 5–15 minutes)
3. create `backend\.env` from `backend\.env.example`, and write a random `JWT_SECRET` into it
   (the secret that signs logins; it is not shown and must never be shared or committed)
4. run `npm install` in `frontend`

Wait for `=== Setup complete ===`. Then create the first login: see "First login" below.

**Manual way** (same thing, in PowerShell, from the project folder):

```powershell
cd backend
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
python scripts\create_jwt_secret.py
cd ..\frontend
npm install
```

> If PowerShell says "running scripts is disabled", run this once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use the `.bat` files instead.

### Database

By default the app uses a **local SQLite file** (`backend\vernex_attendance.db`). Nothing to configure.
The file is made by `create_super_admin.py` together with the first super admin. The backend itself never
makes an empty one: if the file in `DATABASE_URL` does not exist, or has no login account, it refuses to
start and names the file it looked for. A relative SQLite path is the `backend` folder's, wherever the
backend or a script is started from.

To use a Supabase PostgreSQL database instead, open `backend\.env` and uncomment/fill `DATABASE_URL`
(Supabase → Connect → Transaction pooler). In the password write `@` as `%40` and `%` as `%25`.
Test it with:

```powershell
cd backend
.\.venv\Scripts\python scripts\test_supabase_connection.py
```

With SQLite the tables are created automatically on first start. With PostgreSQL the backend creates
and changes nothing: first run `backend\migrations\full_schema.sql` in Supabase's SQL editor (a new,
empty database) or the numbered files it does not have yet, up to `010_attendance_codes.sql`. A database
from before attendance codes then needs `backend\scripts\backfill_attendance_codes.py` once (see
`docs/RUNBOOK.md`, Database). Then check, without changing anything and without showing any secret:

```powershell
cd backend
.venv\Scripts\python scripts\check_database.py
```

It says whether the connection works, whether every table, column, index and row level security
setting is in place, and which rights the backend's account has. The backend refuses to start, and
says what is missing, when the schema is not ready.

### First login

There is no default account and no default password. After the database is chosen, create the
first super admin on this PC:

```powershell
cd backend
.\.venv\Scripts\python scripts\create_super_admin.py
```

It shows which database it writes to and asks for an email, a name and a password (at least 10
characters; typed hidden, twice). Log in to the app with that email and password.

- Run it again and it changes nothing: a super admin exists.
- `--force` with a new email adds another super admin.
- `--force` with the email of an existing super admin asks you to type the email again, then
  replaces the password, unlocks the account and logs it out everywhere. Use this for a forgotten
  password. It does the same for an admin that used to be a super admin (it stays an admin): the
  Super Admin portal never resets the password of an account that is or has been a super admin.

If you switch `backend\.env` to another database later, run the script again: accounts live in
the database.

Accounts for the other people who use the app are added in the app itself: log in as the super
admin, open **Admins** in the Super Admin portal and press **Add admin**. Each new account gets a
temporary password, shown once, which the person replaces when they first log in.

---

## 4. Run it (every time)

**Easy way:** double-click **`start.bat`**. It opens two windows, *Vernex Backend* and *Vernex Frontend*.
Keep both open while using the app.

**Manual way** — two terminals:

```powershell
# Terminal 1 — backend
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```powershell
# Terminal 2 — frontend
cd frontend
npm run dev:https
```

In the backend window, wait for **`face models ready`** (about 30 s; the very first start also
downloads ~100 MB of model weights). http://localhost:8000/health in a browser shows
`"status":"starting"` until then and `"status":"ok"` after.

The frontend window prints links like:

```
  Admin network:  https://192.168.1.11:5173/
  Phone scanner:  https://192.168.1.11:5173/attendance-scanner
```

- On the PC: open **https://localhost:5173**
- On the phone: use the link that starts with your **Wi-Fi IP address**

To stop: close both windows (or press `Ctrl+C` in each).

---

## 5. Connect the phone

1. PC and phone must be on the **same Wi-Fi**.
2. On the phone open `https://<PC Wi-Fi IP>:5173/attendance-scanner`.
3. The certificate is self-signed, so the browser warns — tap **Advanced → Proceed**.
4. Log in with your email and password, then **allow camera access**.

The first time, Windows may ask whether Node.js may use the network — click **Allow** (tick Private networks).

---

## 6. Using the app

1. **Courses → Batches → Students** — create a course, a batch under it, then students.
   To add many at once, press **Upload** on any of these pages (and on Staff and Members), download
   the template, fill it in and upload it. Excel (`.xlsx`) and CSV files are accepted; rows with a
   problem are listed with their row number and the rest are imported. Details are in `README.md`.
2. **Face Enrollment** — choose Students, Staff or Members. For a student pick course, batch and
   student; staff and members need no course or batch (search by name or ID). Tick the consent box,
   press *Start Enrollment*, and follow the guided shots. Turn the head about 15° for left/right.
3. **Attendance Scanner** — choose Batch class (then course and batch), Staff or Members, press
   *Start Session*, point the camera at the people.
   Green box = recognized, red box = unknown or "Photo detected".
4. A student is marked after being matched in 3 frames within 10 seconds (`present`, or `late` after the grace time).
5. **Stop Session**, then open **Reports** (the **Who** filter shows staff and member records).
6. **QR cards and QR Attendance** — every person has a QR card on their People page (**QR**: download,
   print, replace a lost card; **Print QR cards** prints the filtered list, 10 per A4 page). On
   **QR Attendance**, start or join a session and scan cards with the phone's camera, or type a code.
   The camera needs the **https://** link.
7. Something not working? **Report a problem** — in the top bar on a computer, under **More** on a
   phone (the scanner page included). Give it a title, a category, a severity and what happened; the
   page you were on and your browser, system and screen size are sent with it. Follow it, and answer,
   in **My reports**. Super admins see every report in the Super Admin portal under **Issues**, where
   they reply, change its status and resolve it with a note you can read.

More detail (recognition settings, accuracy, issue reporting) is in `README.md`.

---

## 7. Troubleshooting

| Problem | Fix |
| --- | --- |
| `setup.bat` says Python not found | Reinstall Python 3.10 with "Add to PATH" ticked, then open a new window |
| `setup.bat` says `backend\.venv` is not a working Python 3.10 environment | It was made with another Python and is never reused. Rename it (e.g. to `.venv-old`) and run `setup.bat` again. `setup.bat /check` only checks, and changes nothing |
| `pip install` fails on tensorflow / deepface | You're probably on the wrong Python version — install 3.10, delete `backend\.venv`, run `setup.bat` again |
| Backend stuck before `face models ready` | First start is downloading models; wait, and check the internet connection |
| `Address already in use` / port 8000 or 5173 busy | Another copy is running — close it, or restart the PC |
| Phone can't open the page | Same Wi-Fi? Allow Node.js through Windows Firewall (Windows Security → Firewall → Allow an app). Don't use a guest/hotspot network that isolates devices |
| Camera doesn't start on phone | Use the **https://** link, accept the certificate, allow camera permission in browser settings |
| Frontend shows network/API errors | The backend window must be running and show `face models ready` |
| Face always "Unknown" | Re-enroll in good light, face fully visible, follow all five shots |
| The page is blank or says a module (`qrcode`, `jsqr`) is missing after an update | The frontend was updated with new packages: `cd frontend`, then `npm install`, and start it again |
| Backend refuses to start: `user_management has no ... attendance_code` / `migration 010` | Apply `backend\migrations\010_attendance_codes.sql` in Supabase's SQL editor, then run `backend\scripts\backfill_attendance_codes.py` (see `docs/RUNBOOK.md`) |
| A QR card is refused with "No one has this code" | The code was replaced (a newer card exists) or the card is not from this system: open the person's **QR** and print the current card |
| Upload says Excel files need `openpyxl` | The backend was updated without its new package. Run `setup.bat` again (or `backend\.venv\Scripts\python -m pip install -r backend\requirements.txt`), then restart the backend. CSV files work in the meantime |
| A contact number is refused | It must be 10 digits. Spaces, hyphens and `+91` in front are accepted; other country codes, letters and symbols are not |
| Backend stops with `JWT_SECRET is missing` | Run `backend\.venv\Scripts\python backend\scripts\create_jwt_secret.py`, then start the backend again |
| Backend says `No module named 'argon2'` or `'jwt'` | The backend was updated without its new packages. Run `setup.bat` again (or `backend\.venv\Scripts\python -m pip install -r backend\requirements.txt`) |
| Nobody can log in on a new installation | No account exists yet. Create the first super admin: see "First login" |
| "Too many failed attempts" | Five wrong passwords lock an email for 15 minutes. Wait, or reset the password with `create_super_admin.py --force` |
| "Too many login attempts from this device" | One device gets ten attempts a minute. Wait a minute |
| Logged out again after reloading the page | Open the app with the **https://** link (or `http://localhost:5173` on the PC itself). The login cookie only travels over HTTPS |
| Forgot the super admin password | `backend\.venv\Scripts\python backend\scripts\create_super_admin.py --force`, type that account's email, confirm it, choose a new password. The Super Admin portal cannot reset the password of an account that is or has been a super admin, only that of other admins |
| A report of mine says "Issue not found" | My reports opens only your own reports. A link to someone else's issue says "not found" on purpose |
| "This issue is closed, so it takes no more comments" | A closed issue takes no comments. Report a new problem, or ask a super admin to open the issue again |
| "This temporary password has expired" | A temporary password works for 72 hours. For an **admin** account, a super admin resets the password again in the portal (Admins) and passes on the new one. For an account that **is or has been a super admin**, the portal cannot reset it: on the server run `backend\.venv\Scripts\python backend\scripts\create_super_admin.py --force`, type that account's email twice, then choose a new password |

Run the tests (optional):

```powershell
cd backend
.\.venv\Scripts\python -m pytest
cd ..\frontend
npm test
```

> Security note: every page and every API route now needs a login, but the app is still served by
> the development server with a self-signed certificate. Only use it on a trusted network.
