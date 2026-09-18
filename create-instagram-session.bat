@echo off
setlocal EnableExtensions DisableDelayedExpansion
REM Content Tracker - create Instagram browser session for reels discovery
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

if not exist backend\tools\save_instagram_session_from_cdp.py (
    echo [instagram-session] backend\tools\save_instagram_session_from_cdp.py was not found.
    echo [instagram-session] Run git pull and try again.
    pause
    exit /b 1
)

if not exist backend\uploads mkdir backend\uploads

set "SESSION_EXIT=1"

call :try_docker_session
if "%SESSION_EXIT%"=="0" goto verify_session

echo.
echo [instagram-session] Docker browser-session path was not completed.
echo [instagram-session] Falling back to local Python setup...
echo.

call :try_local_python_session
if not "%SESSION_EXIT%"=="0" (
    echo [instagram-session] Session creation failed.
    pause
    exit /b %SESSION_EXIT%
)

:verify_session
if not exist backend\uploads\instagram_storage_state.json (
    echo [instagram-session] Session file was not created.
    pause
    exit /b 1
)

echo.
echo [instagram-session] Session saved:
echo   backend\uploads\instagram_storage_state.json
echo.

call :restart_docker_services
if not "%SESSION_EXIT%"=="0" exit /b %SESSION_EXIT%

echo.
echo === Done ===
echo Instagram session is ready. Reels discovery will use the saved browser session.
echo.
pause
exit /b 0

:try_docker_session
set "SESSION_EXIT=1"
where docker >nul 2>nul
if errorlevel 1 (
    echo [instagram-session] Docker was not found.
    exit /b 0
)

docker compose version >nul 2>nul
if errorlevel 1 (
    echo [instagram-session] Docker Compose was not found.
    exit /b 0
)

call :find_browser
if not defined BROWSER_EXE (
    echo [instagram-session] Chrome or Edge was not found for local login window.
    exit /b 0
)

set "CDP_PROFILE=%TEMP%\content-tracker-instagram-browser"
echo [instagram-session] Opening local browser for Instagram login...
echo [instagram-session] Browser: "%BROWSER_EXE%"
echo.
echo If Instagram does not open in this browser, use your system VPN/proxy and run this file again.
echo.
start "" "%BROWSER_EXE%" --remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 --remote-allow-origins=* --user-data-dir="%CDP_PROFILE%" "https://www.instagram.com/accounts/login/"

echo Log in to Instagram in the opened browser window.
echo Complete 2FA/challenge if Instagram asks for it.
echo.
pause

echo [instagram-session] Saving session with Docker Python...
docker compose build api
if errorlevel 1 (
    set "SESSION_EXIT=1"
    exit /b 0
)
docker compose run --rm --no-deps --entrypoint python api tools/save_instagram_session_from_cdp.py
set "SESSION_EXIT=%ERRORLEVEL%"
exit /b 0

:find_browser
set "BROWSER_EXE="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if defined BROWSER_EXE exit /b 0
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "BROWSER_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if defined BROWSER_EXE exit /b 0
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "BROWSER_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if defined BROWSER_EXE exit /b 0
if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER_EXE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if defined BROWSER_EXE exit /b 0
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER_EXE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
exit /b 0

:try_local_python_session
set "PY_EXE="
set "PY_CHECK_LOG=%TEMP%\content-tracker-python-check.log"
set "VENV_LOG=%TEMP%\content-tracker-venv.log"

call :select_python
if not defined PY_EXE (
    call :install_python_with_winget
    call :select_python
)
if not defined PY_EXE (
    echo [instagram-session] Working Python 3 was not found.
    echo [instagram-session] Install Python 3.11+ from https://www.python.org/downloads/windows/
    echo [instagram-session] Important: enable "Add python.exe to PATH" during installation.
    echo.
    if exist "%PY_CHECK_LOG%" (
        echo [instagram-session] Last Python check output:
        type "%PY_CHECK_LOG%"
        echo.
    )
    set "SESSION_EXIT=1"
    exit /b 0
)

