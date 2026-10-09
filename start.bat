@echo off
cd /d "%~dp0"
start "Vernex Backend" cmd /k start-backend.bat
start "Vernex Frontend" cmd /k start-frontend.bat
echo Two windows opened: backend and frontend.
echo Open the "Phone scanner" link shown in the frontend window.
timeout /t 5 >nul
