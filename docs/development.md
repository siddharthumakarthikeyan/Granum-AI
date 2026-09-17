# Development

## Setup

```bash
./install.sh --dev          # editable install in ~/.local/share/granum/venv, plus the app service
```

Or manage your own environment:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,service,images,pandas]"
cd web && npm ci && cd ..
```

With an editable install, restart the background service to load Python changes:
`systemctl --user restart granum`. Rebuild the dashboard with `cd web && npm run build`
(no restart needed; the service serves the files directly).

Optional, for training features: `pip install ultralytics rfdetr` and a CUDA build of PyTorch.

## Running locally

```bash
granum service                     # terminal 1: API and built dashboard on :8000
cd web && npm run dev              # terminal 2: dashboard with hot reload on :5173 (proxies /api to :8000)
```

Set `GRANUM_SERVICE_URL` to point the dev proxy at another service. Dev builds expose the store as
`window.__granumStore` for scripted checks.

## Tests

```bash
python3 -m pytest                  # backend
cd web && npm run test             # dashboard unit tests (Vitest)
cd web && npm run typecheck        # TypeScript
ruff check src tests               # lint
```

If a globally installed `anyio` pytest plugin breaks collection, run `python3 -m pytest -p no:anyio`.

Backend tests use an isolated project root per test and FastAPI's test client, so no service needs
to be running. Tests that need PyTorch or Ultralytics skip when those are not installed.

## Building a release

```bash
cd web && npm ci && npm run build && cd ..     # writes src/granum/service/static
pip install build && python -m build            # wheel includes the dashboard
```

The `desktop` extra (`pywebview`) provides the standalone window; `granum open --browser` works without it.

`hatch_build.py` builds the dashboard automatically when a wheel is built without it, so
`pip install .` and `pip install git+https://...` produce a complete app when Node.js is available.
Without npm the package still builds and the service serves the API only.

## Building the Linux app

```bash
packaging/linux/build-appimage.sh      # -> dist/Granum-<version>-x86_64.AppImage
```

The script downloads a relocatable CPython ([python-build-standalone](https://github.com/astral-sh/python-build-standalone)),
builds the dashboard and the wheel, installs Granum with its dependencies and PySide6 (Qt WebEngine, LGPL)
into that Python, trims unused Qt modules (`prune_qt.py`), checks that everything imports, bundles the xcb
libraries Qt needs, precompiles, and packs the result with appimagetool. Downloads are cached in `build/cache`.
Build on the oldest distribution you support (CI uses Ubuntu 22.04 with a desktop set of graphics and display libraries installed, so the build can check the window imports).

Inside the app, `AppRun` sets `GRANUM_BUNDLED=1` and ignores the user's Python packages, then runs
`python -m granum open` (or `python -m granum <args>`). `granum open` installs the app on first launch
(`granum.cli.desktop`), starts the service from the installed copy and shows the Qt window (`granum.cli.window`).

Test a build offline in an empty home, without touching your own service:

```bash
env GRANUM_NO_SYSTEMD=1 GRANUM_SERVICE_PORT=8031 XDG_CONFIG_HOME=/tmp/g/config XDG_DATA_HOME=/tmp/g/share \
    XDG_STATE_HOME=/tmp/g/state GRANUM_PROJECT_ROOT_URL=/tmp/g/granum APPIMAGE_EXTRACT_AND_RUN=1 \
    unshare -rn sh -c 'ip link set lo up && ./dist/Granum-*.AppImage'
```

`unshare -rn` removes network access for the app (loopback stays available once `lo` is up). This is how
the release was verified: service, dashboard, a full COCO import with image checks, thumbnails and review
all work with no network.

`GRANUM_NO_SYSTEMD=1` keeps the test away from your real `granum.service`.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

- **test**: `ruff check src tests` and `pytest` on Python 3.10, 3.11 and 3.12
- **web**: `npm ci`, `npm run test` and `npm run build` on Node 20

`.github/workflows/release-linux.yml` builds the AppImage on every `v*` tag (and on demand) and attaches it
to the GitHub release.

## Project conventions

- **Python**: 3.10+, type-annotated, `ruff` rules `E, F, I, UP, B` (line length is not enforced).
  Public behaviour gets a test in `tests/`.
- **Immutability**: never modify a stored table; derive a new version with its parent and producer set.
- **Service endpoints**: validate every client-supplied path with the existing root checks; return
  `400` for bad input, `404` for unknown objects, `409` for state conflicts.
- **Dashboard**: TypeScript strict mode; colours and spacing from the tokens in `web/src/styles/product.css`;
  dense, professional ML-tool copy, no explainer blocks.
- **Brand**: logo files live in `brand/`. The mark is a "G" drawn as a bounding box with a cyan edit
  handle (`#22d3ee`); use the `-on-dark` or `-on-light` variant for the background.

## Repository layout

```
src/granum/
  core/          objects (Table, Run), schemas, storage, index, config, curation, reviews, qa
  formats/       COCO and YOLO
  importing/     preflight and apply
  metrics/       collectors, detection matching, dynamics
  integration/   Ultralytics, RF-DETR
  training/      model families, trainer subprocess, evaluation
  service/       FastAPI app, jobs, media cache
  cli/           `granum` command (Typer)
web/src/
  api/           typed service client
  pages/         overview, datasets, runs, learning, removed
  review/        review page, image inspector, ship dialog
  importing/     import wizard, preflight report
  training/      train dialog, progress, comparison
  shell/         sidebar, inspection workspace
  panels/ charts/ boxes/ editing/ viewer/ store/
tests/           pytest suite
examples/        runnable end-to-end scripts
brand/           logo assets
docs/            documentation and screenshots
```
