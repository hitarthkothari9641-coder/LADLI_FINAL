"""
app.py — LADLI website backend.
"""

import os
import json
import uuid
import datetime
import functools
import re
import secrets as _secrets
import time
import threading
import logging

from flask import (
    Flask, request, jsonify, session, send_from_directory,
    redirect, abort, Response, g
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import db

# ---------------------------------------------------------------------------
# Setup & Config
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.join(BASE_DIR, "site")
ADMIN_DIR = os.path.join(BASE_DIR, "admin")
ATTACHMENT_DIR = os.path.join(BASE_DIR, "attachments")
MAX_UPLOAD_MB = 25
MAX_ATTACHMENT_MB = 3

def _load_local_env_file():
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.isfile(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

_load_local_env_file()
os.makedirs(ATTACHMENT_DIR, exist_ok=True)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ladli")

def _env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")

app = Flask(__name__, static_folder=None)
_sec_key = os.environ.get("SECRET_KEY")
if not _sec_key:
    logger.warning("SECRET_KEY not set in environment; generating a random one. Sessions will not survive restarts.")
    _sec_key = os.urandom(32).hex()
app.config["SECRET_KEY"] = _sec_key

app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV") == "production" or _env_flag("FORCE_SECURE_COOKIES")
app.config["PERMANENT_SESSION_LIFETIME"] = datetime.timedelta(minutes=30)

db.init_db(
    default_username=os.environ.get("ADMIN_USERNAME", "admin"),
    default_password=os.environ.get("ADMIN_PASSWORD"),
    default_email=os.environ.get("ADMIN_EMAIL"),
)

# ---------------------------------------------------------------------------
# S3 Attachment Handling
# ---------------------------------------------------------------------------
try:
    import boto3
    from botocore.exceptions import ClientError
    S3_AVAILABLE = True
except ImportError:
    S3_AVAILABLE = False

S3_BUCKET = os.environ.get("AWS_S3_BUCKET")
S3_REGION = os.environ.get("AWS_REGION", "ap-south-1")

def _get_s3_client():
    if not S3_AVAILABLE or not S3_BUCKET:
        return None
    return boto3.client("s3", region_name=S3_REGION)

def _save_quote_attachment(file_storage):
    original_name = file_storage.filename or ""
    if not original_name.lower().endswith(".pdf"):
        raise ValueError("Attachment must be a PDF file.")

    data = file_storage.read()
    size_bytes = len(data)
    if size_bytes == 0:
        raise ValueError("Attached file appears to be empty.")
    if size_bytes > MAX_ATTACHMENT_MB * 1024 * 1024:
        raise ValueError(f"Attachment is larger than {MAX_ATTACHMENT_MB} MB. Please attach a smaller PDF.")
    if not data.startswith(b"%PDF"):
        raise ValueError("That file doesn't look like a valid PDF.")

    safe_original_name = secure_filename(original_name) or "attachment.pdf"
    
    s3 = _get_s3_client()
    if s3:
        s3_key = f"attachments/{uuid.uuid4().hex}.pdf"
        file_storage.seek(0)
        s3.upload_fileobj(file_storage, S3_BUCKET, s3_key, ExtraArgs={"ContentType": "application/pdf"})
        return s3_key, safe_original_name, size_bytes
    else:
        # Local fallback
        stored_name = f"{uuid.uuid4().hex}.pdf"
        full_path = os.path.join(ATTACHMENT_DIR, stored_name)
        with open(full_path, "wb") as f:
            f.write(data)
        return stored_name, safe_original_name, size_bytes

# ---------------------------------------------------------------------------
# Rate Limiting & Security
# ---------------------------------------------------------------------------

class RateLimiter:
    def __init__(self):
        self._buckets = {}
        self._lock = threading.Lock()
    
    def is_limited(self, key, max_requests, window_seconds):
        now = time.time()
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = []
            # Clean old entries
            self._buckets[key] = [t for t in self._buckets[key] if now - t < window_seconds]
            if len(self._buckets[key]) >= max_requests:
                return True
            self._buckets[key].append(now)
            return False

_rate_limiter = RateLimiter()

def _client_ip():
    trusted_count = int(os.environ.get("TRUSTED_PROXY_COUNT", "1"))
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",")]
        idx = max(0, len(parts) - trusted_count)
        return parts[idx]
    return request.remote_addr or "unknown"

