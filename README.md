# Granum website and licence server

The public site (landing page, email-gated download, product documentation, privacy notice)
and the licence server the Granum app signs in to, in one Vercel project.

```
public/            the pages: index.html, download.html, privacy.html, styles.css, site.js, assets/
public/docs/       the documentation site: GENERATED, do not edit by hand
docs_src/          the documentation's source: one Markdown file per page
api/index.py       Vercel Python function: every /v1/* request (see vercel.json)
api/_licence/      the licence server: rules (service.py), HTTP API (app.py), storage (db.py)
tools/dev.py       run everything locally, as Vercel would
tools/docs.py      build public/docs from docs_src
tools/admin.py     manage plans and see leads, against the production database
tools/illustrations.py  redraw the homepage charts (made-up numbers, captioned "Illustration")
tests/             the server's tests, and the documentation's (built output, links, anchors)
```

## Documentation

`docs_src/*.md` is the source; `public/docs/**.html` is built from it and **committed**, because
Vercel serves `public/` as it is — there is no build step in deployment.

```
pip install markdown
python3 tools/docs.py             # rebuild after editing any page
python3 tools/docs.py --check     # fail if the committed output is out of date
pytest -q tests/test_docs.py      # output up to date, every link and anchor resolves
```

Pages carry a two-line front matter (`title`, `summary`) and are Markdown with tables, fenced code,
`!!! note "Title"` callouts and raw HTML for the inline-SVG diagrams. The book's structure — sections,
order, sidebar, previous/next, the front page and the search index — is the `NAV` list at the top of
`tools/docs.py`; adding a page means adding its slug there and writing the file.

## What happens, end to end

Buying: the Pricing section's **Buy Single**, **Buy Team** and **Request a quote** open `/quote`.
`POST /v1/quote` stores the request (plan, computers, billing in the message) and emails it to
`CONTACT_EMAIL` with Reply-To set to the buyer. Answer with an invoice and payment link, then
`tools/admin.py grant` the plan once paid. Prices live in `public/index.html` and `public/quote.html`.

1. Someone opens the site and clicks **Download**. They enter their email (name and company
   optional) and pick Windows or Linux. `POST /v1/download` records them and returns the
   installer links.
2. They install Granum and open **Licence**. The app asks this server to email a 6-digit code
   (`/v1/login/code`), then signs in with it (`/v1/activate`).
3. The server decides: an email with a live paid plan gets that plan on the computer (if a
   machine slot is free); otherwise a **7-day free trial with 1 project**, once per email and
   once per computer. It answers with a licence key signed by the owner's private key.
4. The app renews the key every 6 hours while online (`/v1/refresh`) and works 7 days
   offline. Past the plan's end it turns read-only by itself.

## Run it locally

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt uvicorn pytest httpx
LICENCE_DEV=1 python tools/dev.py          # http://127.0.0.1:3000 ; codes are shown, not emailed
pytest -q tests                            # add TEST_DATABASE_URL=postgresql://… to test Postgres too
```

It reads the signing key from `~/.config/granum-admin/signing-k1.pem` unless
`LICENCE_SIGNING_KEY_PEM` or `LICENCE_SIGNING_KEY` is set.

## Deploy on Vercel

1. **Push** this folder to a new GitHub repository (it can be private).
2. **Import** it in Vercel: *Add New → Project → Import*. Framework preset **Other**; leave the
   build and output settings empty (vercel.json sets them).
3. **Database**: in the project, *Storage → Create Database → Neon (Postgres)*, and connect it
   to the project. That adds `DATABASE_URL`. Tables are created on first use.
4. **Environment variables** (*Settings → Environment Variables*, for Production):

   | Name | Value |
   |---|---|
   | `LICENCE_SIGNING_KEY_PEM` | the whole private key: output of `cat ~/.config/granum-admin/signing-k1.pem`. Mark it **Sensitive**. |
   | `LICENCE_ADMIN_TOKEN` | a long random secret: `openssl rand -hex 32`. Only for your own tools and backend. |
   | `SMTP_HOST` / `SMTP_PORT` | `smtp.gmail.com` / `587` |
   | `SMTP_USER` / `SMTP_PASSWORD` | your Gmail address / a Gmail **app password** (Google Account → Security → 2-Step Verification → App passwords) |
   | `SMTP_FROM` | `Granum <you@gmail.com>` |
   | `CONTACT_EMAIL` | where people write to you (shown on the site) |
   | `APP_VERSION` | `0.1.0` |
   | `DOWNLOAD_WINDOWS_URL` / `DOWNLOAD_LINUX_URL` | the installer links (next section) |
   | `LICENCE_TRIAL_DAYS` / `LICENCE_TRIAL_PROJECTS` | optional; default `7` / `1` |

   Never set `LICENCE_DEV` in production: it returns sign-in codes in responses.
5. **Deploy**, then open `https://<project>.vercel.app/v1/health`; it answers `{"ok":true}`.

## Host the installers

Vercel is not for 200 MB files. Use GitHub Releases on a **public** repository that holds
only the installers (your code repositories stay private):

1. Create a public repository, e.g. `granum-downloads`.
2. *Releases → Draft a new release*, tag `v0.1.0`, attach `Granum-0.1.0-Setup.exe` and
   `Granum-0.1.0-x86_64.AppImage`, publish.
3. Copy each file's link (right-click → copy link) into `DOWNLOAD_WINDOWS_URL` and
   `DOWNLOAD_LINUX_URL`, then redeploy.

The links are public once someone has them; the form is how you learn who downloads.

## Manage plans and see leads

Point the tools at the production database (Vercel: *Storage → your database → .env.local*,
copy `DATABASE_URL`):

```
export DATABASE_URL='postgresql://…'
python tools/admin.py leads                                   # who downloaded
python tools/admin.py quotes                                  # buy / Enterprise quote requests
python tools/admin.py list                                    # every trial and plan
python tools/admin.py grant --email buyer@co.com --plan Pro --days 30 --machines 5 --projects 20
python tools/admin.py extend L-XXXX --days 30
python tools/admin.py revoke L-XXXX
python tools/admin.py free L-XXXX GM-XXXX-…                   # free a computer on a plan
```

Payments (Razorpay) can later call the same operations over HTTP:
`POST /v1/admin/grant`, `/v1/admin/extend`, `/v1/admin/revoke`, `/v1/admin/free-machine`,
`GET /v1/admin/account?email=`, each with `Authorization: Bearer $LICENCE_ADMIN_TOKEN`.

## Notes

- `api/_licence/token.py` is a copy of `granum/licensing/token.py` in the app. Keep them identical.
- Vercel's Hobby plan is for non-commercial use; move to Pro before selling.
- The Windows installer is not code-signed yet, so SmartScreen asks users to confirm. The
  download page and FAQ say so.
