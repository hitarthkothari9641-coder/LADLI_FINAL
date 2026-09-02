# LADLI Electrical Testing & Calibration Laboratory — Website + Backend

Production-ready public website and admin portal built on:

```text
Flask + Gunicorn + PostgreSQL (AWS RDS) + AWS S3 + AWS Secrets Manager + HTTPS
```

- **Public website** — 32 fully responsive pages (services, testing
  pages, resources, contact, request-quote) with live contact/quote
  forms, a persistent unique-visitor counter, SEO metadata, structured
  data, sitemap and robots.txt.
- **Admin portal** (`/admin`) — secure login, enquiry dashboard with
  status workflow and PDF attachment downloads, visitor statistics,
  settings, and **security-question account recovery**.
- **No SMTP dependency** — there are no mail credentials, no email
  reset links, no mail-outbox and no email reset tokens anywhere in
  the application. Password recovery works exclusively through
  personal security questions.

## 1. Requirements

- Python 3.9+
- PostgreSQL (AWS RDS in production; any local PostgreSQL for development)
- Optional: an AWS S3 bucket for quote attachments (falls back to local
  `attachments/` storage when unconfigured, e.g. during development)

Dependencies (`requirements.txt`): Flask, Werkzeug, psycopg2-binary,
boto3, gunicorn.

## 2. Configuration

All configuration comes from the environment (or a local `.env` file in
development — never committed). See **`.env.example`** for every
variable. Minimum:

```bash
SECRET_KEY=<64 hex chars — python3 -c "import secrets; print(secrets.token_hex(32))">
FLASK_DEBUG=0
DATABASE_URL=postgresql://user:password@host:5432/ladli_db
```

Optional first-run bootstrap: `ADMIN_USERNAME`, `ADMIN_PASSWORD`,
`ADMIN_EMAIL`. If `ADMIN_PASSWORD` is omitted, a strong password is
generated and printed **once** to the log, and you must change it at
first login.

S3 attachments: set `AWS_S3_BUCKET` and `AWS_REGION` (credentials via
IAM role or the standard boto3 chain). Attachment metadata and S3
object keys are stored in PostgreSQL; admin downloads use short-lived
presigned URLs.

## 3. Run

Development:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 app.py          # http://127.0.0.1:5000
```

Production:

```bash
gunicorn -c gunicorn.conf.py app:app     # binds 0.0.0.0:8000
```

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for the full AWS deployment
guide (RDS, S3, Secrets Manager, ALB/CloudFront, HTTPS, monitoring,
backups).

## 4. Admin portal

| Page | Purpose |
|---|---|
| `/admin/login` | Sign in (IP + account rate-limited, progressive lockout) |
| `/admin` | Enquiries — contact/quote submissions, filter by type/status, status updates, attachment download, delete |
| `/admin/visitors` | Visitor statistics — unique-visitor total, auto/manual display mode |
| `/admin/settings` | Change password, manage security questions |
| `/admin/setup-security` | One-time security-question setup (forced after first login) |
| `/admin/forgot-password` | Account recovery via security questions |

### Password recovery (no email involved)

```text
First login  → choose 3 personal questions (from a bank of 10)
             → answers normalized (trim/lowercase/collapse spaces) and
               stored ONLY as password hashes → setup locked

Forgot password → enter username → answer the 3 questions
                → rate-limited + progressive lockout + audit-logged
                → single-use reset token (hashed, 15-minute expiry)
                → set new password → ALL existing sessions invalidated
```

Changing questions later requires the current password **and** the
current security answers.

## 5. Security highlights

- Session cookies: `Secure` (in production), `HttpOnly`, `SameSite=Lax`;
  30-minute session lifetime.
- CSRF tokens required on all state-changing admin operations.
- Security headers: CSP, HSTS, `X-Content-Type-Options`,
  `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`.
- Rate limiting on `/api/contact`, `/api/quote`, `/api/visitor-register`,
  login and every recovery endpoint; login lockout (5 fails / 15 min).
- Generic authentication/recovery errors — responses never reveal
  whether an account exists; details are logged server-side only.
- Uploads: PDF only, magic-byte validated, 3 MB per attachment,
  25 MB request cap.
- All existing sessions are invalidated automatically when the password
  changes (fingerprint check on every admin request).
- `/health` endpoint for load-balancer checks.

## 6. Visitor counter semantics

The badge counts **unique visitors** (distinct browsers/devices) — not
sessions, tabs or page views. Each browser gets one persistent random
id (localStorage + an authoritative HttpOnly server cookie); the server
hashes it and counts it once, ever. Bot user-agents are ignored,
registration is rate-limited, and the server prefers its own cookie so
client-side code cannot inflate the count. Admins may switch the
displayed number to a manual value from `/admin/visitors`.

## 7. Repository layout

```text
app.py               Flask backend — routes, public/admin APIs, security
db.py                PostgreSQL data-access layer + schema + recovery storage
gunicorn.conf.py     Production Gunicorn configuration
requirements.txt     Flask, Werkzeug, psycopg2-binary, boto3, gunicorn
.env.example         Variable names only — never real secrets
site/                Public website (HTML + assets, self-hosted fonts/libs)
admin/               Admin portal (HTML + admin.css/admin_responsive.css/admin.js)
```

Not in the repository (see `.gitignore`): `.env`, `.venv/`,
`__pycache__/`, `*.db`, `secret.key`, `attachments/`, `mail-outbox/`.

## 8. Brand reference

Royal Blue `#1F6FE5` · Light Sky Blue `#67C5F8` · Bright Pink `#E95AA5` ·
Golden Orange `#F9A825` · White `#FFFFFF`

LADLI Electrical Testing and Calibration Laboratory Pvt. Ltd.
A/39, First Floor, Shrenik Park, Opp. Akota Stadium, Productivity Road,
Akota, Vadodara – 390020, Gujarat, India
Phone: +91 84908 38981 · Email: ladlielec@gmail.com
