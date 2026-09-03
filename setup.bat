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
      "function New-Secret([int]$n){$bytes=New-Object byte[] $n; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes); [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')};" ^
      "$pg=New-Secret 24;" ^
      "$jwt=New-Secret 48;" ^
      "$admin=New-Secret 12;" ^
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
set "ACCOUNTS_SOURCE="
if exist account.txt (
    set "ACCOUNTS_SOURCE=account.txt"
) else if exist accounts.txt (
    set "ACCOUNTS_SOURCE=accounts.txt"
) else if exist default_accounts.json (
    set "ACCOUNTS_SOURCE=default_accounts.json"
)

if defined ACCOUNTS_SOURCE (
    echo [setup] Found %ACCOUNTS_SOURCE%, validating accounts JSON...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content '%ACCOUNTS_SOURCE%' -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null"
    if errorlevel 1 (
        echo [setup] %ACCOUNTS_SOURCE% is not valid JSON. Use default_accounts.example.json as the format reference.
        pause
        exit /b 1
    )
    echo [setup] Adding accounts file to backend startup seed...
    copy /Y "%ACCOUNTS_SOURCE%" backend\default_accounts.json >nul
) else if exist backend\default_accounts.json (
    echo [setup] Removing stale backend accounts seed copy...
    del /F /Q backend\default_accounts.json >nul
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
