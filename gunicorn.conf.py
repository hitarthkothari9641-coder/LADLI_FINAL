"""
gunicorn.conf.py — Gunicorn production configuration for LADLI.

Usage:
    gunicorn -c gunicorn.conf.py app:app
"""

import multiprocessing
import os

# ---------------------------------------------------------------------------
# Server socket
# ---------------------------------------------------------------------------
# PaaS platforms (Render, Railway, Heroku…) inject the port to listen on via
# $PORT — honour it automatically so no extra configuration is required.
bind = os.environ.get(
    "GUNICORN_BIND",
    "0.0.0.0:{}".format(os.environ.get("PORT", "8000")),
)

# ---------------------------------------------------------------------------
# Worker processes
# ---------------------------------------------------------------------------
# 2 × CPU cores + 1 is a good general-purpose default.  Override with
# GUNICORN_WORKERS if the instance is memory-constrained or if the app
# is mostly I/O-bound (fewer workers) vs. CPU-bound (more workers).
workers = int(os.environ.get("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", 2))

# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------
timeout = 120          # Kill workers silent for > 120 s
graceful_timeout = 30  # Time to finish requests on reload/stop
keepalive = 5          # Seconds to wait for next request on a keep-alive connection

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
accesslog = "-"        # stdout
errorlog = "-"         # stderr
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------
preload_app = True     # Load app before forking workers (saves memory via COW)
max_requests = 1000    # Restart workers after N requests (prevents memory leaks)
max_requests_jitter = 50  # Random jitter to prevent all workers restarting at once

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
# Trust X-Forwarded-* headers from the ALB/CloudFront proxy only.
forwarded_allow_ips = os.environ.get("GUNICORN_FORWARDED_ALLOW_IPS", "*")
