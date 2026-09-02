"""
db.py — PostgreSQL data-access layer for the LADLI backend.

Supports PostgreSQL through any of three drivers (with connection
pooling, dictionary rows, and automatic schema initialization),
auto-detected at import time in this order:

  - psycopg2 (psycopg2-binary)     — preferred when installed (Linux prod)
  - psycopg  (psycopg 3, [binary]) — modern fallback for newer Pythons
  - pg8000                         — pure-Python fallback; installs on ANY
                                     Python/platform (used on Windows dev
                                     machines where neither binary driver
                                     ships a matching wheel)

Connection settings come from DATABASE_URL or the individual PG*
environment variables.
"""

import os
import re
import secrets
import string
import datetime
import uuid
import hashlib
from urllib.parse import urlparse
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import psycopg2
    from psycopg2 import pool
    from psycopg2.extras import RealDictCursor
    PG_DRIVER = "psycopg2"
except ImportError:
    try:
        import psycopg  # psycopg 3
        from psycopg.rows import dict_row
        PG_DRIVER = "psycopg3"
    except ImportError:
        try:
            from pg8000 import dbapi as pg8000_dbapi  # pure Python — works everywhere
            PG_DRIVER = "pg8000"
        except ImportError:
            PG_DRIVER = None

# Kept for backwards compatibility with existing checks.
PSYCOPG2_AVAILABLE = PG_DRIVER is not None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")
PGHOST = os.environ.get("PGHOST")
PGPORT = os.environ.get("PGPORT", "5432")
PGDATABASE = os.environ.get("PGDATABASE")
PGUSER = os.environ.get("PGUSER")
PGPASSWORD = os.environ.get("PGPASSWORD")
PGSSLMODE = os.environ.get("PGSSLMODE", "prefer")

_pg_pool = None

def is_postgres_configured():
    """Returns True if PostgreSQL connection parameters are configured."""
    return bool(DATABASE_URL or (PGHOST and PGDATABASE and PGUSER))

def get_pg_connection_params():
    """Parses DATABASE_URL or individual PG* env vars into a connection dict."""
    if DATABASE_URL:
        # Handle postgres:// vs postgresql:// protocol
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql://" + url[11:]
        parsed = urlparse(url)
        return {
            "dbname": parsed.path.lstrip("/"),
            "user": parsed.username,
            "password": parsed.password,
            "host": parsed.hostname,
            "port": parsed.port or 5432,
            "sslmode": PGSSLMODE if parsed.hostname not in ("localhost", "127.0.0.1") else "prefer",
        }
    return {
        "dbname": PGDATABASE,
        "user": PGUSER,
        "password": PGPASSWORD,
        "host": PGHOST,
        "port": int(PGPORT) if PGPORT else 5432,
        "sslmode": PGSSLMODE,
    }

def _get_pg_pool():
    global _pg_pool
    # Connection pooling is only used with psycopg2; with psycopg 3 the app
    # opens short-lived direct connections instead (identical behaviour,
    # no extra psycopg_pool dependency needed).
    if _pg_pool is None and PG_DRIVER == "psycopg2" and is_postgres_configured():
        params = get_pg_connection_params()
        _pg_pool = pool.SimpleConnectionPool(1, 20, **params)
    return _pg_pool