@app.after_request
def set_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if app.config["SESSION_COOKIE_SECURE"]:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    
    if not response.headers.get("Content-Security-Policy"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
    return response

@app.route("/api/admin/csrf-token")
def api_csrf_token():
    if not session.get("admin_user"):
        return jsonify({"error": "Not authenticated"}), 401
    token = _secrets.token_urlsafe(32)
    session["csrf_token"] = token
    return jsonify({"csrf_token": token})

def _verify_csrf():
    token = request.headers.get("X-CSRF-Token") or request.form.get("_csrf_token")
    if not token or token != session.get("csrf_token"):
        abort(403)

def require_admin(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        username = session.get("admin_user")
        if not username:
            return jsonify({"error": "Not authenticated"}), 401
        
        # Verify CSRF for state-changing operations
        if request.method in ("POST", "PUT", "DELETE"):
            if request.path not in ("/api/admin/login", "/api/admin/logout"):
                _verify_csrf()

        if request.path != "/api/admin/change-password":
            conn = db.get_db()
            row = conn.execute(
                "SELECT must_change_password FROM admin_users WHERE username = %s",
                (username,),
            ).fetchone()
            conn.close()
            if row and row["must_change_password"]:
                return jsonify({"error": "Password change required.", "must_change_password": True}), 403
        return view(*args, **kwargs)
    return wrapped

# Input Validation
def _validate_email(email):
    if not email or len(email) > 254:
        return False
    return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))

def _validate_phone(phone):
    if not phone:
        return True  # optional
    cleaned = re.sub(r'[\s\-\(\)\+]', '', phone)
    return len(cleaned) >= 7 and len(cleaned) <= 15 and cleaned.isdigit()

def _validate_name(name):
    return bool(name) and 1 <= len(name.strip()) <= 200

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def now_iso():
    return datetime.datetime.utcnow().isoformat()

def display_date(iso_str):
    try:
        dt = datetime.datetime.fromisoformat(iso_str)
        return dt.strftime("%d %b %Y")
    except Exception:
        return ""

def _respond_ok(data):
    wants_json = request.accept_mimetypes.best == "application/json" or request.is_json
    if wants_json:
        return jsonify({"ok": True})
    next_page = data.get("_next") or "thank-you.html"
    return redirect(f"/{next_page}")

# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------
@app.errorhandler(400)
def bad_request(e):
    return jsonify({"ok": False, "error": "Bad request."}), 400

@app.errorhandler(403)
def forbidden(e):
    return jsonify({"ok": False, "error": "Forbidden."}), 403

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Not found."}), 404
    return send_from_directory(SITE_DIR, "404.html"), 404

@app.errorhandler(413)
def too_large(e):
    return jsonify({"ok": False, "error": f"File is larger than {MAX_UPLOAD_MB} MB."}), 413

@app.errorhandler(429)
def rate_limited(e):
    return jsonify({"ok": False, "error": "Too many requests. Please try again later."}), 429

@app.errorhandler(500)
def server_error(e):
    logger.exception("Internal server error")
    return jsonify({"ok": False, "error": "An internal error occurred."}), 500


# ---------------------------------------------------------------------------
# Core endpoints
# ---------------------------------------------------------------------------
@app.route("/health")
def health():
    try:
        conn = db.get_db()
        conn.execute("SELECT 1")
        conn.close()
        return jsonify({"status": "ok", "database": "connected"})
    except Exception:
        return jsonify({"status": "error", "database": "disconnected"}), 503

@app.route("/")
def home():
    return send_from_directory(SITE_DIR, "index.html")

_LONG_CACHE_EXTENSIONS = (
    ".css", ".js", ".mjs", ".woff", ".woff2", ".ttf", ".eot",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
)

@app.route("/<path:filename>")
def site_files(filename):
    if filename.startswith(("admin/", "data/")):
        abort(404)
    full_path = os.path.join(SITE_DIR, filename)
    if os.path.isfile(full_path):
        if filename.endswith(_LONG_CACHE_EXTENSIONS):
            resp = send_from_directory(SITE_DIR, filename)
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return resp
        resp = send_from_directory(SITE_DIR, filename, max_age=0)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp
    return send_from_directory(SITE_DIR, "404.html"), 404

