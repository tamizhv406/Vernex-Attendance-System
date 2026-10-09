@echo off
title Vernex Frontend (port 5173)
cd /d "%~dp0frontend"
if not exist node_modules (
  echo Run setup.bat first.
  pause & exit /b 1
)
call npm run dev:https
pause
