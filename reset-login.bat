@echo off
setlocal
REM Content Tracker - reset local admin login without deleting data
REM Usage: reset-login.bat

echo === Content Tracker Login Reset ===

where docker >nul 2>nul
if errorlevel 1 (
    echo [reset-login] Docker was not found. Install Docker Desktop and run this file again.
    pause
    exit /b 1
)

docker compose version >nul 2>nul
if errorlevel 1 (
    echo [reset-login] Docker Compose was not found. Install/update Docker Desktop and run this file again.
    pause
    exit /b 1
)

echo [reset-login] Making sure database and API image are ready...
docker compose build api
if errorlevel 1 (
    echo [reset-login] Failed to build API image. Run update.bat first, then try again.
    pause
    exit /b 1
)

docker compose up -d postgres redis
if errorlevel 1 (
    echo [reset-login] Failed to start database services.
    pause
    exit /b 1
)

echo [reset-login] Waiting for database...
for /L %%I in (1,1,30) do (
    docker compose exec -T postgres pg_isready -h localhost >nul 2>nul
    if not errorlevel 1 goto postgres_ready
    timeout /t 2 /nobreak >nul
)
echo [reset-login] Database did not become ready in time.
pause
exit /b 1

:postgres_ready
echo [reset-login] Applying migrations...
docker compose run --rm --no-deps --entrypoint "" api alembic upgrade head >nul
if errorlevel 1 (
    echo [reset-login] Failed to prepare database. Run update.bat first, then try again.
    pause
    exit /b 1
)

echo [reset-login] Generating a new admin password...
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$bytes=New-Object byte[] 12; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes); [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')"`) do set "ADMIN_PASSWORD=%%P"

docker compose run --rm --no-deps --entrypoint "" -e RESET_ADMIN_LOGIN=admin -e RESET_ADMIN_PASSWORD=%ADMIN_PASSWORD% api python -m app.scripts.reset_admin_password > .admin-login.txt
if errorlevel 1 (
    echo [reset-login] Failed to reset admin password. Run update.bat first, then try again.
    pause
    exit /b 1
)

echo [reset-login] Admin credentials saved to .admin-login.txt
echo.
type .admin-login.txt
echo.
echo [reset-login] Restarting API and web...
docker compose up -d api web

echo.
echo === Done ===
echo Open http://localhost:5000 and log in with credentials from .admin-login.txt
echo.
start "" http://localhost:5000