@app.route("/api/contact", methods=["POST"])
def api_contact():
    ip = _client_ip()
    if _rate_limiter.is_limited(f"contact:{ip}", max_requests=10, window_seconds=60):
        abort(429)

    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    if data.get("_honey"):
        return jsonify({"ok": True})

    name = (data.get("name") or "").strip()
    message = (data.get("message") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()

    if not _validate_name(name) or not message:
        return jsonify({"ok": False, "error": "Name and message are required."}), 400
    if not _validate_email(email):
        return jsonify({"ok": False, "error": "Invalid email address."}), 400
    if not _validate_phone(phone):
        return jsonify({"ok": False, "error": "Invalid phone number."}), 400

    conn = db.get_db()
    conn.execute(
        "INSERT INTO inquiries (kind, name, company, phone, email, message, extra_json, status, created_at) "
        "VALUES ('contact', %s, %s, %s, %s, %s, NULL, 'new', %s)",
        (name, data.get("company", ""), phone, email, message, now_iso()),
    )
    conn.commit()
    conn.close()
    return _respond_ok(data)

@app.route("/api/quote", methods=["POST"])
def api_quote():
    ip = _client_ip()
    if _rate_limiter.is_limited(f"quote:{ip}", max_requests=5, window_seconds=60):
        abort(429)

    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    if data.get("_honey"):
        return jsonify({"ok": True})

    name = (data.get("contact_name") or data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()

    if not _validate_name(name):
        return jsonify({"ok": False, "error": "Contact name is required."}), 400
    if not _validate_email(email):
        return jsonify({"ok": False, "error": "Invalid email address."}), 400
    if not _validate_phone(phone):
        return jsonify({"ok": False, "error": "Invalid phone number."}), 400

    known = {
        "contact_name", "company", "company_organisation", "phone", "email",
        "message", "_kind", "_next", "_honey", "attachment"
    }
    extra = {k: v for k, v in data.items() if k not in known}
    company = (data.get("company") or data.get("company_organisation") or "").strip()

    attachment_filename = attachment_original_name = None
    attachment_size_bytes = None
    s3_object_key = None
    upload = request.files.get("attachment")
    
    if upload and upload.filename:
        try:
            res, orig, size = _save_quote_attachment(upload)
            if _get_s3_client():
                s3_object_key = res
            else:
                attachment_filename = res
            attachment_original_name = orig
            attachment_size_bytes = size
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    conn = db.get_db()
    conn.execute(
        "INSERT INTO inquiries "
        "(kind, name, company, phone, email, message, extra_json, status, created_at, "
        "attachment_filename, attachment_original_name, attachment_size_bytes, s3_object_key) "
        "VALUES ('quote', %s, %s, %s, %s, %s, %s, 'new', %s, %s, %s, %s, %s)",
        (
            name, company, phone, email, data.get("message", ""),
            json.dumps(extra, ensure_ascii=False), now_iso(),
            attachment_filename, attachment_original_name, attachment_size_bytes, s3_object_key
        ),
    )
    conn.commit()
    conn.close()
    return _respond_ok(data)


def _hash_visitor_id(raw_visitor_id):
    return hashlib.sha256(raw_visitor_id.encode("utf-8")).hexdigest()

@app.route("/api/visitor-register", methods=["POST"])
def api_track_visitor():
    ip = _client_ip()
    if _rate_limiter.is_limited(f"visit:{ip}", max_requests=30, window_seconds=60):
        abort(429)

    ua = request.headers.get("User-Agent", "").lower()
    if not ua or "bot" in ua or "crawler" in ua or "spider" in ua:
        count, mode = db.get_display_visitor_count()
        return jsonify({"ok": True, "new_visitor": False, "count": count, "mode": mode})

    data = request.get_json(silent=True) or {}
    visitor_id = (data.get("visitor_id") or "").strip()
    
    cookie_id = request.cookies.get("ladli_visitor_id")
    if not visitor_id and cookie_id:
        visitor_id = cookie_id

    if not visitor_id or len(visitor_id) > 128:
        return jsonify({"ok": False, "error": "Invalid visitor id."}), 400

    token = _hash_visitor_id(visitor_id)
    is_new_visitor, _unique_total = db.record_unique_visitor(token)
    count, mode = db.get_display_visitor_count()
    
    res = jsonify({"ok": True, "new_visitor": is_new_visitor, "count": count, "mode": mode})
    res.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    
    if not request.cookies.get("ladli_visitor_id"):
        res.set_cookie("ladli_visitor_id", visitor_id, max_age=31536000, httponly=True, secure=app.config["SESSION_COOKIE_SECURE"], samesite="Lax")
        
    return res

@app.route("/api/visitor-count")
def api_visitor_count():
    count, mode = db.get_display_visitor_count()
    res = jsonify({"count": count, "mode": mode})
    res.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    res.headers["Pragma"] = "no-cache"
    res.headers["Expires"] = "0"
    return res

# ---------------------------------------------------------------------------
# Admin API
# ---------------------------------------------------------------------------
@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    ip_address = _client_ip()
    if _rate_limiter.is_limited(f"login:{ip_address}", max_requests=10, window_seconds=60):
        abort(429)

    data = request.get_json(silent=True) or request.form.to_dict()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"ok": False, "error": "Invalid username or password."}), 401

    if db.is_locked_out(username, ip_address):
        return jsonify({
            "ok": False,
            "error": f"Too many failed attempts. Try again in {db.LOCKOUT_WINDOW_MINUTES} minutes.",
        }), 429

    conn = db.get_db()
    row = conn.execute("SELECT * FROM admin_users WHERE username = %s", (username,)).fetchone()
    conn.close()

    if not row or not check_password_hash(row["password_hash"], password):
        db.record_login_attempt(username, ip_address, success=False)
        logger.warning(f"Failed login attempt for username {username} from {ip_address}")
        error = "Invalid username or password."
        if row:
            changed_ago = db.find_password_in_history(username, password, row["password_hash"])
            if changed_ago:
                error = f"This password was changed {changed_ago}. Please use your newest password."
            else:
                error = "Wrong password! Please check your credentials and try again."
        return jsonify({"ok": False, "error": error}), 401

    db.record_login_attempt(username, ip_address, success=True)
    db.clear_login_attempts(username, ip_address)

    session.clear()
    session["admin_user"] = username
    session.permanent = True
    logger.info(f"Successful login for username {username} from {ip_address}")
    
    return jsonify({
        "ok": True,
        "username": username,
        "must_change_password": bool(row["must_change_password"]),
        "security_setup_completed": bool(row.get("security_setup_completed", 0)),
    })

