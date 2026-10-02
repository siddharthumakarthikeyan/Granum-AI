# Build identity and release qualification

## What is now enforced by packaging

- The dashboard build writes a stamp containing hashes of its frontend inputs and built files.
- The wheel build verifies that stamp. An existing but stale/incomplete dashboard is rebuilt; it is
  not silently shipped just because an old HTML entry point exists. An API-only build without npm is
  still possible, but it is not a desktop release.
- Every new wheel embeds a format-1 build manifest: version, UTC build time, Git revision, dirty state,
  actual licensing policy/channel, package hash, build-input hash and dashboard stamp.
- Desktop packagers verify embedded wheel hashes and version, including a reused Windows `-Wheel`.
  Old unstamped wheels must be rebuilt. The installed/bundled Python runs a smoke check with `-I`
  so checkout imports and user site packages cannot mask packaging failures.
- Final artifacts receive adjacent `.manifest.json` and `.sha256` files. The manifest records the
  exact packaged source, Python/platform, dependencies and **unsigned** status; it does not certify
  a fresh machine, a trusted signature or customer readiness.

`granum build-info` and `/api/health` identify the installed build. A mutable checkout is labeled as
such, rather than pretending its last packaged manifest describes all subsequent edits.

## CI versus publication

Linux and Windows release jobs depend on the backend/frontend/browser CI workflow. Tagged releases
set `GRANUM_RELEASE_BUILD=1`: a clean, known Git revision, matching tag/package version and valid dashboard
are required. Artifacts and sidecars are attached as **prereleases**. Windows CI additionally defines
fresh silent install, installed-package smoke and uninstall checks.

These workflow definitions have been added, not run on GitHub in this editing session. Local validation
built and installed a fresh wheel in an isolated environment and ran its package/data/service-creation
smoke test. Because changes are uncommitted, that wheel correctly records `source_dirty: true`; it is
not a publishable clean release. Do not relabel it as one.

### Local evidence — 2 October 2026

| Check | Result |
|---|---|
| Backend suite, Python 3.10.12 | 560 passed, 1 skipped |
| Backend/build-helper Ruff checks | Passed |
| Frontend source unit tests | 185 passed |
| Application and browser-test TypeScript checks; production dashboard build | Passed |
| Chromium gallery + both editors' reload/failed-save/commit workflows | 3 passed at 120 images; 3 passed at 10,000 images |
| npm dependency audit | 0 known vulnerabilities reported |
| Website API/publication/copy/email tests | 20 passed |
| Website docs generation and JavaScript syntax | Passed |
| Fresh wheel hashes, isolated installation and installed-package smoke | Passed; dirty unrestricted-alpha, not a clean release |

This is source-workspace qualification on the Linux host documented in [scaling](scaling.md), not
evidence of live website deployment, successful GPU training, or clean-machine installer qualification.

## Operator checklist

1. Review/commit the intended source, leaving secrets, databases and local data out of Git. Choose a
   package version and matching tag. Existing installer dates do not establish freshness.
2. Run full backend tests/lint, frontend tests/typecheck/build, browser recovery tests and security audit.
   Retain platform-specific reports and benchmark workload parameters.
3. Build both packages from the reviewed commit. Validate the wheel and final artifact hashes, channel,
   version, source revision and clean state. Keep the manifest, checksum and installer together.
4. On a fresh supported OS, test install, launch, a real small dataset import/edit/reload, exploratory
   version creation, approval refusal/success, stale edits, backup/restore, upgrade and uninstall.
   Check that user projects survive upgrade/uninstall. Rehearse shared HTTPS access if offered.
5. Qualify actual GPU/model training separately. Package-import smoke is not a successful model run.
6. Windows is unsigned. Follow organizational policy; do not tell users to bypass warnings blindly.
   If signing is introduced, hash the **final signed bytes**, update the manifest and validate the chain.
7. Publish an alpha with exact supported platforms and limitations. Re-download public artifacts and
   verify hashes. Checksums detect corruption; authenticity still depends on the trusted release channel.
8. Only then configure the website's source revision, per-platform SHA-256 and HTTPS manifest URLs,
   and explicitly set `APP_RELEASE_QUALIFIED=1`. Bare download URLs are withheld by default.

The website gate validates metadata, not remote bytes, a signature, or the truth of a human sign-off.
The operator owns the qualification decision. Do not set the flag simply to make an old download visible.

## Commercial policy

`ENFORCED=False` remains unchanged. The channel is **unrestricted-alpha**, not a timed trial or active
metered subscription. Public marketing and documentation now say this. Proprietary written usage
permission still applies. Pilot scope, support and fees are manual agreements; the quote form is not
checkout. Existing licensing/admin APIs are retained, not claimed as automated payment processing.

Enabling commercial enforcement in a future release requires a deliberate policy decision, consistent
terms/UI/server behavior, tested account/payment operations and a newly qualified artifact. Machine
licensing is not workspace authentication or enterprise tenancy.

## Still outside local qualification

Clean-machine Windows operation and signing; hardware power-loss recovery; cloud/NFS multiwriter
behavior; GPU training across supported families; SSO/project tenancy; public website deployment;
live email deliverability, billing and customer acceptance. Record evidence before making those claims.