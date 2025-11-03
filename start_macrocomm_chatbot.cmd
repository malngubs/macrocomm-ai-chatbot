@echo off
rem =========================================================
rem Macrocomm Assistant — Windows launcher (portable)
rem Reads backend URL from .\config\server_url.txt and launches Electron
rem =========================================================

setlocal enabledelayedexpansion

rem 1) Resolve paths
set "BASEDIR=%~dp0"
set "APPDIR=%BASEDIR%app"
set "ELECTRON=%APPDIR%\node_modules\electron\dist\electron.exe"

rem 2) Sanity checks
if not exist "%APPDIR%" (
  echo [ERROR] App folder not found: "%APPDIR%"
  pause
  exit /b 1
)
if not exist "%ELECTRON%" (
  echo [ERROR] Electron runtime not found: "%ELECTRON%"
  pause
  exit /b 1
)

rem 3) Backend URL from config (fallback to bot.macrocomm.local:8000)
set "MACROCOMM_URL="
if exist "%BASEDIR%config\server_url.txt" (
  for /f "usebackq delims=" %%A in ("%BASEDIR%config\server_url.txt") do set "MACROCOMM_URL=%%A"
)
if "%MACROCOMM_URL%"=="" set "MACROCOMM_URL=http://bot.macrocomm.local:8000"

rem 4) Export env var for Electron (desktop-wrapper/main.js reads it)
set "MACROCOMM_URL=%MACROCOMM_URL%"

rem 5) Launch Electron (detached)
start "" "%ELECTRON%" "%APPDIR%"
exit /b 0
