"""
gunicorn.conf.py — Gunicorn production configuration for LADLI.

Usage:
    gunicorn -c gunicorn.conf.py app:app
"""

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
# Start with a bounded footprint; tune against measured memory and DB limits.
workers = int(os.environ.get("GUNICORN_WORKERS", 2))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", 2))

# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))          # Kill workers silent for > 120 s
graceful_timeout = 30  # Time to finish requests on reload/stop
keepalive = 5          # Seconds to wait for next request on a keep-alive connection

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Exclude query strings, cookies and referrers (which can carry credentials).
access_log_format = '%(h)s %(m)s %(U)s %(s)s %(L)s'
accesslog = "-"        # stdout
errorlog = "-"         # stderr
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------
preload_app = False     # Keep database pools and locks local to each worker
max_requests = 1000    # Restart workers after N requests (prevents memory leaks)
max_requests_jitter = 50  # Random jitter to prevent all workers restarting at once

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
# Trust X-Forwarded-* headers from the ALB/CloudFront proxy only.
forwarded_allow_ips = os.environ.get("GUNICORN_FORWARDED_ALLOW_IPS", "127.0.0.1,::1")
