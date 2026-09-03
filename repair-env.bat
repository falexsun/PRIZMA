@echo off
setlocal
REM Content Tracker - repair local .env and Postgres password without deleting data
REM Usage: repair-env.bat

echo === Content Tracker Environment Repair ===

where docker >nul 2>nul
if errorlevel 1 (
    echo [repair-env] Docker was not found. Install Docker Desktop and run this file again.
    pause
    exit /b 1
)

docker compose version >nul 2>nul
if errorlevel 1 (
    echo [repair-env] Docker Compose was not found. Install/update Docker Desktop and run this file again.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\Repair-Env.ps1
if errorlevel 1 (
    echo [repair-env] Repair failed. Send the error above to support.
    pause
    exit /b 1
)

echo.
echo === Repaired ===
echo Now run reset-login.bat and log in as admin with the password from .admin-login.txt
echo.
