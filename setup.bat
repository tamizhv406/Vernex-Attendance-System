@echo off
setlocal
cd /d "%~dp0"
echo === Vernex Smart Attendance - one-time setup ===
echo.

rem "setup.bat /check" only checks which Python would be used (and an existing backend\.venv), then stops.
set "CHECK_ONLY="
if /i "%~1"=="/check" set "CHECK_ONLY=1"

rem Only Python 3.10: TensorFlow and DeepFace cannot be installed on newer versions, and a backend
rem without them starts but can never check a face. Another version is never used instead.
set "PY="
call backend\scripts\check_python.bat py -3.10 && set "PY=py -3.10"
if not defined PY (
  call backend\scripts\check_python.bat python && set "PY=python"
)
if not defined PY (
  echo [ERROR] Python 3.10 was not found. This computer has:
  python --version 2>nul || echo         no python on PATH
  echo         Install Python 3.10 from https://www.python.org/downloads/release/python-31011/
  echo         ^(newer versions cannot install the face models^), then run setup.bat again.
  (if not defined CHECK_ONLY pause) & exit /b 1
)
echo Using: %PY%
%PY% --version

rem An environment made earlier with another Python is never reused: it would install, or start,
rem without the face models. It is not deleted either; whoever runs setup decides.
if exist backend\.venv (
  call backend\scripts\check_python.bat backend\.venv\Scripts\python.exe || (
    echo [ERROR] backend\.venv exists but is not a working Python 3.10 environment:
    backend\.venv\Scripts\python.exe --version 2>nul || echo         it has no working python.exe
    echo         Rename it ^(for example to .venv-old^) and run setup.bat again. Nothing was changed.
    (if not defined CHECK_ONLY pause) & exit /b 1
  )
)
if defined CHECK_ONLY (
  echo [OK] Python 3.10 found, and backend\.venv is missing or uses Python 3.10. Nothing was changed.
  exit /b 0
)

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js not found. Install Node.js 20 or newer ^(LTS^) from https://nodejs.org
  pause & exit /b 1
)

echo.
echo [1/3] Creating Python virtual environment...
if not exist backend\.venv (
  %PY% -m venv backend\.venv || (echo [ERROR] venv creation failed & pause & exit /b 1)
)

echo.
echo [2/3] Installing Python packages ^(large download, can take 5-15 minutes^)...
backend\.venv\Scripts\python -m pip install --upgrade pip
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt || (echo [ERROR] pip install failed & pause & exit /b 1)

if not exist backend\.env (
  copy backend\.env.example backend\.env >nul
  echo Created backend\.env ^(uses local SQLite database^)
)
rem The secret that signs login tokens: written into backend\.env if it is not there yet, never shown.
backend\.venv\Scripts\python backend\scripts\create_jwt_secret.py || (echo [ERROR] Could not write JWT_SECRET to backend\.env & pause & exit /b 1)

echo.
echo [3/3] Installing frontend packages...
pushd frontend
call npm install || (popd & echo [ERROR] npm install failed & pause & exit /b 1)
popd

echo.
echo === Setup complete. ===
echo Before the first login, create the first super admin ^(after choosing the database in backend\.env^):
echo     backend\.venv\Scripts\python backend\scripts\create_super_admin.py
echo Then double-click start.bat.
pause