@app.route("/api/admin/logout", methods=["POST"])
def api_admin_logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/admin/me")
def api_admin_me():
    if session.get("admin_user"):
        conn = db.get_db()
        row = conn.execute(
            "SELECT must_change_password, security_setup_completed FROM admin_users WHERE username = %s",
            (session["admin_user"],),
        ).fetchone()
        conn.close()
        return jsonify({
            "logged_in": True,
            "username": session["admin_user"],
            "must_change_password": bool(row["must_change_password"]) if row else False,
            "security_setup_completed": bool(row.get("security_setup_completed", 0)) if row else False,
        })
    return jsonify({"logged_in": False})


def _password_is_strong(pwd):
    return len(pwd.strip()) >= 8

@app.route("/api/admin/change-password", methods=["POST"])
@require_admin
def api_admin_change_password():
    data = request.get_json(silent=True) or {}
    current = data.get("current_password") or ""
    new_password = data.get("new_password") or ""

    if not _password_is_strong(new_password):
        return jsonify({"ok": False, "error": "New password must be at least 8 characters."}), 400

    conn = db.get_db()
    row = conn.execute(
        "SELECT * FROM admin_users WHERE username = %s", (session["admin_user"],)
    ).fetchone()
    
    if not row or not check_password_hash(row["password_hash"], current):
        conn.close()
        return jsonify({"ok": False, "error": "Current password is incorrect."}), 400

    if check_password_hash(row["password_hash"], new_password):
        conn.close()
        return jsonify({"ok": False, "error": "New password must be different from the current one."}), 400

    conn.close()
    db.set_password(session["admin_user"], new_password)
    logger.info(f"Password changed for user {session['admin_user']}")
    session.clear()
    return jsonify({"ok": True})

# ---------------------------------------------------------------------------
# Security Questions & Recovery API
# ---------------------------------------------------------------------------

@app.route("/api/admin/security-questions")
def api_security_questions():
    """Public — returns available security questions for recovery page."""
    questions = db.get_security_questions()
    return jsonify([{"id": q["id"], "question": q["question"]} for q in questions])

