@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo  McParty Backend
echo ============================================

if exist "venv\Scripts\python.exe" (
  set "PY=venv\Scripts\python.exe"
  echo [1/2] Using bundled venv python...
) else (
  set "PY=python"
  echo [1/2] venv not found, using system python...
)

echo [2/2] Checking dependencies (flask)...
%PY% -c "import flask, flask_cors" >nul 2>&1
if errorlevel 1 (
  echo   First run: installing dependencies, please wait...
  %PY% -m pip install -r requirements.txt
)

echo.
echo Starting backend on http://localhost:5000 ...
echo (Keep this window OPEN while using the web page)
echo.
%PY% app.py
pause
