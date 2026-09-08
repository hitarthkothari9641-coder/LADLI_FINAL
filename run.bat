@echo off
REM ===========================================================================
REM run.bat - LADLI local development launcher (Windows)
REM ---------------------------------------------------------------------------
REM DEVELOPMENT USE ONLY - do NOT include this file in the production package.
REM Production runs under Gunicorn on Linux:
REM     gunicorn -c gunicorn.conf.py app:app
REM
REM Usage:  double-click run.bat, or from a terminal:  run.bat
REM
REM Requirements:
REM   - Python 3.9+ on PATH (py launcher or python)
REM   - A reachable PostgreSQL database. Configure it in a local .env file
REM     (copy .env.example to .env) via DATABASE_URL or PGHOST/PGDATABASE/
REM     PGUSER. app.py loads .env automatically on startup.
REM ===========================================================================
setlocal
cd /d "%~dp0"

REM ---- Pick a Python interpreter -------------------------------------------
set "PY=py -3"
%PY% --version >nul 2>&1
if errorlevel 1 (
    set "PY=python"
    %PY% --version >nul 2>&1
    if errorlevel 1 (
        echo [run.bat] ERROR: Python 3 was not found on PATH.
        echo           Install it from https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

REM ---- Virtual environment ---------------------------------------------------
if not exist ".venv\Scripts\activate.bat" (
    echo [run.bat] Creating virtual environment ^(.venv^)...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [run.bat] ERROR: could not create the virtual environment.
        pause
        exit /b 1
    )
)
call ".venv\Scripts\activate.bat"

REM ---- Dependencies -----------------------------------------------------------
echo [run.bat] Installing dependencies...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo [run.bat] ERROR: dependency installation failed.
    pause
    exit /b 1
)

REM ---- Sanity hint ------------------------------------------------------------
if not exist ".env" (
    echo [run.bat] NOTE: no .env file found. Copy .env.example to .env and set
    echo           DATABASE_URL ^(PostgreSQL^) before starting. The app will
    echo           not start without a reachable PostgreSQL database.
)

REM ---- Start ------------------------------------------------------------------
echo [run.bat] Starting Flask dev server on http://127.0.0.1:5000 ...
python app.py
pause