@app.route("/api/admin/security-setup-status")
@require_admin
def api_security_setup_status():
    conn = db.get_db()
    row = conn.execute("SELECT id, security_setup_completed FROM admin_users WHERE username = %s", (session["admin_user"],)).fetchone()
    conn.close()
    return jsonify({"completed": bool(row["security_setup_completed"]) if row else False})

@app.route("/api/admin/setup-security-questions", methods=["POST"])
@require_admin
def api_setup_security_questions():
    data = request.get_json(silent=True) or {}
    answers = data.get("answers", [])
    if len(answers) != 3:
        return jsonify({"ok": False, "error": "Exactly 3 questions required."}), 400
    question_ids = [a["question_id"] for a in answers]
    if len(set(question_ids)) != 3:
        return jsonify({"ok": False, "error": "All questions must be different."}), 400
    for a in answers:
        if not a.get("answer") or len(a["answer"].strip()) < 2:
            return jsonify({"ok": False, "error": "All answers must be at least 2 characters."}), 400
    
    conn = db.get_db()
    row = conn.execute("SELECT id, security_setup_completed FROM admin_users WHERE username = %s", (session["admin_user"],)).fetchone()
    conn.close()
    if not row:
        return jsonify({"ok": False, "error": "Account not found."}), 404
    if row["security_setup_completed"]:
        return jsonify({"ok": False, "error": "Security questions already configured. Use the change flow."}), 400
    
    hashed_answers = []
    for a in answers:
        normalized = db.normalize_answer(a["answer"])
        hashed_answers.append({"question_id": a["question_id"], "answer_hash": generate_password_hash(normalized)})
    db.save_security_answers(row["id"], hashed_answers)
    logger.info(f"Security questions configured for user {session['admin_user']}")
    return jsonify({"ok": True})

@app.route("/api/admin/change-security-questions", methods=["POST"])
@require_admin
def api_change_security_questions():
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password", "")
    current_answers = data.get("current_answers", [])
    new_answers = data.get("new_answers", [])
    
    conn = db.get_db()
    row = conn.execute("SELECT * FROM admin_users WHERE username = %s", (session["admin_user"],)).fetchone()
    conn.close()
    if not row or not check_password_hash(row["password_hash"], current_password):
        return jsonify({"ok": False, "error": "Current password is incorrect."}), 400
    
    if not db.verify_security_answers(row["id"], current_answers):
        return jsonify({"ok": False, "error": "Current security answers are incorrect."}), 400
    
    if len(new_answers) != 3:
        return jsonify({"ok": False, "error": "Exactly 3 questions required."}), 400
    new_qids = [a["question_id"] for a in new_answers]
    if len(set(new_qids)) != 3:
        return jsonify({"ok": False, "error": "All questions must be different."}), 400
    
    hashed_answers = []
    for a in new_answers:
        normalized = db.normalize_answer(a["answer"])
        hashed_answers.append({"question_id": a["question_id"], "answer_hash": generate_password_hash(normalized)})
    
    conn = db.get_db()
    conn.execute("DELETE FROM admin_security_answers WHERE admin_user_id = %s", (row["id"],))
    conn.commit()
    conn.close()
    
    db.save_security_answers(row["id"], hashed_answers)
    logger.info(f"Security questions changed for user {session['admin_user']}")
    return jsonify({"ok": True})

@app.route("/api/admin/get-user-questions", methods=["POST"])
def api_get_user_questions():
    """Returns the 3 security questions for a given username (for recovery)."""
    ip = _client_ip()
    if _rate_limiter.is_limited(f"recovery:{ip}", max_requests=5, window_seconds=1800):
        abort(429)

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    
    if db.is_recovery_locked_out(username or "__empty__", ip):
        return jsonify({"ok": False, "error": "Too many attempts. Please try again later."}), 429
    
    if not username:
        return jsonify({"ok": False, "error": "If that account exists, security questions will be shown."}), 400
    
    admin = db.find_admin_by_username_or_email(username)
    if not admin or not admin.get("security_setup_completed"):
        fake_qs = db.get_security_questions()[:3]
        return jsonify({"ok": True, "questions": [{"question_id": q["id"], "question": q["question"]} for q in fake_qs]})
    
    questions = db.get_user_security_questions(admin["id"])
    return jsonify({"ok": True, "questions": questions})

