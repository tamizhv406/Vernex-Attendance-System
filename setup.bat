@echo off
setlocal
cd /d "%~dp0"
echo === Vernex Smart Attendance - one-time setup ===
echo.

set "PY="
py -3.10 --version >nul 2>&1 && set "PY=py -3.10"
if not defined PY (
  python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [ERROR] Python not found. Install Python 3.10 from https://www.python.org/downloads/release/python-31011/
  echo         and tick "Add python.exe to PATH" during install.
  pause & exit /b 1
)
echo Using: %PY%
%PY% --version

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

echo.
echo [3/3] Installing frontend packages...
pushd frontend
call npm install || (popd & echo [ERROR] npm install failed & pause & exit /b 1)
popd

echo.
echo === Setup complete. Now double-click start.bat ===
pause
