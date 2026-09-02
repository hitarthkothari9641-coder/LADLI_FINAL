# LADLI Electrical Testing & Calibration Laboratory — Website + Backend

A complete, self-contained local website with a Python (Flask) backend:
live contact/quote forms backed by a real database, and an admin portal
to review enquiries and publish PDF documents to the public Downloads
page. No external services, no CDN dependencies, no cloud account
needed — it runs entirely on your own machine.

## 1. Run it

**Requirements:** Python 3.9+ installed on your machine.

### macOS / Linux
```bash
./run.sh
```

### Windows
Double-click `run.bat`, or from a terminal:
```
run.bat
```

### Manual (any OS)
```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python3 app.py
```

Then open **http://127.0.0.1:5000** in your browser.

The first time you run it, a SQLite database is created automatically
at `data/ladli.db`, and an admin account is created. **Your terminal
will print the generated login** the very first time — look for a
block like this:

```
================================================================
 First run: an admin account was created.
   Username: admin
   Password: <a randomly generated password, shown only here>
 This password was randomly generated and is shown ONLY here, once.
 Save it now. You will be required to change it the moment you log in.
================================================================
```

You'll be required to set your own password the moment you first log
in at `/admin` — the rest of the admin portal is locked until you do.

If you'd rather set your own credentials from the start, set these
environment variables before the first run instead:
```bash
export ADMIN_USERNAME="your_username"
export ADMIN_PASSWORD="your_password"
python3 app.py
```

You can also place the same settings in a local `.env` file in the
project root. The app will load it automatically on startup.

Example `.env` contents:
```bash
ADMIN_USERNAME=your_username
ADMIN_PASSWORD=your_password
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=ladlielec@gmail.com
SMTP_PASSWORD=your_gmail_app_password
MAIL_FROM_EMAIL=ladlielec@gmail.com
MAIL_FROM_NAME=LADLI Electrical Testing and Calibration Laboratory
MAIL_REPLY_TO=ladlielec@gmail.com
```
For Gmail, the password must be a Google app password, not your normal
login password. Turn on 2-step verification on the Gmail account, create
an app password, and paste that value into `SMTP_PASSWORD` in `.env`.

To enable the automated quote confirmation email, set these SMTP
variables before starting the app:
```bash
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USERNAME="ladlielec@gmail.com"
export SMTP_PASSWORD="your_gmail_app_password"
export MAIL_FROM_EMAIL="ladlielec@gmail.com"
export MAIL_FROM_NAME="LADLI Electrical Testing and Calibration Laboratory"
export MAIL_REPLY_TO="ladlielec@gmail.com"
```
The email includes the LADLI logo and a branded thank-you message. If
SMTP settings are not provided, the form submission still saves, but no
confirmation email is sent.

## 2. What's included

```
app.py                 Flask backend (routes, forms API, admin API)
db.py                  SQLite schema + connection helper
requirements.txt       Two dependencies: Flask, Werkzeug
run.sh / run.bat        One-click local launchers
site/                   The public website (41 pages, all assets)
  assets/
    vendor/             Self-hosted three.min.js, anime.min.js, tsparticles.slim.min.js
    fonts/              Self-hosted Inter woff2 files
    site-3d.js          The five Three.js scenes
    particles.js         Ambient particle background config
    motion.js             anime.js-powered interactions
    animations.css        Motion + glass header + splash + responsive fixes
admin/                  The admin portal (login, dashboard, documents, settings)
uploads/                Where uploaded PDFs are stored on disk
data/                   ladli.db (SQLite) and a generated session secret key
```

## 3. The public website

Same 41-page site as before, plus:
- **Splash screen** — the LADLI logo flashes in briefly on a visitor's
  first page load each browser session, then fades away (skipped
  automatically on repeat page loads in that session, and instantly
  skipped for anyone with "reduce motion" turned on).
- **Glassmorphism header** — translucent, blurred header that shrinks
  slightly once you scroll.
- **Subtle lab-themed background texture** across every page.
- **Five distinct Three.js 3D components** (not just one) — each major
  page gets its own scene, all self-hosted, all pausing automatically
  when scrolled out of view and disabled below 900px width in favour
  of the lighter CSS decoration:
  | Page | Scene |
  |---|---|
  | Home | Orbiting DGA gas-molecule cluster around a wireframe core |
  | About | Transformer core with rotating copper coil rings and drifting field particles |
  | Services | A cluster of coloured sample vials bobbing gently |
  | Laboratory | An abstract analytical-instrument rack with moving dials and orbiting sample trays |
  | Contact | A location pin over a map grid with pulsing radar rings |
- **Ambient particle background** (tsParticles) — a very sparse,
  slow-drifting layer of brand-coloured dots behind every hero section,
  tuned deliberately subtle so it never competes with the 3D component
  or the headline. Off below 640px width.
- **anime.js-powered premium interactions** — word-by-word hero heading
  reveal, smoother number counters, magnetic hover on primary buttons
  and the back-to-top button (desktop only), and a top scroll-progress
  bar.
