---
title: Run from source
summary: Set up the Python package and dashboard in an isolated development environment.
status: available
---

Use a source checkout when integrating Granum into Python or testing development features. Desktop
installation is covered separately in [Install Granum](/docs/start/install). The commands below run
from the root of an authorised Granum repository checkout.

## Prepare the environment

Use Python 3.10 or newer, a virtual environment, and Node/npm for the bundled dashboard build.
Python and model-framework compatibility must overlap; SuperGradients has a narrower verified
[environment](/docs/integrations/supergradients).

```bash
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on Linux, or `.venv\Scripts\Activate.ps1` in Windows
PowerShell. Install core service and image support:

```bash
python -m pip install -e ".[service,images,pandas]"
```

The package build hook can build a missing dashboard when its prerequisites are present. To rebuild
it explicitly after changing the web source:

```bash
npm --prefix web ci
npm --prefix web run build
```

## Start a separate workspace

Choose a development root so experiments do not accidentally become part of your working projects:

```bash
granum --project-root-url ~/granum-dev service --open
```

The service normally serves the dashboard at `http://127.0.0.1:8000`. Set `--port` when that address
already belongs to another Granum instance. Browser drafts are tied to the origin, including the port.

## Verify before importing

Run `granum version`, `granum build-info` and `granum config show`. Confirm the root reported by the
running service. Open `/api/health` at the service address if you need to check build identity through
the API. A service that serves API routes but no dashboard needs the web build above.

Import the [course sample](/docs/course/data) or create a small [Python table](/docs/python/tables),
then confirm it appears in the project list. Training packages, GPU drivers and weights are separate
from a successful core install; see [requirements](/docs/reference/requirements).
