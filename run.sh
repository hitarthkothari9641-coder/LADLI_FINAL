#!/usr/bin/env bash
# =============================================================================
# run.sh — LADLI local development launcher (macOS / Linux)
# -----------------------------------------------------------------------------
# DEVELOPMENT USE ONLY — do NOT include this file in the production package.
# Production runs under Gunicorn:  gunicorn -c gunicorn.conf.py app:app
#
# Usage:
#   ./run.sh          # Flask dev server on http://127.0.0.1:5000
#   ./run.sh prod     # Gunicorn (production-style) on http://0.0.0.0:8000
#
# Requirements:
#   - Python 3.9+
#   - A reachable PostgreSQL database. Configure it in a local .env file
#     (copy .env.example → .env) via DATABASE_URL or PGHOST/PGDATABASE/PGUSER.
#     app.py loads .env automatically on startup.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

# ---- Virtual environment ----------------------------------------------------
if [ ! -d ".venv" ]; then
  echo "[run.sh] Creating virtual environment (.venv)…"
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# ---- Dependencies -----------------------------------------------------------
echo "[run.sh] Installing dependencies…"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# ---- Sanity hint ------------------------------------------------------------
if [ ! -f ".env" ]; then
  echo "[run.sh] NOTE: no .env file found. Copy .env.example to .env and set"
  echo "         DATABASE_URL (PostgreSQL) before starting, or export the"
  echo "         PG* variables in your shell. The app will not start without"
  echo "         a reachable PostgreSQL database."
fi

# ---- Start ------------------------------------------------------------------
MODE="${1:-dev}"
if [ "$MODE" = "prod" ]; then
  echo "[run.sh] Starting Gunicorn on http://0.0.0.0:8000 …"
  exec gunicorn -c gunicorn.conf.py app:app
else
  echo "[run.sh] Starting Flask dev server on http://127.0.0.1:5000 …"
  exec python app.py
fi