- **Scroll parallax** on the hero photo and 3D stage.
- **Refined motion system** — every transition follows the
  animation-engineering approach published by Emil Kowalski
  (github.com/emilkowalski/skills): custom "stronger" easing curves
  instead of default CSS easing, `ease-out` for things entering/exiting
  vs `ease-in-out` for on-screen movement, nothing animates in from
  `scale(0)`, only `transform`/`opacity` are animated, and reveal
  effects use interruptible transitions rather than keyframes.
- **Tuned for laptop / tablet / mobile specifically** — verified with
  zero horizontal overflow across all 41 pages at 1440px (laptop),
  834px/768px (tablet portrait & landscape), and 390px/375px (mobile);
  full nav collapses to a slide-out menu ≤1120px; hero grid stacks to a
  single column ≤820px; 3D scenes and particles progressively disable
  on smaller/touch screens to protect performance and battery.
- **Fully self-hosted** — Inter, Three.js, anime.js and tsParticles all
  live locally under `site/assets/` (`assets/vendor/`). Nothing is
  fetched from Google Fonts or any CDN, so the site works completely
  offline.
- **Live contact & quote forms** — both submit to the local backend
  (`/api/contact`, `/api/quote`) and land straight in the admin portal.
  They still work even with JavaScript disabled (the `<form>` tags have
  a static `action`/`method`/field names as a fallback).
- **Live document library** on the Downloads page — automatically shows
  whatever PDFs have been published from the admin portal.

A note on component libraries: DaisyUI and "Origin UI" are Tailwind/React
component kits that need a build pipeline to work, which doesn't fit
this project's 41 hand-built vanilla HTML/CSS pages without risking a
full rewrite. Three.js, anime.js and tsParticles were used instead
because they drop into the existing architecture cleanly while
delivering the same premium, animated, 3D-enhanced result.

## 4. The admin portal — `/admin`

| Page | What it does |
|---|---|
| `/admin/login` | Sign in |
| `/admin` | **Enquiries** — every contact/quote submission, filterable by type and status (New / Contacted / Closed), with one-click status updates and delete |
| `/admin/documents` | **Documents** — upload a PDF (title + category), it's instantly live on the public Downloads page; delete removes it from both places |
| `/admin/settings` | Change your admin password |

Everything in `/admin/*` and `/api/admin/*` requires a logged-in session
— trying to load the dashboard or call the admin API while signed out
redirects to the login page / returns `401`.

## 5. Data & storage

- **Enquiries and document metadata** live in `data/ladli.db` (SQLite —
  a single file, no separate database server to install).
- **Uploaded PDFs** are saved to `uploads/` with a randomised filename
  (the original filename is kept only as a label); only `.pdf` files up
  to 25 MB are accepted.
- To start completely fresh, stop the server and delete `data/ladli.db`
  (a new one, with a new admin account, will be created on next start).
  Deleting `uploads/*.pdf` will break links to any documents already
  published — delete documents through the admin portal instead so the
  database and files stay in sync.

## 6. Before you deploy this beyond your own machine

The built-in server (`python app.py`) is meant for local use and small
internal deployments. Before exposing it on the internet:

1. **Put it behind HTTPS.** Run it behind a reverse proxy (nginx, Caddy)
   or a production WSGI server (gunicorn/waitress) with a real TLS
   certificate — the admin login should never travel over plain HTTP.
   (PythonAnywhere, see section 7, gives you this automatically.)
2. **Set your own admin password on first login** — the portal now
   forces this automatically (see section 1) and locks itself to
   5 failed login attempts per 15 minutes, so there's nothing extra to
   configure here beyond picking a strong password when prompted.
3. **Replace the placeholder domain.** `sitemap.xml`, canonical tags,
   and the JSON-LD schema in `site/` currently use
   `https://www.ladlielectricaltesting.com` as a placeholder — swap it
   for your real domain.
4. **Back up `data/ladli.db` and `uploads/`** regularly once this is
   handling real enquiries.
5. Hold off on publishing any NABL/ISO/accreditation claims, fixed
   turnaround times, or client/test counts until they're formally
   approved — this was flagged in the original handover pack and
   still applies.

## 7. Going live on PythonAnywhere

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for a full step-by-step guide
to putting this site live on PythonAnywhere's free tier, including
account setup, uploading the project, and the WSGI/static-file
configuration.

If you already have this project live on PythonAnywhere, upload the
current repository files there and replace the PythonAnywhere WSGI file
with [wsgi_pythonanywhere.py](wsgi_pythonanywhere.py). Then set the
project path in the WSGI file to the folder that contains `app.py`, and
reload the web app.

You should also copy your `.env` settings to the PythonAnywhere host so
the same mail/database configuration is used there. If the server already
has `data/ladli.db`, your existing admin data will stay in place.

## 8. Brand reference

Royal Blue `#1F6FE5` · Light Sky Blue `#67C5F8` · Bright Pink `#E95AA5` ·
Golden Orange `#F9A825` · White `#FFFFFF`

LADLI Electrical Testing and Calibration Laboratory Pvt. Ltd.
A/39, First Floor, Shrenik Park, Opp. Akota Stadium, Productivity Road,
Akota, Vadodara – 390020, Gujarat, India
Phone: +91 84908 38981 · Email: ladlielec@gmail.com