# ---------------------------------------------------------------------------
# Unified Database Cursor & Connection Wrapper
# ---------------------------------------------------------------------------
class PostgresCursorWrapper:
    """Wraps the DB driver cursor to provide uniform dict-row access and rowcount."""

    def __init__(self, cursor, conn):
        self._cursor = cursor
        self._conn = conn

    def execute(self, sql, params=None):
        # Translate '?' placeholders to '%s' if necessary
        formatted_sql = sql
        if "?" in formatted_sql and "%s" not in formatted_sql:
            formatted_sql = formatted_sql.replace("?", "%s")
        
        # We don't need SQLite translations anymore, but kept for compatibility just in case
        formatted_sql = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO\s+(\w+)", r"INSERT INTO \1", formatted_sql, flags=re.IGNORECASE)
        
        if params is not None:
            if isinstance(params, (list, tuple)):
                self._cursor.execute(formatted_sql, params)
            else:
                self._cursor.execute(formatted_sql, (params,))
        else:
            self._cursor.execute(formatted_sql)
        return self

    def _to_dict(self, row):
        if row is None:
            return None
        if isinstance(row, dict):
            return dict(row)
        # pg8000 (and plain cursors) return sequences — build dicts from
        # the cursor description so callers always get dict rows.
        columns = [d[0] for d in (self._cursor.description or [])]
        return dict(zip(columns, row))

    def fetchone(self):
        return self._to_dict(self._cursor.fetchone())

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [self._to_dict(r) for r in rows] if rows else []

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class PostgresConnectionWrapper:
    """Wraps a psycopg2 connection."""

    def __init__(self, raw_conn, from_pool=False):
        self._conn = raw_conn
        self._from_pool = from_pool
        self._closed = False

    def execute(self, sql, params=None):
        if PG_DRIVER == "psycopg2":
            cursor = self._conn.cursor(cursor_factory=RealDictCursor)
        elif PG_DRIVER == "psycopg3":
            cursor = self._conn.cursor(row_factory=dict_row)
        else:  # pg8000 — plain cursor; wrapper converts rows to dicts
            cursor = self._conn.cursor()
        wrapper = PostgresCursorWrapper(cursor, self)
        wrapper.execute(sql, params)
        return wrapper

    def executescript(self, script):
        if PG_DRIVER == "pg8000":
            # pg8000 executes one statement at a time; the schema script
            # contains no procedural bodies, so splitting on ';' is safe.
            cursor = self._conn.cursor()
            try:
                for statement in script.split(";"):
                    if statement.strip():
                        cursor.execute(statement)
            finally:
                cursor.close()
            self._conn.commit()
            return
        with self._conn.cursor() as cur:
            cur.execute(script)
        self._conn.commit()

    def commit(self):
        if not self._closed:
            self._conn.commit()

    def rollback(self):
        if not self._closed:
            self._conn.rollback()

    def close(self):
        if not self._closed:
            self._closed = True
            if self._from_pool and _pg_pool is not None:
                _pg_pool.putconn(self._conn)
            else:
                self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self.close()

def _pg8000_connect(params):
    """Opens a pg8000 connection, translating libpq-style params."""
    kwargs = {
        "user": params.get("user"),
        "database": params.get("dbname"),
        "port": int(params.get("port") or 5432),
    }
    if params.get("password"):
        kwargs["password"] = params["password"]
    host = params.get("host")
    if host and host.startswith("/"):
        # Unix-socket directory (libpq style) → full socket path for pg8000
        kwargs["unix_sock"] = f"{host}/.s.PGSQL.{kwargs['port']}"
    elif host:
        kwargs["host"] = host
    sslmode = (params.get("sslmode") or "").lower()
    if sslmode in ("require", "verify-ca", "verify-full"):
        kwargs["ssl_context"] = True
    return pg8000_dbapi.connect(**kwargs)

def get_db():
    """
    Returns an active database connection wrapper.
    Connects to PostgreSQL with whichever driver is installed
    (psycopg2 preferred, then psycopg 3, then pure-Python pg8000).
    """
    if PG_DRIVER and is_postgres_configured():
        try:
            pool_instance = _get_pg_pool()
            if pool_instance:
                conn = pool_instance.getconn()
                return PostgresConnectionWrapper(conn, from_pool=True)
            params = get_pg_connection_params()
            if PG_DRIVER == "psycopg2":
                conn = psycopg2.connect(**params)
            elif PG_DRIVER == "psycopg3":
                conn = psycopg.connect(**params)
            else:
                conn = _pg8000_connect(params)
            return PostgresConnectionWrapper(conn, from_pool=False)
        except Exception as e:
            raise RuntimeError(f"Could not connect to PostgreSQL database: {e}")

    raise RuntimeError(
        "No PostgreSQL driver is available or the database is not configured. "
        "Install 'psycopg2-binary', 'psycopg[binary]', or 'pg8000' and "
        "set DATABASE_URL or PGHOST/PGDATABASE/PGUSER."
    )

