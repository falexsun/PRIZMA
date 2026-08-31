@echo off
setlocal
REM Content Tracker - update existing Windows installation
REM Usage: update.bat

echo === Content Tracker Update ===

where git >nul 2>nul
if errorlevel 1 (
    echo [update] Git was not found. Install Git and run this file again.
    pause
    exit /b 1
)

where docker >nul 2>nul
if errorlevel 1 (
    echo [update] Docker was not found. Install Docker Desktop and run this file again.
    pause
    exit /b 1
)

docker compose version >nul 2>nul
if errorlevel 1 (
    echo [update] Docker Compose was not found. Install/update Docker Desktop and run this file again.
    pause
    exit /b 1
)

if not exist .git (
    echo [update] This folder is not a Git repository. Run update.bat from the project root.
    pause
    exit /b 1
)

echo [update] Pulling latest project changes...
git pull --ff-only
if errorlevel 1 (
    echo [update] Git pull failed. Check the message above and resolve local changes first.
    pause
    exit /b 1
)

if exist account.txt (
    echo [update] Found account.txt, refreshing backend startup seed copy...
    copy /Y account.txt backend\default_accounts.json >nul
) else if exist accounts.txt (
    echo [update] Found accounts.txt, refreshing backend startup seed copy...
    copy /Y accounts.txt backend\default_accounts.json >nul
) else if exist default_accounts.json (
    echo [update] Found default_accounts.json, refreshing backend startup seed copy...
    copy /Y default_accounts.json backend\default_accounts.json >nul
)

echo [update] Rebuilding and restarting containers...
docker compose up --build -d
if errorlevel 1 (
    echo [update] Docker update failed. Check Docker Desktop and the logs above.
    pause
    exit /b 1
)

echo.
echo === Updated ===
echo   Web:  http://localhost:5000
echo   API:  http://localhost:8000/docs
echo.
start "" http://localhost:5000
