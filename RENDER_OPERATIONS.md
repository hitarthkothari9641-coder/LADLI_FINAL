# Render operations and audit follow-up

Render + PostgreSQL is the primary deployment. Vercel and the AWS instructions are alternative configurations, not a migration plan. Keep operational data in PostgreSQL; this change does not introduce Excel, Firebase or another database.

## Behavior changes

- Password recovery defaults to a controlled owner reset. Existing passwords remain valid. After verifying the person's identity, the operator runs `python manage.py reset-admin --username admin` from a trusted shell with the application's environment. Password prompts are hidden; do not pass passwords as command-line arguments. Resetting invalidates existing sessions and requires another password change at login.
- Security-question recovery is disabled unless `ALLOW_SECURITY_QUESTION_RECOVERY=true`. This legacy compatibility option remains weaker than verified recovery or MFA. Its tokens are random, stored only as SHA-256 hashes, expire after 15 minutes and are consumed in the same transaction as password/history updates. Repeated question IDs cannot satisfy verification. All password changes invalidate outstanding tokens.
- New bootstrap accounts require an explicitly configured password of at least 12 characters and must change it. Existing accounts are not recreated. No generated bootstrap password is printed to logs.
- Production attachment uploads require configured S3. Without storage, attachment submissions return 503 with an actionable message; submissions without files and public pages remain available. Local development retains filesystem storage. Existing ephemeral files cannot be recovered by this code change.
- Login, recovery, enquiry and visitor request limits now use PostgreSQL transactions shared by workers. Failed storage deletion retains the enquiry for retry. Admin responses are non-cacheable; logout requires CSRF. Tokens are stable within a session so multiple tabs do not invalidate one another.

## Owner configuration still required

1. Confirm Render deploys `main` from this repository and inspect its deploy logs. A GitHub push is not proof that Render deployed successfully. Existing manually configured Render environment variables may override Blueprint changes.
2. Set a stable, random `SECRET_KEY`, strong initial `ADMIN_PASSWORD`, PostgreSQL SSL and least-privilege credentials. Existing admin passwords are unaffected by changing the bootstrap variable. Rotate any credentials confirmed exposed, including historical ones.
3. Set `AWS_S3_BUCKET`, `AWS_REGION` and credentials or an IAM role. Enable S3 Block Public Access and restrict the role to the attachment prefix with only required object permissions. Test upload, authorized download, deletion and persistence after redeploy. AES256 server-side encryption is requested on upload; bucket policies must allow it. PDF signature checks are not malware scanning.
4. Determine the actual immediate proxy peers and forwarding behavior before setting `TRUSTED_PROXY_CIDRS` and `TRUSTED_PROXY_COUNT`. Gunicorn's separate `GUNICORN_FORWARDED_ALLOW_IPS` must also match trusted peers, never `*`. Test forged headers from outside the proxy. Until configured, client IP uses the socket peer, so visitors behind the same proxy share a limit bucket. No network ranges are guessed in this repository.
5. Set `ALLOWED_HOSTS` to the real custom domains and Render service hostname, including the health-check hostname. Defaults allow ladlilab.com, www.ladlilab.com, local development hosts and RENDER_EXTERNAL_HOSTNAME when supplied by Render. Add any other legitimate hostname explicitly; no redirect is built from an untrusted forwarded host. HTTPS enforcement remains at Render; secure cookies are configured in production.
6. Budget DB connections as workers × `DB_POOL_MAX` plus migration/maintenance capacity. Render defaults are two workers, four threads, five pooled connections per worker. Psycopg2 uses a thread-safe pool; psycopg3/pg8000 use short-lived direct connections. All paths roll back and close on failure. The alternative drivers are not claimed to share the same pooling implementation.

## Migrations, health and rollback

`python manage.py migrate` runs additive numbered migrations in `migrations/`, tracked in `schema_migrations`. First-request bootstrap remains compatible with the existing deployment and runs the same migrations. A PostgreSQL advisory transaction lock serializes bootstrap across workers. Schema, seed records and initial admin creation commit together. Do not edit already applied migrations; add another numbered file.

`/health` and `/healthz` are liveness only and remain 200 during a DB outage. `/ready` verifies schema initialization and a live DB query, returning 503 on failure. Use readiness and a non-destructive enquiry smoke test in monitoring; do not interpret liveness as proof of storage or database health.

Before deploying schema changes, take an encrypted `pg_dump -Fc` backup using a secure service file or environment credentials. Restore to a separate empty database using `pg_restore --no-owner`, run migrations, compare row counts and test login, enquiry retrieval and attachment access. Verify the restore with the actual supported PostgreSQL version and storage backup. Never rehearse against production. For this release, new indexes/tables are additive and can remain when reverting code. Do not delete operational tables to roll back. Keep S3 versioning/backups and test object restoration independently.

## Retention and privacy

`python manage.py cleanup --visitor-days 365` deletes inactive hashed visitor identifiers older than the chosen interval, old login/recovery attempt records (30 days), and used/expired reset tokens. Schedule daily through the owner's supported job runner; this repository cannot configure a Render schedule. Shared rate-limit records are pruned after one day during admission. Cleanup changes the automatic visitor count; manual display counts are separate from measured visitors.

Enquiry and attachment retention needs a business-approved duration. No customer records are automatically purged by this release. Confirm the privacy notice and any jurisdiction-specific requirements with the owner. Do not log passwords, cookies, answers, tokens or full connection URLs. Gunicorn access logs omit query strings and referrers.

## Release evidence and remaining audit items

Run `python -m unittest discover -s tests -v`. To include destructive PostgreSQL integration tests, set `TEST_DATABASE_URL` to a **disposable database only**. Tests exercise concurrent bootstrap, one-use concurrent resets, expiry, rollback, password history, shared rate limits, failed transactions and answer replacement. CI runs PostgreSQL on Python 3.11 and 3.13, dependency auditing and a history secret scan. CI must be green before calling a release verified.

The supplied audit also asks for work requiring owner/platform access: production restore drills, S3 persistence/access-policy verification, proxy topology verification, domain/HTTPS settings, monitoring and alerts, secret rotation, real-device testing and field performance measurement. These are not completed by a repository push. This release does not certify production readiness or claim a performance improvement.

Accreditation wording and builder instructions have been made neutral. The owner must verify legal identity, certificate/scope, method/equipment matrix and approve a redacted sample report. The unverified sample image (which contained an accreditation claim and dummy certificate identifiers) has been removed from the public site and replaced with a sample-on-request link. The large brochure still requires content approval before republication or optimization; no certificate or technical scope has been invented.
