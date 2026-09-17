@echo off
setlocal
REM Content Tracker - create local Instagram browser session for reels discovery
REM Usage: create-instagram-session.bat

cd /d "%~dp0"

echo === Instagram Session Setup ===
echo This tool opens a browser window. Log in to Instagram manually there.
echo Your Instagram password is not saved by this script.
echo.

if not exist backend\tools\create_instagram_session.py (
    echo [instagram-session] backend\tools\create_instagram_session.py was not found.
    echo [instagram-session] Run this file from the Content Tracker project root.
    pause
    exit /b 1
)

if not exist backend\uploads mkdir backend\uploads

set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=py -3"
) else (
    where python >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
    echo [instagram-session] Python was not found.
    echo [instagram-session] Install Python 3.11+ and enable "Add Python to PATH", then run this file again.
    pause
    exit /b 1
)

if not exist backend\.venv\Scripts\python.exe (
    echo [instagram-session] Creating local Python environment...
    %PY_CMD% -m venv backend\.venv
    if errorlevel 1 (
        echo [instagram-session] Failed to create backend\.venv.
        pause
        exit /b 1
    )
)

set "VENV_PY=backend\.venv\Scripts\python.exe"

echo [instagram-session] Installing Playwright if needed...
"%VENV_PY%" -m pip install --disable-pip-version-check --quiet "playwright==1.61.0"
if errorlevel 1 (
    echo [instagram-session] Failed to install Playwright.
    pause
    exit /b 1
)

echo [instagram-session] Making sure Chromium is installed...
"%VENV_PY%" -m playwright install chromium
if errorlevel 1 (
    echo [instagram-session] Failed to install Playwright Chromium.
    pause
    exit /b 1
)

echo.
echo If Instagram does not open directly, paste NON-RU proxy when asked.
echo Leave proxy empty if this computer already opens Instagram normally.
echo.

cd backend
"%~dp0backend\.venv\Scripts\python.exe" tools\create_instagram_session.py --ask-proxy
set "SESSION_EXIT=%ERRORLEVEL%"
cd /d "%~dp0"

if not "%SESSION_EXIT%"=="0" (
    echo [instagram-session] Session creation failed.
    pause
    exit /b %SESSION_EXIT%
)

if not exist backend\uploads\instagram_storage_state.json (
    echo [instagram-session] Session file was not created.
    pause
    exit /b 1
)

echo.
echo [instagram-session] Session saved:
echo   backend\uploads\instagram_storage_state.json
echo.

where docker >nul 2>nul
if errorlevel 1 (
    echo [instagram-session] Docker was not found, skipping service restart.
    echo [instagram-session] Restart API and worker-heavy later after Docker is available.
    pause
    exit /b 0
)

docker compose version >nul 2>nul
if errorlevel 1 (
    echo [instagram-session] Docker Compose was not found, skipping service restart.
    pause
    exit /b 0
)

echo [instagram-session] Restarting API and Instagram worker...
docker compose up -d api worker-heavy
if errorlevel 1 (
    echo [instagram-session] Docker restart failed. The session file is saved, but services were not restarted.
    pause
    exit /b 1
)

echo.
echo === Done ===
echo Instagram session is ready. Reels discovery will use the saved browser session.
echo.
pause