@app.route("/api/admin/verify-security-answers", methods=["POST"])
def api_verify_security_answers():
    """Verify security answers and issue a reset token."""
    ip = _client_ip()
    if _rate_limiter.is_limited(f"recovery_verify:{ip}", max_requests=5, window_seconds=1800):
        abort(429)
        
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    answers = data.get("answers", [])
    
    if db.is_recovery_locked_out(username or "__empty__", ip):
        return jsonify({"ok": False, "error": "Too many attempts. Please try again later."}), 429
    
    generic_error = "Verification failed. Please check your answers and try again."
    
    admin = db.find_admin_by_username_or_email(username)
    if not admin:
        db.record_recovery_attempt(username or "__unknown__", ip, False)
        return jsonify({"ok": False, "error": generic_error}), 400
    
    if not db.verify_security_answers(admin["id"], answers):
        db.record_recovery_attempt(username, ip, False)
        logger.warning(f"Failed recovery attempt for '{username}' from {ip}")
        return jsonify({"ok": False, "error": generic_error}), 400
    
    db.record_recovery_attempt(username, ip, True)
    token = db.create_reset_token(username)
    logger.info(f"Password reset token issued for '{username}' from {ip}")
    return jsonify({"ok": True, "reset_token": token})

@app.route("/api/admin/reset-password-with-token", methods=["POST"])
def api_reset_password_with_token():
    """Set a new password using a reset token."""
    ip = _client_ip()
    if _rate_limiter.is_limited(f"reset_token:{ip}", max_requests=5, window_seconds=1800):
        abort(429)
        
    data = request.get_json(silent=True) or {}
    token = data.get("token", "")
    new_password = data.get("new_password", "")
    
    if not _password_is_strong(new_password):
        return jsonify({"ok": False, "error": "Password must be at least 8 characters."}), 400
    
    username = db.validate_reset_token(token)
    if not username:
        return jsonify({"ok": False, "error": "Invalid or expired reset token."}), 400
    
    db.set_password(username, new_password)
    db.invalidate_reset_token(token)
    db.cleanup_expired_tokens()
    
    logger.info(f"Password reset completed for '{username}'")
    return jsonify({"ok": True})

# ---------------------------------------------------------------------------
# Inquiries API
# ---------------------------------------------------------------------------
@app.route("/api/admin/inquiries")
@require_admin
def api_admin_inquiries():
    kind = request.args.get("kind", "")
    status = request.args.get("status", "")

    query = "SELECT * FROM inquiries WHERE 1=1"
    params = []
    if kind in ("contact", "quote"):
        query += " AND kind = %s"
        params.append(kind)
    if status in ("new", "contacted", "closed"):
        query += " AND status = %s"
        params.append(status)
    query += " ORDER BY created_at DESC"

    conn = db.get_db()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    out = []
    for r in rows:
        extra = {}
        if r["extra_json"]:
            try:
                extra = json.loads(r["extra_json"])
            except Exception:
                extra = {}
        out.append({
            "id": r["id"],
            "kind": r["kind"],
            "name": r["name"],
            "company": r["company"],
            "phone": r["phone"],
            "email": r["email"],
            "message": r["message"],
            "extra": extra,
            "status": r["status"],
            "created_at": r["created_at"],
            "created_at_display": display_date(r["created_at"]),
            "has_attachment": bool(r["attachment_filename"] or r.get("s3_object_key")),
            "attachment_original_name": r["attachment_original_name"],
            "attachment_size_bytes": r["attachment_size_bytes"],
        })
    return jsonify(out)

