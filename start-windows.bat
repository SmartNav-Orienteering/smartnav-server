@echo off
rem SmartNav server for Windows: double-click to start.
rem First run: creates a Python environment and installs SmartNav (a minute or two).
rem Later runs: starts straight away. Close this window or press Ctrl+C to stop.
setlocal
cd /d "%~dp0"
title SmartNav server

rem ---- find Python 3.11 or later -------------------------------------------
set "PY="
rem Prefer Python 3.12 or 3.13, which all of SmartNav's dependencies support.
py -3.12 -c "" >nul 2>nul && set "PY=py -3.12"
if not defined PY py -3.13 -c "" >nul 2>nul && set "PY=py -3.13"
if not defined PY where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY goto nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto nopython

rem ---- first run: create the environment and install -----------------------
if not exist "venv\Scripts\smartnav.exe" (
  echo Setting up SmartNav for the first time. This takes a minute or two...
  %PY% -m venv venv
  if errorlevel 1 goto failed
  venv\Scripts\python -m pip install --quiet --upgrade pip
  venv\Scripts\python -m pip install --quiet -e .\sdk -e .\plugins -e .\server
  if errorlevel 1 goto failed
  echo.
  choice /c YN /m "Add sample events and runs so you can look around"
  if not errorlevel 2 (
    set "SMARTNAV_DATA_DIR=%~dp0data"
    venv\Scripts\smartnav demo
  )
)

rem ---- settings --------------------------------------------------------------
if not defined SMARTNAV_BASE_URL set "SMARTNAV_BASE_URL=http://localhost:8000"
set "SMARTNAV_DATA_DIR=%~dp0data"

rem ---- start -----------------------------------------------------------------
echo.
echo SmartNav is starting.
echo   Admin site:   http://localhost:8000/admin
echo   Results site: http://localhost:8000
echo   Your data is kept in: %SMARTNAV_DATA_DIR%
echo Close this window or press Ctrl+C to stop the server.
echo.
start "" /b cmd /c "timeout /t 4 /nobreak >nul & start "" http://localhost:8000/admin"
venv\Scripts\smartnav serve --port 8000
if errorlevel 1 goto failed
goto end

:nopython
echo.
echo Python 3.11 or later was not found.
echo Install Python 3.12 from https://www.python.org/downloads/
echo On the installer's first screen, tick "Add python.exe to PATH", then run this file again.
echo.
pause
goto end

:failed
echo.
echo Something went wrong. If this happened during setup, delete the "venv" folder
echo next to this file and try again. If it keeps failing, copy the messages above
echo and send them to whoever maintains your SmartNav server.
echo.
pause

:end
endlocal
