# Granum website and licence server

The public site (landing page, email-gated download, product documentation, privacy notice)
and the licence server the Granum app signs in to, in one Vercel project. It lives in the
`website/` folder of the app's repository; every path below is relative to that folder, and
commands are run from it.

**Current channel: unrestricted-alpha.** The app's licensing enforcement remains disabled.
Public copy must not promise a timed trial, automatic expiry or paid quotas that this build does
not enforce. Granum is proprietary: use, pilot support and any fees require written agreement.
Quote handling is manual; no payment processor or self-service subscription flow is implemented.

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

The primary first-use path is the [guided aerial-data course](docs_src/course/start.md): 12 numbered
lessons plus an introduction, a real 120-image sample, 35 screenshots, 10 captioned recordings and actual
model/restore evidence. It does not use the homepage's illustrative metrics or claim production accuracy.

Course assets live under `public/assets/course`, **outside** the docs builder's cleanup directory.
Use [tools/COURSE.md](tools/COURSE.md) for safe sample regeneration, real-app recording, caption/media
requirements, preview and validation. `tools/preview_docs.py` provides a loopback-only clean-URL static
preview without starting the licence server or accessing a production database.

## What happens, end to end

Pilots: the **Discuss a pilot** and **Discuss requirements** actions open `/quote`.
`POST /v1/quote` stores the request (plan, computers, billing in the message) and emails it to
`CONTACT_EMAIL` with Reply-To set to the requester. The legacy Single/Team/Enterprise values remain
API-compatible request categories, not active subscription entitlements. Agree scope and any fees
manually; never claim that submitting the form charges the customer or grants usage rights.

1. Someone opens the site and clicks **Download**. They enter their email (name and company
   optional) and pick Windows or Linux. `POST /v1/download` records them and returns the
   installer links **only if their release metadata passes the publication gate**. Email verification
   uses `/v1/download/code` first and does not start an app trial.
2. The unrestricted alpha requires no in-app activation or licence renewal.

### Preserved licensing backend (not the current alpha restriction)

For an explicitly licensed build, the app can ask this server to email a 6-digit code
   (`/v1/login/code`), then signs in with it (`/v1/activate`).
The server decides: an email with a live paid plan gets that plan on the computer (if a
   machine slot is free); otherwise a **7-day free trial with 1 project**, once per email and
   once per computer. It answers with a licence key signed by the owner's private key.
Such a build renews the key every 6 hours while online (`/v1/refresh`) and works 7 days
   offline. Past the plan's end it turns read-only by itself.

These endpoints and manual grant tools remain tested. Enabling them commercially also requires an
explicit app policy change, matching public terms, payment/account operations and release qualification.
The presence of a trial-issuing API does **not** make trial claims true for an unrestricted binary.

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

1. **Import** the app's repository in Vercel: *Add New → Project → Import*, or on an existing
   project *Settings → Git* to connect it. Production branch `main`.
2. *Settings → Build and Deployment*: **Root Directory** `website`. Framework preset **Other**;
   leave the build and output settings empty (vercel.json sets them). To deploy only when the
   site changes, set **Ignored Build Step** to `git diff --quiet HEAD^ HEAD -- .`
3. **Database**: in the project, *Storage → Create Database → Neon (Postgres)*, and connect it
   to the project. That adds `DATABASE_URL`. Tables are created on first use.
4. **Environment variables** (*Settings → Environment Variables*, for Production):

   | Name | Value |
   |---|---|
   | `LICENCE_SIGNING_KEY_PEM` | the private key supplied directly through a secret manager; never commit it or send it through chat. Mark it **Sensitive**. |
   | `LICENCE_ADMIN_TOKEN` | a long random secret: `openssl rand -hex 32`. Only for your own tools and backend. |
   | `SMTP_HOST` / `SMTP_PORT` | `smtp.gmail.com` / `587` |
   | `SMTP_USER` / `SMTP_PASSWORD` | your Gmail address / a Gmail **app password** (Google Account → Security → 2-Step Verification → App passwords) |
   | `SMTP_FROM` | `Granum <you@gmail.com>` |
   | `CONTACT_EMAIL` | where people write to you (shown on the site) |
   | `DOWNLOAD_RELEASE_REPOSITORY` | optional; the public repository whose approved release is offered. Default `siddharthumakarthikeyan/Granum-AI` |

   The download links, version, checksums and manifests need no variables: they come from the
   approved release (next section). Setting `DOWNLOAD_WINDOWS_URL` or `DOWNLOAD_LINUX_URL` switches
   to links set by hand instead, which then also need `APP_VERSION`, `APP_SOURCE_REVISION`,
   `DOWNLOAD_<OS>_SHA256`, `DOWNLOAD_<OS>_MANIFEST_URL` and `APP_RELEASE_QUALIFIED=1`.
   | `LICENCE_TRIAL_DAYS` / `LICENCE_TRIAL_PROJECTS` | optional; default `7` / `1` |

   Never set `LICENCE_DEV` in production: it returns sign-in codes in responses.
5. **Deploy**, then open `https://<project>.vercel.app/v1/health`; it answers `{"ok":true}`.

## The download the site offers

Vercel is not for 200 MB files; the installers are GitHub release files of the app's repository.

1. **Every push or merge to `main`** builds the Windows Setup.exe and the Linux AppImage, each with a
   `.sha256` and a `.manifest.json`, and keeps them as the *Build of main* pre-release (tag
   `main-build`), replacing the build before. The site does not offer this.
2. **You approve a build**: on GitHub, *Actions → publish-download → Run workflow*. It checks that both
   installers are the bytes their checksums and manifests describe and were built from one clean commit,
   then publishes them as a full release (`build-<version>-<commit>`) carrying `release.json`.
3. **The site follows**: `api/_licence/releases.py` reads the newest full release's `release.json`
   (asked again every five minutes) and passes it through the same publication gate as before: a
   known channel, a real commit, an https link, a 64-character checksum and a manifest per installer.
   With no approved release, or one that fails the gate, the site shows no current desktop release.

Approving is the publication decision. Before running the workflow, rehearse installation, launch,
import/edit/reload, backup/restore, upgrade and uninstall of the *Build of main* files on the operating
systems you list as supported; the workflow proves the files are what they say, not that they work on a
clean machine. Windows remains unsigned unless separately signed. To withdraw a download, delete its
release on GitHub: the site returns to the approved build before it.

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

Future payment integration (not implemented) could call the same operations over HTTP:
`POST /v1/admin/grant`, `/v1/admin/extend`, `/v1/admin/revoke`, `/v1/admin/free-machine`,
`GET /v1/admin/account?email=`, each with `Authorization: Bearer $LICENCE_ADMIN_TOKEN`.

## Notes

- `api/_licence/token.py` is a copy of `granum/licensing/token.py` in the app. Keep them identical.
- Vercel's Hobby plan is for non-commercial use; move to Pro before selling.
- The Windows installer is not code-signed yet, so SmartScreen asks users to confirm. The
  download page and FAQ say so.
