@echo off
REM Content Tracker — one-command setup for Windows
REM Usage: setup.bat

echo === Content Tracker Setup ===

REM 1. Create .env from example if missing
if not exist .env (
    echo [setup] Creating .env from .env.example...
    copy .env.example .env
    echo [setup] .env created. Edit it to set passwords and API keys.
)

REM 2. Create data directories
if not exist data\postgres mkdir data\postgres
if not exist backend\uploads mkdir backend\uploads

REM 3. Build and start
echo [setup] Building and starting containers...
docker compose up --build -d

echo.
echo === Done ===
echo   Web:  http://localhost:5000
echo   API:  http://localhost:8000/docs
echo.
echo Next steps:
echo   1. Open http://localhost:5000 and register
echo   2. Go to /admin/settings to configure platform tokens and proxies
