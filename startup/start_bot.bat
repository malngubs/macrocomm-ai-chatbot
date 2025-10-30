@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM =============================================================================
REM Macrocomm Desktop Chatbot launcher (single source of truth)
REM - Starts local FastAPI backend (uvicorn) in the repo's /server
REM - Starts Electron desktop bubble from /desktop-wrapper
REM - Reads/sets MACROCOMM_URL (default to local http://127.0.0.1:8000)
REM - Designed to be called directly or via start_bot_hidden.vbs (hidden window)
REM =============================================================================

REM --- 0) Resolve repo root from THIS script's location (portable, no hardcoded paths) ---
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%\.." 1>nul 2>nul
set "REPO_ROOT=%CD%"
popd 1>nul 2>nul

set "STARTUP_DIR=%REPO_ROOT%\startup"
set "BACKEND_DIR=%REPO_ROOT%\server"
set "ELECTRON_DIR=%REPO_ROOT%\desktop-wrapper"
set "LOG_DIR=%STARTUP_DIR%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" 1>nul 2>nul

set "BOOT_LOG=%LOG_DIR%\macrocomm_bootstrap.log"
echo.>>"%BOOT_LOG%"
echo [%date% %time%] ==== LAUNCH START ==== >>"%BOOT_LOG%"
echo [%date% %time%] REPO_ROOT=%REPO_ROOT% >>"%BOOT_LOG%"

REM --- 1) Backend URL target ----------------------------------------------
REM Choose where you want the UI to point:
REM    - Local dev backend on this machine:
set "MACROCOMM_URL=http://127.0.0.1:8000"
REM    - Or your shared server (uncomment & adjust if needed):
REM set "MACROCOMM_URL=http://10.0.0.5:8000"
REM    - Or HTTPS reverse-proxy DNS name:
REM set "MACROCOMM_URL=https://bot.macrocomm.local"

echo [%date% %time%] MACROCOMM_URL=%MACROCOMM_URL% >>"%BOOT_LOG%"

REM --- 2) Activate Python env (conda preferred; fallback to venv if present) ----------
set "CONDA_HOOK=%USERPROFILE%\anaconda3\condabin\conda.bat"
if exist "%CONDA_HOOK%" (
  call "%CONDA_HOOK%" activate macrocomm-rag  1>>"%BOOT_LOG%" 2>&1
) else (
  if exist "%REPO_ROOT%\.venv\Scripts\activate.bat" (
    call "%REPO_ROOT%\.venv\Scripts\activate.bat"  1>>"%BOOT_LOG%" 2>&1
  ) else (
    echo [%date% %time%] WARN: No conda or .venv activation found. >>"%BOOT_LOG%"
  )
)

REM --- 3) Start/ensure backend (uvicorn) on 127.0.0.1:8000 --------------------------
REM If you want to use the shared server instead, skip this block.
REM We check whether 8000 is already listened to; if not, we start uvicorn.
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":8000 .*LISTENING"') do (
  set "UVICORN_PID=%%P"
)

if not defined UVICORN_PID (
  echo [%date% %time%] Starting uvicorn... >>"%BOOT_LOG%"
  pushd "%BACKEND_DIR%"
  REM Start in a minimized console so it doesn’t steal focus
  start "macrocomm_api" /min cmd /c ^
    uvicorn server.api_server:app --host 127.0.0.1 --port 8000 --reload 1>>"%BOOT_LOG%" 2>&1
  popd
) else (
  echo [%date% %time%] uvicorn already listening on :8000 (PID !UVICORN_PID!) >>"%BOOT_LOG%"
)

REM --- 4) Start Electron desktop bubble -------------------------------------------
pushd "%ELECTRON_DIR%"

REM First run? install dependencies (safe to run once)
if not exist "node_modules" (
  echo [%date% %time%] npm install (desktop-wrapper)... >>"%BOOT_LOG%"
  call npm install 1>>"%BOOT_LOG%" 2>&1
)

REM Pass MACROCOMM_URL to the Electron app (only for this process tree)
set "MACROCOMM_URL=%MACROCOMM_URL%"

REM Start Electron minimized; only the bubble (always-on-top) will appear
REM (package.json: "start": "electron .")
echo [%date% %time%] starting Electron... >>"%BOOT_LOG%"
start "macrocomm_ui" /min cmd /c npm run start 1>>"%BOOT_LOG%" 2>&1

popd

echo [%date% %time%] ==== LAUNCH END ==== >>"%BOOT_LOG%"
exit /b 0
