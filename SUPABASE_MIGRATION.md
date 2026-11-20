# LADLI migration status

Prepared from production commit `6954bac` on 20 November 2026. This branch does
not change the running Render service, its database URL, DNS or public pages.

## Prepared

- Supabase CLI 3.2.0 initialized the local project and created the migration.
- The migration preserves the existing Flask database schema and both numbered
  application migrations, seeds reference questions and the visitor singleton,
  and enables RLS on all 12 application tables.
- Public and signed-in API clients have no table or sequence permissions.
  Only the trusted backend service role receives API access. Never put its key
  in browser code. The migration does not create an admin or import records.
- A separate preview archive is generated under `.dist/` with noindex headers
  and a robots exclusion. It must not be used as the final production package.

## Required before cutover

1. Finish the free `ladli-production` project in the `ladl Org` organization.
   Choose Asia-Pacific, disable automatic API grants and enable automatic RLS.
   Save the database password in the owner's credential store.
2. Recover an export of the previous database if available. The live `/ready`
   endpoint returned 503 during preparation, and Render still referenced the
   old internal database host. Do not assume historical enquiries or accounts
   have been copied. Preserve the old environment settings for rollback.
3. Apply and verify the schema on the new project. Compare table/row counts
   after importing any recovered data; run Supabase security advisors and
   disposable-database integration tests. Do not run destructive integration
   tests on the client project.
4. Provide private durable storage for PDF attachments. Supabase Storage needs
   backend upload/download integration: the current Flask app uses S3. Moving
   the database alone does not move attachments.
5. Deploy a frontend preview on Cloudflare. Its default clean-URL handling must
   preserve the site's `.html` canonicals and existing 301 redirects. Retain
   the domain, sitemap, Search Console verification and business details.
6. Port and test the Flask API to Supabase Edge Functions before removing
   Render. A static upload alone does not implement forms, visitor counts,
   sessions, CSRF, admin routes, password controls or attachment access.
7. Verify real preview form submissions, authenticated admin access, status
   updates, logout, CSRF rejection, unauthorized access rejection and private
   PDF downloads. Remove preview noindex rules only from the production
   package, then change DNS after the replacement passes.

The website needs Cloudflare hosting as well as Supabase; Supabase does not
run the existing Flask web service unchanged. Keep Render as the rollback
until the complete replacement works. Use free plans only; no paid service or
plan change is authorized. Free quotas and Supabase inactivity pausing still
apply, so this setup is not a two-year availability guarantee.

## Verification so far

The latest repository checks pass with its required Flask 3.1.3 and Werkzeug
3.1.9: 27 passed, 9 database integration tests skipped because no disposable
database was configured. The hosted schema, data restore, storage and final
cutover have not yet been verified.