# ---------------------------------------------------------------------------
# Database Schema Definitions
# ---------------------------------------------------------------------------
POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users (
    id                       SERIAL PRIMARY KEY,
    username                 VARCHAR(150) UNIQUE NOT NULL,
    password_hash            TEXT NOT NULL,
    created_at               VARCHAR(50) NOT NULL,
    must_change_password     SMALLINT NOT NULL DEFAULT 0,
    email                    VARCHAR(255),
    security_setup_completed SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS password_history (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(150) NOT NULL,
    password_hash TEXT NOT NULL,
    changed_at    VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id           SERIAL PRIMARY KEY,
    username     VARCHAR(150) NOT NULL,
    ip_address   VARCHAR(100) NOT NULL,
    attempted_at VARCHAR(50) NOT NULL,
    success      SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS inquiries (
    id                       SERIAL PRIMARY KEY,
    kind                     VARCHAR(50) NOT NULL,
    name                     TEXT,
    company                  TEXT,
    phone                    TEXT,
    email                    TEXT,
    message                  TEXT,
    extra_json               TEXT,
    status                   VARCHAR(50) NOT NULL DEFAULT 'new',
    created_at               VARCHAR(50) NOT NULL,
    attachment_filename      TEXT,
    attachment_original_name TEXT,
    attachment_size_bytes    BIGINT,
    s3_object_key            TEXT
);

CREATE TABLE IF NOT EXISTS visitor_stats (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    manual_count INTEGER NOT NULL DEFAULT 0,
    mode         VARCHAR(50) NOT NULL DEFAULT 'auto',
    updated_at   VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS unique_visitors (
    visitor_token VARCHAR(128) PRIMARY KEY,
    first_seen    VARCHAR(50) NOT NULL,
    last_seen     VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS security_questions (
    id       SERIAL PRIMARY KEY,
    question TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS admin_security_answers (
    id            SERIAL PRIMARY KEY,
    admin_user_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
    question_id   INTEGER NOT NULL REFERENCES security_questions(id),
    answer_hash   TEXT NOT NULL,
    created_at    VARCHAR(50) NOT NULL,
    UNIQUE(admin_user_id, question_id)
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id             SERIAL PRIMARY KEY,
    username       VARCHAR(150) NOT NULL,
    token_hash     TEXT NOT NULL UNIQUE,
    created_at     VARCHAR(50) NOT NULL,
    expires_at     VARCHAR(50) NOT NULL,
    used           SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS recovery_attempts (
    id           SERIAL PRIMARY KEY,
    username     VARCHAR(150) NOT NULL,
    ip_address   VARCHAR(100) NOT NULL,
    attempted_at VARCHAR(50) NOT NULL,
    success      SMALLINT NOT NULL DEFAULT 0
);
"""

def seed_security_questions(conn):
    questions = [
        "What is the name of your first pet?",
        "In what city were you born?",
        "What is your mother's maiden name?",
        "What was the name of your first school?",
        "What is your favorite movie?",
        "What was the make of your first car?",
        "What is your favorite book?",
        "What street did you grow up on?",
        "What is the name of your childhood best friend?",
        "What was your first job title?"
    ]
    for q in questions:
        conn.execute("INSERT INTO security_questions (question) VALUES (%s) ON CONFLICT (question) DO NOTHING", (q,))

def _migrate(conn):
    """Ensures default visitor_stats record exists and runs migrations."""
    now = datetime.datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO visitor_stats (id, manual_count, mode, updated_at) "
        "VALUES (1, 0, 'auto', %s) ON CONFLICT (id) DO NOTHING",
        (now,),
    )
    conn.execute("UPDATE visitor_stats SET mode = 'auto' WHERE mode = 'real'")
    seed_security_questions(conn)
    conn.commit()

def generate_strong_password(length=16):
    """Generates a cryptographically strong random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in pwd)
            and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd)
            and any(c in "!@#$%^&*-_=+" for c in pwd)
        ):
            return pwd

def init_db(default_username="admin", default_password=None, default_email=None):
    """Initializes the database schema and creates initial admin if missing."""
    conn = get_db()
    conn.executescript(POSTGRES_SCHEMA)

    _migrate(conn)

    existing_row = conn.execute("SELECT COUNT(*) AS c FROM admin_users").fetchone()
    existing = existing_row["c"] if existing_row else 0
    if existing == 0:
        generated = default_password is None
        password = default_password or generate_strong_password()
        now = datetime.datetime.utcnow().isoformat()
        password_hash = generate_password_hash(password)

        conn.execute(
            "INSERT INTO admin_users (username, password_hash, created_at, must_change_password, email) "
            "VALUES (%s, %s, %s, %s, %s)",
            (default_username, password_hash, now, 1 if generated else 0, default_email),
        )
        conn.execute(
            "INSERT INTO password_history (username, password_hash, changed_at) VALUES (%s, %s, %s)",
            (default_username, password_hash, now),
        )
        conn.commit()
        print("=" * 64)
        print(f" First run (PostgreSQL): an admin account was created.")
        print(f"   Username: {default_username}")
        if generated:
            print(f"   Password: {password}")
            print(" This password was randomly generated and is shown ONLY")
            print(" here, once. Save it now. You will be required to change")
            print(" it the moment you log in at /admin.")
        else:
            print(" Password: (the value of ADMIN_PASSWORD in your .env)")
        print("=" * 64)
    conn.commit()
    conn.close()

def _humanize_delta(changed_at_iso):
    """'3 hours ago' / '2 days ago' style label for a past ISO timestamp."""
    try:
        changed_at = datetime.datetime.fromisoformat(changed_at_iso)
    except Exception:
        return "recently"
    delta = datetime.datetime.utcnow() - changed_at
    seconds = max(delta.total_seconds(), 0)
    if seconds < 3600:
        minutes = max(int(seconds // 60), 1)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = int(seconds // 86400)
    return f"{days} day{'s' if days != 1 else ''} ago"

def record_password_history(username, password_hash):
    conn = get_db()
    now = datetime.datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO password_history (username, password_hash, changed_at) VALUES (%s, %s, %s)",
        (username, password_hash, now),
    )
    # Keep only the last 5 hashes per account
    conn.execute(
        "DELETE FROM password_history WHERE username = %s AND id NOT IN "
        "(SELECT id FROM password_history WHERE username = %s ORDER BY id DESC LIMIT 5)",
        (username, username),
    )
    conn.commit()
    conn.close()

def find_password_in_history(username, plaintext_password, current_hash):
    conn = get_db()
    rows = conn.execute(
        "SELECT password_hash, changed_at FROM password_history "
        "WHERE username = %s ORDER BY id DESC",
        (username,),
    ).fetchall()
    conn.close()
    for row in rows:
        if row["password_hash"] == current_hash:
            continue
        if check_password_hash(row["password_hash"], plaintext_password):
            return _humanize_delta(row["changed_at"])
    return None

# ---------------------------------------------------------------------------
# Login lockout (brute-force protection)
# ---------------------------------------------------------------------------
LOCKOUT_MAX_ATTEMPTS = 5
LOCKOUT_WINDOW_MINUTES = 15

def record_login_attempt(username, ip_address, success):
    conn = get_db()
    now = datetime.datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO login_attempts (username, ip_address, attempted_at, success) VALUES (%s, %s, %s, %s)",
        (username.lower(), ip_address, now, 1 if success else 0),
    )
    cutoff = (
        datetime.datetime.utcnow() - datetime.timedelta(minutes=LOCKOUT_WINDOW_MINUTES)
    ).isoformat()
    conn.execute("DELETE FROM login_attempts WHERE attempted_at < %s", (cutoff,))
    conn.commit()
    conn.close()

def is_locked_out(username, ip_address):
    cutoff = (
        datetime.datetime.utcnow() - datetime.timedelta(minutes=LOCKOUT_WINDOW_MINUTES)
    ).isoformat()
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM login_attempts "
        "WHERE username = %s AND ip_address = %s AND success = 0 AND attempted_at >= %s",
        (username.lower(), ip_address, cutoff),
    ).fetchone()
    conn.close()
    return (row["c"] if row else 0) >= LOCKOUT_MAX_ATTEMPTS

def clear_login_attempts(username, ip_address):
    conn = get_db()
    conn.execute(
        "DELETE FROM login_attempts WHERE username = %s AND ip_address = %s",
        (username.lower(), ip_address),
    )
    conn.commit()
    conn.close()

def clear_all_login_attempts_for_user(username):
    conn = get_db()
    conn.execute(
        "DELETE FROM login_attempts WHERE username = %s",
        (username.lower(),),
    )
    conn.commit()
    conn.close()

def set_must_change_password(username, value=True):
    conn = get_db()
    conn.execute(
        "UPDATE admin_users SET must_change_password = %s WHERE username = %s",
        (1 if value else 0, username),
    )
    conn.commit()
    conn.close()

def find_admin_by_username_or_email(identifier):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM admin_users WHERE lower(username) = lower(%s) OR lower(email) = lower(%s)",
        (identifier, identifier),
    ).fetchone()
    conn.close()
    return row

def set_password(username, new_password_plain):
    new_hash = generate_password_hash(new_password_plain)
    conn = get_db()
    conn.execute(
        "UPDATE admin_users SET password_hash = %s, must_change_password = 0 WHERE username = %s",
        (new_hash, username),
    )
    conn.commit()
    conn.close()
    record_password_history(username, new_hash)
    clear_all_login_attempts_for_user(username)
    return new_hash

# ---------------------------------------------------------------------------
# Visitor Management
# ---------------------------------------------------------------------------
def get_visitor_stats():
    conn = get_db()
    row = conn.execute("SELECT * FROM visitor_stats WHERE id = 1").fetchone()
    conn.close()
    return row

def set_visitor_mode(mode):
    if mode not in ("auto", "manual"):
        raise ValueError("mode must be 'auto' or 'manual'")
    conn = get_db()
    now = datetime.datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE visitor_stats SET mode = %s, updated_at = %s WHERE id = 1",
        (mode, now),
    )
    conn.commit()
    conn.close()

