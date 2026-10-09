@echo off
title Vernex Backend (port 8000)
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  pause & exit /b 1
)
echo Starting backend... wait for "face models ready" ^(first start downloads ~100 MB of models^).
.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
