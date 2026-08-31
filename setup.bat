@echo off
setlocal
REM Content Tracker - one-command setup for Windows
REM Usage: setup.bat

echo === Content Tracker Setup ===

where docker >nul 2>nul
if errorlevel 1 (
    echo [setup] Docker was not found. Install Docker Desktop and run this file again.
    pause
    exit /b 1
)

docker compose version >nul 2>nul
if errorlevel 1 (
    echo [setup] Docker Compose was not found. Install/update Docker Desktop and run this file again.
    pause
    exit /b 1
)

REM 1. Create .env from example if missing
if not exist .env (
    echo [setup] Creating .env with generated local secrets...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$pg=[Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(24)).TrimEnd('=').Replace('+','-').Replace('/','_');" ^
      "$jwt=[Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48)).TrimEnd('=').Replace('+','-').Replace('/','_');" ^
      "$admin=[Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(12)).TrimEnd('=').Replace('+','-').Replace('/','_');" ^
      "$env=(Get-Content '.env.example' -Raw);" ^
      "$env=$env -replace 'POSTGRES_PASSWORD=.*', ('POSTGRES_PASSWORD=' + $pg);" ^
      "$env=$env -replace 'DATABASE_URL=.*', ('DATABASE_URL=postgresql+asyncpg://content_tracker:' + $pg + '@postgres:5432/content_tracker');" ^
      "$env=$env -replace 'JWT_SECRET=.*', ('JWT_SECRET=' + $jwt);" ^
      "$env=$env -replace 'ENV=.*', 'ENV=local';" ^
      "$env=$env -replace 'INITIAL_ADMIN_PASSWORD=.*', ('INITIAL_ADMIN_PASSWORD=' + $admin);" ^
      "Set-Content -Path '.env' -Value $env -Encoding UTF8;" ^
      "Set-Content -Path '.admin-login.txt' -Value ('Login: admin' + [Environment]::NewLine + 'Password: ' + $admin) -Encoding UTF8;"
    if errorlevel 1 (
        echo [setup] Failed to create .env.
        pause
        exit /b 1
    )
    echo [setup] .env created.
    echo [setup] Admin credentials saved to .admin-login.txt
) else (
    echo [setup] .env already exists, keeping current settings.
)

REM 2. Create data directories
if not exist data\postgres mkdir data\postgres
if not exist backend\uploads mkdir backend\uploads
if not exist backend\max_session mkdir backend\max_session
if not exist vpn mkdir vpn

REM 3. Optional client-provided accounts file.
REM The file content must be JSON in the same format as default_accounts.example.json.
if exist account.txt (
    echo [setup] Found account.txt, adding it to backend startup seed...
    copy /Y account.txt backend\default_accounts.json >nul
) else if exist accounts.txt (
    echo [setup] Found accounts.txt, adding it to backend startup seed...
    copy /Y accounts.txt backend\default_accounts.json >nul
) else if exist default_accounts.json (
    echo [setup] Found default_accounts.json, adding it to backend startup seed...
    copy /Y default_accounts.json backend\default_accounts.json >nul
)

REM 4. Build and start
echo [setup] Building and starting containers...
docker compose up --build -d
if errorlevel 1 (
    echo [setup] Docker startup failed. Check Docker Desktop and the logs above.
    pause
    exit /b 1
)

echo.
echo === Done ===
echo   Web:  http://localhost:5000
echo   API:  http://localhost:8000/docs
echo.
echo Next steps:
echo   1. Open http://localhost:5000
echo   2. Log in with credentials from .admin-login.txt
echo   3. Go to http://localhost:5000/admin/settings to configure platform tokens and proxies
echo.
start "" http://localhost:5000