if not exist backend\.venv\Scripts\python.exe (
    echo [instagram-session] Creating local Python environment...
    "%PY_EXE%" -m venv --clear backend\.venv > "%VENV_LOG%" 2>&1
    if errorlevel 1 (
        echo [instagram-session] Failed to create backend\.venv.
        echo [instagram-session] Python used: "%PY_EXE%"
        echo.
        if exist "%VENV_LOG%" (
            echo [instagram-session] Python error output:
            type "%VENV_LOG%"
            echo.
        )
        echo [instagram-session] If this says that venv or ensurepip is unavailable, reinstall Python from python.org.
        echo [instagram-session] If Python was installed from Microsoft Store, uninstall it and install Python from python.org.
        set "SESSION_EXIT=1"
        exit /b 0
    )
)

set "VENV_PY=backend\.venv\Scripts\python.exe"

echo [instagram-session] Installing Playwright if needed...
"%VENV_PY%" -m pip install --disable-pip-version-check --quiet "playwright==1.61.0"
if errorlevel 1 (
    echo [instagram-session] Failed to install Playwright.
    set "SESSION_EXIT=1"
    exit /b 0
)

echo [instagram-session] Making sure Chromium is installed...
"%VENV_PY%" -m playwright install chromium
if errorlevel 1 (
    echo [instagram-session] Failed to install Playwright Chromium.
    set "SESSION_EXIT=1"
    exit /b 0
)

echo.
echo If Instagram does not open directly, paste NON-RU proxy when asked.
echo Leave proxy empty if this computer already opens Instagram normally.
echo.

cd backend
"%~dp0backend\.venv\Scripts\python.exe" tools\create_instagram_session.py --ask-proxy
set "SESSION_EXIT=%ERRORLEVEL%"
cd /d "%~dp0"
exit /b 0

:restart_docker_services
set "SESSION_EXIT=0"
where docker >nul 2>nul
if errorlevel 1 (
    echo [instagram-session] Docker was not found, skipping service restart.
    echo [instagram-session] Restart API and worker-heavy later after Docker is available.
    exit /b 0
)

docker compose version >nul 2>nul
if errorlevel 1 (
    echo [instagram-session] Docker Compose was not found, skipping service restart.
    exit /b 0
)

echo [instagram-session] Restarting API and Instagram worker...
docker compose up -d api worker-heavy
set "SESSION_EXIT=%ERRORLEVEL%"
if not "%SESSION_EXIT%"=="0" (
    echo [instagram-session] Docker restart failed. The session file is saved, but services were not restarted.
)
exit /b 0

:select_python
call :try_python "py -3"
if defined PY_EXE exit /b 0
call :try_python "%LocalAppData%\Programs\Python\Python312\python.exe"
if defined PY_EXE exit /b 0
call :try_python "%LocalAppData%\Programs\Python\Python311\python.exe"
if defined PY_EXE exit /b 0
call :try_python "%ProgramFiles%\Python312\python.exe"
if defined PY_EXE exit /b 0
call :try_python "%ProgramFiles%\Python311\python.exe"
if defined PY_EXE exit /b 0
call :try_python "python"
if defined PY_EXE exit /b 0
call :try_python "python3"
exit /b 0

:try_python
set "PY_CANDIDATE=%~1"
if not defined PY_CANDIDATE exit /b 1
if not exist "%PY_CANDIDATE%" (
    echo %PY_CANDIDATE% | findstr /i "\.exe" >nul 2>nul
    if not errorlevel 1 exit /b 1
)
echo %PY_CANDIDATE% | findstr /i "\.exe" >nul 2>nul
if not errorlevel 1 (
    "%PY_CANDIDATE%" -c "import sys, venv; print(sys.executable)" > "%PY_CHECK_LOG%" 2>&1
) else (
    %PY_CANDIDATE% -c "import sys, venv; print(sys.executable)" > "%PY_CHECK_LOG%" 2>&1
)
if errorlevel 1 exit /b 1
for /f "usebackq delims=" %%P in ("%PY_CHECK_LOG%") do (
    set "PY_EXE=%%P"
    exit /b 0
)
exit /b 1

:install_python_with_winget
where winget >nul 2>nul
if errorlevel 1 exit /b 0
echo [instagram-session] Python 3 was not found. Trying to install Python 3.12 with winget...
winget install --id Python.Python.3.12 -e --source winget --silent --accept-package-agreements --accept-source-agreements
exit /b 0
