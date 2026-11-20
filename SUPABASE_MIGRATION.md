# LADLI free hosting migration

Prepared from production commit `6954bac`, 20 November 2026. Use free plans
only. The owner explicitly chose a fresh database: no historical enquiries or
accounts are required. Render's expired database was not restored.

## Deployed preview

- Website: https://ladli-app.ladlielec.workers.dev/
- Supabase project: `ladli-production`, ref `xybtgvuugfsewduccsxz`.
- Cloudflare `ladli-app` runs `cloudflare/worker.mjs`. Its `ASSETS` service
  binding points to the static-only `ladli-preview` Worker. Use a service
  binding for communication between Workers in this account.
- The static bundle has 124 files, including the existing admin UI. HTML
  handling is `none`, preserving existing `.html` URLs; the router maps
  `/` to `/index.html` and preserves legacy canonical redirects.
- Preview responses have `X-Robots-Tag: noindex, nofollow` and disallow all
  crawlers. Keep preview indexing exclusions until domain cutover.
- Supabase `ladli-api` contains `index.ts` and `handler.mjs`; deploy both.
  The gateway strips `/functions/v1` from request URLs.

## Database and security

All three versioned migrations have been applied. The 13 application tables
have RLS and no public or authenticated-client access. Only the backend service
role can read private data or call the privileged application RPCs.

The owner created their new `admin` account privately. One-time provisioning
refuses to run if any admin already exists. Passwords use Werkzeug-compatible
PBKDF2 with one million iterations; plaintext passwords never enter migration
files. The temporary loopback owner setup server has been stopped.

Private PDF storage is `ladli-attachments`, restricted to PDFs up to 3 MB.
Admin sessions store token hashes and CSRF tokens server-side, expire after
30 minutes, and are revoked after password changes. Shared database rate
limits and login lockouts survive serverless restarts. Public password
recovery remains disabled, matching the owner-controlled production policy.

The Supabase function requires `LADLI_PROXY_TOKEN` and an exact origin
allowlist. Legacy JWT gateway verification is off because custom proxy auth
and separate administrator sessions implement authentication. Direct private
requests without the proxy token are rejected. Supabase service keys remain
inside the backend and must never be included in site assets.

## Deployment configuration

Cloudflare runtime values:

- `SUPABASE_PROJECT_URL`: `https://xybtgvuugfsewduccsxz.supabase.co`
- `PREVIEW_MODE`: `true` until production cutover
- `ASSETS`: service binding to `ladli-preview`
- `LADLI_PROXY_TOKEN`: encrypted secret, same value as Supabase

Supabase function secrets:

- `LADLI_PROXY_TOKEN`: private server-to-server credential
- `LADLI_ALLOWED_ORIGINS`: `https://ladli-app.ladlielec.workers.dev,https://ladlilab.com,https://www.ladlilab.com`

The function uses injected `SUPABASE_SECRET_KEYS.default`, with a legacy
service-role fallback. New secret keys use the `apikey` header, not JWT Bearer.

`python tools/build_cloudflare.py` produces the preview archive under ignored
`.dist/`. `--production` produces the production archive. Optional Wrangler
configuration deploys `ladli-app` with an integrated `ASSETS` bundle instead
of the Dashboard's separate static Worker; build before using it. Configure
the proxy secret separately. Never upload `.dist/ladli-local-secrets.json`.

## Verified

- Python baseline: 27 passed, 9 disposable-Postgres tests skipped locally.
  GitHub CI passed on Python 3.11 and 3.13 with PostgreSQL integration tests;
  dependency auditing and secret scanning also passed (run 44742711767).
- Node: 20 routing/API/security/validation tests passed.
- Deno type check passed for the two-file function entry point.
- Live SQL checks verified private tables and reference seeds. Transactional
  smoke tests verified shared rate limits, password compare-and-swap, session
  revocation and atomic question replacement; fixtures rolled back.
- Live preview `/ready` reports database connected and schema ready.
- Browser quote submission reached Supabase (test enquiry 1).
- PDF upload reached private storage, backend download matched all bytes,
  and anonymous download was blocked (test enquiry 2).
- Wrong proxy tokens, foreign origins and unauthenticated private data access
  were rejected. The browser preview homepage and resource images load.

## Required before cutover

1. Verify the owner's real preview login, dashboard, status updates, private
   attachment download and logout. Keep the two marked migration test
   enquiries for verification; they are not customer requests.
2. GoDaddy's full DNS export is saved in ignored `.dist/` for rollback. All
   11 portable records were compared with Cloudflare; both DKIM aliases missed
   by scanning were added DNS-only. MX, SPF, DMARC, email and autodiscovery are
   preserved. Existing DNSSEC is off. Recheck for concurrent edits at cutover.
3. Activate Cloudflare DNS using assigned nameservers
   `arnold.ns.cloudflare.com` and `edna.ns.cloudflare.com`. Current GoDaddy
   nameservers: `ns75.domaincontrol.com` and `ns76.domaincontrol.com`.
   Imported web records still point to Render during activation.
4. Connect apex and www to the tested Worker, confirm certificates, restore
   production robots rules and remove production noindex responses. Verify
   HTTPS, canonical redirects, sitemap and the same form/admin flows.
5. Keep Render available as rollback until the replacement is confirmed.

At this checkpoint `ladlilab.com` still points to Render; migration is not yet
complete. No paid upgrade has been made. Free quotas and Supabase inactivity
pausing apply; this is not a two-year availability guarantee.
