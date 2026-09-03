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

set "ACCOUNTS_SOURCE="
if exist account.txt (
    set "ACCOUNTS_SOURCE=account.txt"
) else if exist accounts.txt (
    set "ACCOUNTS_SOURCE=accounts.txt"
) else if exist default_accounts.json (
    set "ACCOUNTS_SOURCE=default_accounts.json"
)

if defined ACCOUNTS_SOURCE (
    echo [update] Found %ACCOUNTS_SOURCE%, validating accounts JSON...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content '%ACCOUNTS_SOURCE%' -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null"
    if errorlevel 1 (
        echo [update] %ACCOUNTS_SOURCE% is not valid JSON. Use default_accounts.example.json as the format reference.
        pause
        exit /b 1
    )
    echo [update] Refreshing backend startup seed copy...
    copy /Y "%ACCOUNTS_SOURCE%" backend\default_accounts.json >nul
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
