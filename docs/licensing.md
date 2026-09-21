# Licensing

Granum checks a signed licence key on each computer. Without a valid key, or when the plan
has ended, the app is **read-only**: projects open, images and runs can be viewed and data
exported, but nothing can be created, edited, imported or trained.

## What a key holds

A key is `GRN1.<payload>.<signature>` (base64url). The payload is JSON; the signature is
Ed25519 over `GRN1.<payload>`. The app ships only public keys
(`src/granum/licensing/keys.py`), so it can check keys but never make them. Fields are
documented in `src/granum/licensing/token.py`: `lid`, `email`, `customer`, `plan`,
`machines`, `machine`, `kind`, `issued`, `expires`, `lease_until`, `max_projects`.

Every key is for **one machine** (`machine`, the `GM-…` id on the Licence page). A plan
for 5 machines is one licence id (`lid`) with up to 5 keys, one per machine.

## What the app enforces (`src/granum/licensing/manager.py`)

| Check | Effect |
|---|---|
| Signature, known key id | anything else is refused |
| `machine` equals this computer | a copied key does not work elsewhere |
| `expires` passed | read-only |
| `online` keys: `lease_until` passed, or 7 days of *running time* since issue | read-only until renewed |
| system clock behind the latest time Granum has seen (by 2 h) | read-only until the clock is right |
| `max_projects` reached | new projects refused; existing ones keep working |

Running time is counted with a monotonic clock while the service runs, so turning the
calendar back does not give offline time back. The latest time seen comes from the app's
heartbeat, the key's issue time and the newest object in the projects, and is stored in
two HMAC-protected files; edited or deleted state counts the offline allowance as spent.

## Issuing keys by hand (`tools/granum_licence.py`)

The private signing key stays with the owner in `~/.config/granum-admin/signing-k1.pem`
(never in this repository; keep an offline backup). Examples:

```
tools/granum_licence.py issue --email buyer@co.com --customer "Co" --plan Pro \
    --machine GM-XXXX-... --days 30 --projects 5              # offline key, 30 days, 5 projects
tools/granum_licence.py issue ... --kind online               # 7-day lease, needs the licence server
tools/granum_licence.py issue ... --lid L-ABC --machine GM-…  # another machine of the same purchase
tools/granum_licence.py inspect GRN1.…
```

`offline` keys never renew: for computers that are never online. Sell them with a fixed
end date.

## Licence server (the `granum-website` project)

A small service, deployed beside the website, that holds accounts, trials, plans and the
machines using them. It signs keys with the owner's private key and is the only clock that
counts. It is not part of the app package.

It lives with the website, in `granum-website/api/_licence/`, and runs on Vercel with a
Neon Postgres database; its README has the deployment steps.

**Rules** (`api/_licence/service.py`)

- Sign-in is by a 6-digit code emailed to the address (10 minutes, 5 tries, 5 codes an hour).
- An email with a live paid plan gets that plan on the computer, if a machine slot is free.
- Otherwise a **free trial**: 7 days, 1 project (settings below). One trial per email and one per
  computer: another email on the same computer, or the same email elsewhere, gets none.
- Keys are `online`: a 7-day lease, never past the plan's end. The app renews every 6 hours while
  it runs online. A revoked licence or a signed-out computer loses its key at the next renewal.
- Signing out in the app frees the computer's slot on the plan.

**Endpoints**

| Endpoint | Who calls it | Does |
|---|---|---|
| `POST /v1/register {email}` | the website's download form | records the email as a lead |
| `POST /v1/login/code {email}` | the app | emails a sign-in code |
| `POST /v1/activate {email, code, machine}` | the app | returns `{key, licence}`: the plan, or a free trial |
| `POST /v1/refresh {key}` | the app | a fresh key and lease |
| `POST /v1/deactivate {key}` | the app (Sign out) | frees the machine |
| `POST /v1/admin/grant {email, plan, days, machines, max_projects}` | website backend on payment | creates a paid plan |
| `POST /v1/admin/extend {lid, days}` | website backend on renewal | adds days |
| `POST /v1/admin/revoke {lid}` | website backend on refund | cancels |
| `POST /v1/admin/free-machine {lid, machine}` | website account page | frees a machine |
| `GET /v1/admin/account?email=` | website account page | plans and machines of an account |

Admin endpoints need `Authorization: Bearer $LICENCE_ADMIN_TOKEN`.

**Running it**

```
LICENCE_SIGNING_KEY=/secure/signing-k1.pem   # the private key (default ~/.config/granum-admin/signing-k1.pem)
LICENCE_DB=/var/lib/granum/licences.sqlite3
LICENCE_ADMIN_TOKEN=<long random secret, shared with the website backend only>
LICENCE_TRIAL_DAYS=7  LICENCE_TRIAL_PROJECTS=1
SMTP_HOST=… SMTP_PORT=587 SMTP_USER=… SMTP_PASSWORD=… SMTP_FROM="Granum <licence@your-domain>"
```

`LICENCE_DEV=1` returns codes in responses instead of needing email: for local testing only,
never in production. Plans can be managed by hand with
`tools/admin.py grant|extend|revoke|free|show|list|leads` in the website project.

**The app** finds the server through the config `licence.server` (env `GRANUM_LICENCE_SERVER`).
Set its default in `src/granum/core/config.py` to the real address (for example
`https://licence.your-domain.com`) before building installers; without it the Licence page
offers only keys entered by hand.
