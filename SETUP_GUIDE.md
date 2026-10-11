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
3. create `backend\.env` from `backend\.env.example`
4. run `npm install` in `frontend`

Wait for `=== Setup complete ===`.

**Manual way** (same thing, in PowerShell, from the project folder):

```powershell
cd backend
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
cd ..\frontend
npm install
```

> If PowerShell says "running scripts is disabled", run this once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use the `.bat` files instead.

### Database

By default the app uses a **local SQLite file** (`backend\vernex_attendance.db`), created automatically.
Nothing to configure.

To use a Supabase PostgreSQL database instead, open `backend\.env` and uncomment/fill `DATABASE_URL`
(Supabase → Connect → Transaction pooler). In the password write `@` as `%40` and `%` as `%25`.
Test it with:

```powershell
cd backend
.\.venv\Scripts\python scripts\test_supabase_connection.py
```

Tables are created automatically on first start in either case.

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
downloads ~100 MB of model weights). Check http://localhost:8000/health in a browser.

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
4. Log in, then **allow camera access**.

The first time, Windows may ask whether Node.js may use the network — click **Allow** (tick Private networks).

---

## 6. Using the app

1. **Courses → Batches → Students** — create a course, a batch under it, then students.
   To add many at once, press **Upload** on any of these pages (and on Staff and Members), download
   the template, fill it in and upload it. Excel (`.xlsx`) and CSV files are accepted; rows with a
   problem are listed with their row number and the rest are imported. Details are in `README.md`.
2. **Face Enrollment** — pick course, batch and student, press *Start Enrollment*, and follow the five
   guided shots (front, left, right, close, far). Turn the head about 15° for left/right.
3. **Attendance Scanner** — pick course and batch, press *Start Session*, point the camera at the class.
   Green box = recognized, red box = unknown or "Photo detected".
4. A student is marked after being matched in 3 frames within 10 seconds (`present`, or `late` after the grace time).
5. **Stop Session**, then open **Reports**.

More detail (recognition settings, accuracy) is in `README.md`.

---

## 7. Troubleshooting

| Problem | Fix |
| --- | --- |
| `setup.bat` says Python not found | Reinstall Python 3.10 with "Add to PATH" ticked, then open a new window |
| `pip install` fails on tensorflow / deepface | You're probably on the wrong Python version — install 3.10, delete `backend\.venv`, run `setup.bat` again |
| Backend stuck before `face models ready` | First start is downloading models; wait, and check the internet connection |
| `Address already in use` / port 8000 or 5173 busy | Another copy is running — close it, or restart the PC |
| Phone can't open the page | Same Wi-Fi? Allow Node.js through Windows Firewall (Windows Security → Firewall → Allow an app). Don't use a guest/hotspot network that isolates devices |
| Camera doesn't start on phone | Use the **https://** link, accept the certificate, allow camera permission in browser settings |
| Frontend shows network/API errors | The backend window must be running and show `face models ready` |
| Face always "Unknown" | Re-enroll in good light, face fully visible, follow all five shots |
| Upload says Excel files need `openpyxl` | The backend was updated without its new package. Run `setup.bat` again (or `backend\.venv\Scripts\python -m pip install -r backend\requirements.txt`), then restart the backend. CSV files work in the meantime |
| A contact number is refused | It must be 10 digits. Spaces, hyphens and `+91` in front are accepted; other country codes, letters and symbols are not |

Run the tests (optional):

```powershell
cd backend
.\.venv\Scripts\python -m pytest
cd ..\frontend
npm test
```

> Security note: the login page does not check passwords and the API has no authentication.
> Only use it on a trusted network.