def set_manual_count(count):
    count = max(0, int(count))
    conn = get_db()
    now = datetime.datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE visitor_stats SET manual_count = %s, updated_at = %s WHERE id = 1",
        (count, now),
    )
    conn.commit()
    conn.close()

def record_unique_visitor(visitor_token):
    now = datetime.datetime.utcnow().isoformat()
    conn = get_db()
    
    cur = conn.execute(
        "INSERT INTO unique_visitors (visitor_token, first_seen, last_seen) "
        "VALUES (%s, %s, %s) ON CONFLICT (visitor_token) DO NOTHING",
        (visitor_token, now, now),
    )
    
    is_new = cur.rowcount > 0
    if not is_new:
        conn.execute(
            "UPDATE unique_visitors SET last_seen = %s WHERE visitor_token = %s",
            (now, visitor_token),
        )
    conn.commit()
    count_row = conn.execute("SELECT COUNT(*) AS c FROM unique_visitors").fetchone()
    total = count_row["c"] if count_row else 0
    conn.close()
    return is_new, total

def get_unique_visitor_count():
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) AS c FROM unique_visitors").fetchone()
    conn.close()
    return row["c"] if row else 0

def get_display_visitor_count():
    row = get_visitor_stats()
    if row and row["mode"] == "manual":
        return row["manual_count"], "manual"
    return get_unique_visitor_count(), "auto"


