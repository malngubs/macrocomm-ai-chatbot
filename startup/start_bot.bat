@echo off
setlocal enableextensions enabledelayedexpansion

REM ======================================================================
REM Macrocomm autostart (single-source, main repo)
REM ======================================================================

REM Log to %TEMP% so we always see if the task fired
set "BOOT_LOG=%TEMP%\macrocomm_bootstrap.log"
echo.>>"%BOOT_LOG%"
echo =========================================================>>"%BOOT_LOG%"
echo [%date% %time%] START start_bot.bat >> "%BOOT_LOG%"
echo [%date% %time%] CWD=%CD% >> "%BOOT_LOG%"

REM -------- REPO ROOT (your canonical codebase) --------
set "REPO_ROOT=C:\Users\Malusi\OneDrive - MACROCOMM\Desktop\macrocomm-ai-chatbot"

REM Derived folders
set "STARTUP_DIR=%REPO_ROOT%\startup"
set "BACKEND_DIR=%REPO_ROOT%\server"
set "ELECTRON_DIR=%REPO_ROOT%\desktop-wrapper"

REM -------- Conda + API config --------
set "CONDA_DIR=%USERPROFILE%\anaconda3"
set "CONDA_ENV=macrocomm-rag"
set "UVICORN_APP=server.api_server:app"
set "API_HOST=127.0.0.1"
set "API_PORT=8000"

REM Logs next to this script
set "LOG_DIR=%STARTUP_DIR%\logs"
set "API_WAIT_SECONDS=6"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" 2>nul
echo.>>"%LOG_DIR%\startup.log"
echo =========================================================>>"%LOG_DIR%\startup.log"
echo [%date% %time%] start_bot.bat invoked. REPO_ROOT=%REPO_ROOT% >> "%LOG_DIR%\startup.log"

REM -------- Activate conda --------
if not exist "%CONDA_DIR%\Scripts\activate.bat" (
  echo [%date% %time%] ERROR: Missing %CONDA_DIR%\Scripts\activate.bat >> "%BOOT_LOG%"
  echo [%date% %time%] ERROR: Missing conda activate >> "%LOG_DIR%\startup.log"
  goto :EOF
)
call "%CONDA_DIR%\Scripts\activate.bat" "%CONDA_ENV%"
if errorlevel 1 (
  echo [%date% %time%] ERROR: Failed to activate env %CONDA_ENV% >> "%BOOT_LOG%"
  echo [%date% %time%] ERROR: Failed to activate env %CONDA_ENV% >> "%LOG_DIR%\startup.log"
  goto :EOF
)
echo [%date% %time%] Conda env "%CONDA_ENV%" activated. >> "%LOG_DIR%\startup.log"

REM -------- Start FastAPI (detached/minimized) --------
if not exist "%BACKEND_DIR%" (
  echo [%date% %time%] ERROR: BACKEND_DIR not found: %BACKEND_DIR% >> "%LOG_DIR%\startup.log"
  goto :EOF
)
pushd "%BACKEND_DIR%"
echo [%date% %time%] Starting API: %UVICORN_APP% on %API_HOST%:%API_PORT% >> "%LOG_DIR%\startup.log"
start "" /MIN cmd /c ^
  "python -m uvicorn %UVICORN_APP% --host %API_HOST% --port %API_PORT% >> \"%LOG_DIR%\api.log\" 2>&1"
popd

REM -------- Wait for API to bind --------
set /a _pings=%API_WAIT_SECONDS%+1
ping 127.0.0.1 -n %_pings% >nul

REM -------- Start Electron from desktop-wrapper --------
if exist "%ELECTRON_DIR%\package.json" (
  pushd "%ELECTRON_DIR%"
  echo [%date% %time%] Launching Electron (dev) from %ELECTRON_DIR% >> "%LOG_DIR%\startup.log"
  start "" /MIN cmd /c ^
    "npx --yes electron . >> \"%LOG_DIR%\electron.log\" 2>&1"
  popd
) else (
  echo [%date% %time%] ERROR: No package.json in %ELECTRON_DIR% >> "%LOG_DIR%\startup.log"
)

echo [%date% %time%] DONE start_bot.bat >> "%LOG_DIR%\startup.log"
exit /b 0
