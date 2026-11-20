# LADLI production hosting

Completed on 20 November 2026. The live website uses Cloudflare Workers and
Supabase Free plans. Render no longer has the custom-domain bindings.

- Website: https://ladlilab.com/
- Owner login: https://ladlilab.com/admin/login
- Readiness: https://ladlilab.com/ready
- Supabase: `ladli-production`, project `xybtgvuugfsewduccsxz`
- Cloudflare account: `a12b93a39b1227f4d9c4f8ec85760bee`
- DNS zone: `24342a995e4b802e6181a18b3e7474c1`

The owner explicitly chose a fresh database with no historical records. The
owner created their password privately and confirmed both preview and live
admin sign-in. No password reset was needed; the unused recovery server was
stopped. No plaintext owner password is stored in this repository.

## Architecture and routing

`ladli-app` runs `cloudflare/worker.mjs`, with an `ASSETS` service binding to
static-only Worker `ladli-preview`. Its 124-file bundle includes the existing
public pages and static admin UI. Use the internal service binding rather
than a public fetch between Workers on this account.

The DNS zone has 11 records. The apex A record is proxied and points to the
reserved documentation address `192.0.2.1`; this is a placeholder, never an
application origin. The Worker handles every request through routes
`ladlilab.com/*` and `www.ladlilab.com/*`, both fail-closed. The proxied www
CNAME points to `ladlilab.com`. No web DNS record points to Render.

Nameservers are `arnold.ns.cloudflare.com` and `edna.ns.cloudflare.com`.
GoDaddy's complete DNS export is saved under ignored `.dist/` for rollback.
All portable records were compared. Both DKIM records missed by automatic
scanning were added DNS-only; MX, SPF, DMARC, email and autodiscovery records
are preserved. Cloudflare Universal SSL is active and Always Use HTTPS is on.

The previous Render custom hostname took routing priority over normal
Cloudflare DNS routes. Both Render bindings were removed with explicit owner
approval after the new API, owner login and private storage were verified.
The Render service remains at `https://ladli-final.onrender.com`. Its expired
old database is not a working backend rollback; it can serve the old public
pages only unless its backend is separately restored.

The router keeps `.html` URLs, legacy redirects and sitemap URLs, maps `/` to
`/index.html`, and redirects www to the apex (301 for GET/HEAD, 308 otherwise).
Public production pages are indexable. Admin pages remain noindex/no-store;
the workers.dev preview remains noindex even with production enabled.

## Backend and security

Supabase `ladli-api` uses `index.ts` and `handler.mjs`; deploy both together.
The hosted gateway strips `/functions/v1` before forwarding requests.
All three versioned SQL migrations were applied through the SQL editor.
Before adopting CLI database deployment, reconcile its migration history with
`supabase migration repair`; do not blindly replay these on the live project.

All 13 application tables have RLS and no public or authenticated-client table
access. Privileged RPCs are service-role-only. The private `ladli-attachments`
bucket accepts PDFs up to 3 MB. No service key belongs in browser assets.

Owner password hashes are Werkzeug-compatible PBKDF2 with one million
iterations. Sessions store token hashes and CSRF tokens, expire after 30
minutes and are invalidated after password changes. Shared database rate
limits and login lockouts survive restarts. Public password recovery remains
disabled, matching the owner-controlled production policy.

The Edge Function uses custom proxy authentication rather than legacy JWT
verification. `LADLI_PROXY_TOKEN` is required on private function requests;
admin sessions independently protect customer data. Wrong tokens and foreign
origins are rejected. The secret API key is injected by Supabase, with the
new key sent only in the server-side `apikey` header.

## Runtime configuration

Cloudflare:

- `SUPABASE_PROJECT_URL`: `https://xybtgvuugfsewduccsxz.supabase.co`
- `PREVIEW_MODE`: `false` (only the real production hostnames become indexable)
- `ASSETS`: service binding to `ladli-preview`
- `LADLI_PROXY_TOKEN`: encrypted secret, matching Supabase

Supabase function secrets:

- `LADLI_PROXY_TOKEN`: private server-to-server credential
- `LADLI_ALLOWED_ORIGINS`: `https://ladli-app.ladlielec.workers.dev,https://ladlilab.com,https://www.ladlilab.com`

`python tools/build_cloudflare.py --production` builds the production static
archive. Dashboard uploads must use HTML handling `none`, not-found handling
`404-page`. The optional Wrangler configuration instead bundles assets into
`ladli-app` under the same `ASSETS` interface. Build before deploying, configure
the proxy secret separately, and verify that assets and bindings match the
chosen deployment method. Never upload `.dist/ladli-local-secrets.json`.
GitHub pushes run checks; the Cloudflare deployment is currently manual.

The Dashboard code editor was observed dropping ordinary variables and
service bindings during a code-only deployment (the encrypted secret stayed).
Runtime values and the ASSETS service binding were restored and retested.
Prefer deployment from the checked-in Wrangler configuration. If using the
Dashboard editor, reapply the documented runtime configuration immediately
and verify both the homepage and /ready after every code deployment.

## Acceptance evidence

- 24 Node tests pass, covering API validation, proxy authentication, CSRF,
  session handling, empty-body admin actions, storage failures and routing.
- Python baseline: 27 passed locally, 9 disposable-Postgres tests skipped.
  GitHub CI passed on Python 3.11 and 3.13 with PostgreSQL integration tests,
  dependency auditing and secret scanning (run 44746678328 for API revision).
- Deno checks pass. Live SQL smoke tests verified shared rate limiting,
  password compare-and-swap, session invalidation and atomic question updates;
  fixtures were rolled back.
- All 34 production page checks passed, with public pages indexable and admin
  pages noindex. The live `/ready` returns 200, database connected/schema ready.
- Owner sign-in, enquiry listing/status updates, visitor statistics, private
  PDF download integrity and logout were verified. Owner also confirmed the
  final `ladlilab.com` admin login works.
- The real-domain quotation form successfully inserted test enquiry 3.
  All three clearly marked migration test enquiries are Closed, not deleted.
- Anonymous `/api/admin/me` returns logged_in false; private enquiry listing
  returns 401. Wrong proxy tokens and foreign origins are rejected. Private
  storage rejects anonymous file downloads.
- HTTP redirects to HTTPS; www and index.html redirect to the apex canonical.
  Production robots.txt retains the real sitemap and private-path exclusions.

Free quotas and Supabase inactivity pausing still apply. No paid upgrade was
made, and free hosting is not a two-year availability guarantee.