# ---------------------------------------------------------------------------
# Security Questions & Recovery
# ---------------------------------------------------------------------------
def normalize_answer(answer):
    return " ".join(answer.strip().lower().split())

def get_security_questions():
    conn = get_db()
    rows = conn.execute("SELECT id, question FROM security_questions ORDER BY id").fetchall()
    conn.close()
    return rows

def get_user_security_questions(admin_user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT sq.id as question_id, sq.question "
        "FROM security_questions sq "
        "JOIN admin_security_answers asa ON sq.id = asa.question_id "
        "WHERE asa.admin_user_id = %s "
        "ORDER BY sq.id",
        (admin_user_id,)
    ).fetchall()
    conn.close()
    return rows

def has_security_setup(username):
    admin = find_admin_by_username_or_email(username)
    if not admin:
        return False
    return bool(admin.get("security_setup_completed"))

def save_security_answers(admin_user_id, answers):
    conn = get_db()
    now = datetime.datetime.utcnow().isoformat()
    for a in answers:
        conn.execute(
            "INSERT INTO admin_security_answers (admin_user_id, question_id, answer_hash, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (admin_user_id, a["question_id"], a["answer_hash"], now)
        )
    conn.execute("UPDATE admin_users SET security_setup_completed = 1 WHERE id = %s", (admin_user_id,))
    conn.commit()
    conn.close()

