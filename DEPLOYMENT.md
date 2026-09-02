# LADLI — Production Deployment (AWS)

Production stack:

```text
Internet
   ↓
CloudFront (CDN, HTTPS, static caching)
   ↓
Application Load Balancer (HTTPS termination / forwarding)
   ↓
Gunicorn  (gunicorn -c gunicorn.conf.py app:app)
   ↓
Flask (app.py)
   ├── AWS RDS PostgreSQL   (all application data)
   ├── AWS S3               (quote attachments, private bucket)
   └── AWS Secrets Manager  (SECRET_KEY, DB credentials)
```

There is **no SMTP dependency**: password recovery uses personal
security questions only. No mail server, mail credentials, mail-outbox
or email reset tokens exist anywhere in this application.

---

## 1. Prerequisites

- An AWS account with permissions for EC2/ECS, RDS, S3, Secrets Manager,
  ACM, CloudFront and Route 53.
- The final production domain (e.g. `www.ladlielectricaltesting.com`).
- This repository (do **not** ship `.git/`, `.venv/`, `__pycache__/`,
  `.env`, any `*.db` files, or `data/` runtime artifacts in the deploy
  package — see `.gitignore`).

## 2. Database — RDS PostgreSQL

1. Create an **RDS PostgreSQL** instance (private subnet, no public
   access; the app's security group only).
2. Create the application database and user:
   ```sql
   CREATE DATABASE ladli_db;
   CREATE USER ladli_app WITH PASSWORD '<strong-password>';
   GRANT ALL PRIVILEGES ON DATABASE ladli_db TO ladli_app;
   ```
3. Enable **automated backups** (7–35 day retention) and, if desired,
   point-in-time recovery.
4. The schema is created automatically on first application start
   (`db.init_db()`); no manual migration step is needed for a fresh
   install. If legacy SQLite data must be preserved, migrate it into
   PostgreSQL **before** go-live and keep any one-off migration script
   outside the deployed runtime.

## 3. Object storage — S3

1. Create a **private** S3 bucket for attachments
   (e.g. `ladli-attachments-prod`), with:
   - Block Public Access: **ON** (all four settings)
   - Default encryption: SSE-S3 or SSE-KMS
2. Add a **lifecycle rule** as the attachment retention policy
   (e.g. expire objects under `attachments/` after 365 days) so storage
   cannot grow indefinitely.
3. Grant the application's IAM role only:
   `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` on
   `arn:aws:s3:::<bucket>/attachments/*`.

Admin downloads use **short-lived presigned URLs** (5 minutes); the
bucket is never publicly readable.

## 4. Secrets — AWS Secrets Manager

Store as secrets (never in the repo or the AMI):

- `SECRET_KEY` — generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`
- `DATABASE_URL` (or `PGHOST`/`PGUSER`/`PGPASSWORD`/…)
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` (first-run bootstrap only —
  **rotate the admin password immediately after first login**)

Inject them into the service environment at start-up (ECS task
definition secrets, or an EC2 start script that reads Secrets Manager).
See `.env.example` for the full variable list — it contains names only,
never real values.

## 5. Application host — Gunicorn

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
gunicorn -c gunicorn.conf.py app:app
```

- `gunicorn.conf.py` binds `0.0.0.0:8000` by default
  (`GUNICORN_BIND` to override) and logs to stdout/stderr.
- Run under a process supervisor (systemd unit or ECS service) so it
  restarts on failure.
- Set `GUNICORN_FORWARDED_ALLOW_IPS` to the ALB subnet CIDR/addresses so
  `X-Forwarded-*` headers are only trusted from the load balancer, and
  set `TRUSTED_PROXY_COUNT` to the number of proxy hops
  (1 = ALB only, 2 = CloudFront + ALB).

Required environment (see `.env.example`):

```text
SECRET_KEY, FLASK_DEBUG=0, FLASK_ENV=production, FORCE_SECURE_COOKIES=true,
DATABASE_URL, AWS_S3_BUCKET, AWS_REGION, TRUSTED_PROXY_COUNT
```

## 6. HTTPS, domain & CDN

1. Request an **ACM certificate** for the production domain.
2. Attach it to the ALB (HTTPS :443 listener; redirect :80 → :443).
3. Create a **CloudFront distribution** in front of the ALB:
   - Cache `assets/*` (CSS/JS/images/fonts) — the app already serves
     them with `Cache-Control: public, max-age=31536000, immutable`.
   - Do **not** cache HTML or `/api/*` (the app sends
     `no-cache, must-revalidate` for HTML) — forward cookies and all
     methods for `/api/*` and `/admin*`.
4. Point **Route 53** (or your DNS) at the CloudFront distribution.
5. Verify HSTS is active in responses (the app sends
   `Strict-Transport-Security` when secure cookies are enabled).

## 7. Health checks & monitoring

- ALB target-group health check path: **`/health`**
  (returns `{"status": "ok", "database": "connected"}` and 503 when the
  database is unreachable).
- Ship Gunicorn stdout/stderr to **CloudWatch Logs**; the app logs
  authentication events, admin actions, quote submissions, recovery
  attempts and errors (never passwords, answers, tokens or secrets).
- Add CloudWatch alarms on 5xx rate, unhealthy hosts, RDS CPU/storage
  and free-able memory.

## 8. First run

1. Start the service with `ADMIN_USERNAME`/`ADMIN_PASSWORD` set (or let
   the app generate a one-time password, printed once to the log).
2. Log in at `https://<domain>/admin` — you are forced to change a
   generated password immediately.
3. Complete the **security-question setup** (choose 3 questions from
   the bank). Recovery is impossible without this, so do it on day one.
4. Submit a test quote with a PDF attachment and confirm it appears in
   the dashboard and downloads via the S3 presigned URL.
5. Confirm `/health` is green behind the ALB and the visitor counter
   increments once per browser.

## 9. Production package checklist

The deployed artifact must **not** contain:

```text
.env  .git/  .venv/  __pycache__/  *.pyc
data/ladli.db  data/secret.key  data/mail-outbox/
development scripts, Windows launchers, PythonAnywhere configs,
password utilities or one-time migration scripts
```

What ships: `app.py`, `db.py`, `requirements.txt`,
`gunicorn.conf.py`, `.env.example`, `site/`, `admin/`.
