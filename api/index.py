"""
api/index.py — Vercel serverless entry point for the LADLI Flask app.

Vercel's Python runtime looks for a WSGI/ASGI callable named `app` in files
under /api. Every incoming route is rewritten to this function by vercel.json,
so Flask keeps full control of routing (public site, /admin pages and the
JSON API alike).

Serverless notes:
  * The filesystem is read-only apart from /tmp, so ATTACHMENT_DIR is pointed
    at /tmp and AWS S3 must be configured for durable quote attachments.
  * Set DATABASE_URL to a pooled/serverless-friendly PostgreSQL connection
    (Neon, Supabase pooler, RDS Proxy…), because each invocation may open its
    own connection.
"""

import os
import sys

os.environ.setdefault("ATTACHMENT_DIR", "/tmp/ladli-attachments")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402  (Flask WSGI application)

# Vercel invokes this object.
application = app