def verify_security_answers(admin_user_id, answers):
    conn = get_db()
    saved_answers = conn.execute(
        "SELECT question_id, answer_hash FROM admin_security_answers WHERE admin_user_id = %s",
        (admin_user_id,)
    ).fetchall()
    conn.close()
    
    if not saved_answers or len(saved_answers) != 3:
        return False
        
    saved_dict = {row["question_id"]: row["answer_hash"] for row in saved_answers}
    
    match_count = 0
    for a in answers:
        q_id = a.get("question_id")
        ans = a.get("answer")
        if q_id in saved_dict and ans:
            norm_ans = normalize_answer(ans)
            if check_password_hash(saved_dict[q_id], norm_ans):
                match_count += 1
                
    return match_count == 3

def create_reset_token(username):
    raw_token = uuid.uuid4().hex
    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    now = datetime.datetime.utcnow()
    expires = (now + datetime.timedelta(minutes=15)).isoformat()
    
    conn = get_db()
    conn.execute(
        "INSERT INTO password_reset_tokens (username, token_hash, created_at, expires_at, used) "
        "VALUES (%s, %s, %s, %s, 0)",
        (username, token_hash, now.isoformat(), expires)
    )
    conn.commit()
    conn.close()
    return raw_token

def validate_reset_token(raw_token):
    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    now = datetime.datetime.utcnow().isoformat()
    
    conn = get_db()
    row = conn.execute(
        "SELECT username FROM password_reset_tokens "
        "WHERE token_hash = %s AND used = 0 AND expires_at > %s",
        (token_hash, now)
    ).fetchone()
    conn.close()
    return row["username"] if row else None

def invalidate_reset_token(raw_token):
    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    conn = get_db()
    conn.execute("UPDATE password_reset_tokens SET used = 1 WHERE token_hash = %s", (token_hash,))
    conn.commit()
    conn.close()

def cleanup_expired_tokens():
    now = datetime.datetime.utcnow().isoformat()
    conn = get_db()
    conn.execute("DELETE FROM password_reset_tokens WHERE expires_at < %s", (now,))
    conn.commit()
    conn.close()

def record_recovery_attempt(username, ip, success):
    conn = get_db()
    now = datetime.datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO recovery_attempts (username, ip_address, attempted_at, success) VALUES (%s, %s, %s, %s)",
        (username, ip, now, 1 if success else 0)
    )
    conn.commit()
    conn.close()

def get_recovery_attempt_count(username, ip):
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(minutes=30)).isoformat()
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM recovery_attempts "
        "WHERE username = %s AND ip_address = %s AND attempted_at >= %s",
        (username, ip, cutoff)
    ).fetchone()
    conn.close()
    return row["c"] if row else 0

def is_recovery_locked_out(username, ip):
    return get_recovery_attempt_count(username, ip) >= 5