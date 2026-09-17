# Development

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,service,images,pandas]"
cd web && npm ci && cd ..
```

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

A wheel built after the dashboard build contains it, so `pip install granum-*.whl` followed by
`granum service` is the whole setup on another machine. Without a dashboard build the package still
builds and the service serves the API only.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

- **test**: `ruff check src tests` and `pytest` on Python 3.10, 3.11 and 3.12
- **web**: `npm ci`, `npm run test` and `npm run build` on Node 20

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