@app.route("/api/admin/inquiries/<int:inquiry_id>/status", methods=["POST"])
@require_admin
def api_admin_update_status(inquiry_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in ("new", "contacted", "closed"):
        return jsonify({"ok": False, "error": "Invalid status."}), 400

    conn = db.get_db()
    cur = conn.execute("UPDATE inquiries SET status = %s WHERE id = %s", (status, inquiry_id))
    conn.commit()
    updated = cur.rowcount
    conn.close()
    if not updated:
        return jsonify({"ok": False, "error": "Inquiry not found."}), 404
    return jsonify({"ok": True})

@app.route("/api/admin/inquiries/<int:inquiry_id>/attachment")
@require_admin
def api_admin_inquiry_attachment(inquiry_id):
    conn = db.get_db()
    row = conn.execute("SELECT * FROM inquiries WHERE id = %s", (inquiry_id,)).fetchone()
    conn.close()
    
    if not row or not (row["attachment_filename"] or row.get("s3_object_key")):
        abort(404)
        
    download_name = row["attachment_original_name"] or row["attachment_filename"] or "attachment.pdf"
    
    if row.get("s3_object_key"):
        s3 = _get_s3_client()
        if s3:
            url = s3.generate_presigned_url("get_object", Params={"Bucket": S3_BUCKET, "Key": row["s3_object_key"]}, ExpiresIn=300)
            return redirect(url)
            
    return send_from_directory(
        ATTACHMENT_DIR, row["attachment_filename"], as_attachment=True, download_name=download_name
    )

@app.route("/api/admin/inquiries/<int:inquiry_id>", methods=["DELETE"])
@require_admin
def api_admin_delete_inquiry(inquiry_id):
    conn = db.get_db()
    row = conn.execute("SELECT * FROM inquiries WHERE id = %s", (inquiry_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "Inquiry not found."}), 404
        
    if row.get("s3_object_key"):
        s3 = _get_s3_client()
        if s3:
            try:
                s3.delete_object(Bucket=S3_BUCKET, Key=row["s3_object_key"])
            except Exception as e:
                logger.error(f"Failed to delete S3 object: {e}")
                
    if row["attachment_filename"]:
        file_path = os.path.join(ATTACHMENT_DIR, row["attachment_filename"])
        if os.path.isfile(file_path):
            os.remove(file_path)
            
    conn.execute("DELETE FROM inquiries WHERE id = %s", (inquiry_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ---------------------------------------------------------------------------
# Visitors API
# ---------------------------------------------------------------------------
@app.route("/api/admin/visitors")
@require_admin
def api_admin_visitors():
    row = db.get_visitor_stats()
    unique_count = db.get_unique_visitor_count()
    return jsonify({
        "unique_count": unique_count,
        "manual_count": row["manual_count"],
        "mode": row["mode"],
        "updated_at": row["updated_at"],
    })

@app.route("/api/admin/visitors", methods=["POST"])
@require_admin
def api_admin_update_visitors():
    data = request.get_json(silent=True) or {}
    if "mode" in data:
        mode = data.get("mode")
        if mode not in ("auto", "manual"):
            return jsonify({"ok": False, "error": "Mode must be 'auto' or 'manual'."}), 400
        db.set_visitor_mode(mode)
    if "manual_count" in data:
        try:
            manual_count = int(data.get("manual_count"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Manual count must be a whole number."}), 400
        if manual_count < 0:
            return jsonify({"ok": False, "error": "Manual count cannot be negative."}), 400
        db.set_manual_count(manual_count)

    row = db.get_visitor_stats()
    unique_count = db.get_unique_visitor_count()
    return jsonify({
        "ok": True,
        "unique_count": unique_count,
        "manual_count": row["manual_count"],
        "mode": row["mode"],
        "updated_at": row["updated_at"],
    })

# ---------------------------------------------------------------------------
# Admin UI Routes
# ---------------------------------------------------------------------------
@app.route("/admin")
@app.route("/admin/")
def admin_root():
    if session.get("admin_user"):
        return send_from_directory(ADMIN_DIR, "dashboard.html")
    return redirect("/admin/login")

@app.route("/admin/login")
def admin_login_page():
    if session.get("admin_user"):
        return redirect("/admin")
    return send_from_directory(ADMIN_DIR, "login.html")

@app.route("/admin/settings")
def admin_settings_page():
    if not session.get("admin_user"):
        return redirect("/admin/login")
    return send_from_directory(ADMIN_DIR, "settings.html")

@app.route("/admin/visitors")
def admin_visitors_page():
    if not session.get("admin_user"):
        return redirect("/admin/login")
    return send_from_directory(ADMIN_DIR, "visitors.html")

@app.route("/admin/forgot-password")
def admin_forgot_password():
    if session.get("admin_user"):
        return redirect("/admin")
    return send_from_directory(ADMIN_DIR, "forgot_password.html")

@app.route("/admin/setup-security")
def admin_security_setup_page():
    if not session.get("admin_user"):
        return redirect("/admin/login")
    return send_from_directory(ADMIN_DIR, "setup_security.html")

@app.route("/admin/assets/<path:filename>")
def admin_assets(filename):
    return send_from_directory(os.path.join(ADMIN_DIR, "assets"), filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="127.0.0.1", port=port, debug=debug)