# Service and CLI

## Commands

```bash
granum open [--browser] [--no-window]              # open the Granum window (starting the service if needed)
granum app install [--port N] [--no-autostart] [--no-launcher]
granum app status
granum app uninstall                               # removes service and launcher; data is kept
granum version
granum service [--open] [--host 127.0.0.1] [--port 8000] [--data-root DIR]... [--allow-host H]... [--allow-origin O]...
               [--scan-interval S] [--watch/--no-watch] [--cache-size BYTES] [--cache-timeout S]
granum import coco SPLIT=PATH... --project NAME [--dataset NAME] [--media full|sample|none]
                   [--choose CODE=OPTION]... [--check-only] [--fail-on block|warn|never] [--json]
granum thumbnails create <table-or-run-url>
granum config show | path | validate
```

Global options go before the command: `granum --project-root-url /data/granum service`.

## Configuration

Settings resolve, highest priority first, from command-line flags, environment variables, the project, user and system config files (`granum config path`), then built-in defaults. `granum config show` reports where each value came from.

| Setting | Environment variable | Default |
|---|---|---|
| `project-root-url` | `GRANUM_PROJECT_ROOT_URL` | `~/granum` |
| `service.port` | `GRANUM_SERVICE_PORT` | `8000` |
| `service.data-roots` | `GRANUM_SERVICE_DATA_ROOTS` | your home folder |
| `service.allowed-origins` | `GRANUM_SERVICE_ALLOWED_ORIGINS` | none |
| `log-level` | `GRANUM_LOG_LEVEL` | `WARNING` |
| `log-file` | `GRANUM_LOG_FILE` | none |

The project root may be a local path or an fsspec URL (`s3://`, `gs://`, `az://`) with the matching extra installed.

## Running as an app

`./install.sh` (or `granum app install`) sets Granum up to run without a terminal:

| Piece | File | Notes |
|---|---|---|
| Background service | `~/.config/systemd/user/granum.service` | Starts at login, restarts on failure. Manage with `systemctl --user status granum` (or `restart`, `stop`) |
| Launcher | `~/.local/share/applications/granum.desktop` | Runs `granum open`, which shows Granum in its own window |
| Window storage | `~/.local/share/granum/window` | Browser storage for the window: reviewer name, unsaved-edit recovery |
| Log | `~/.local/state/granum/service.log` | Service output |
| Project root | `~/.config/granum/config.granum.yaml` | Pinned at install, so the service, launcher and terminal always use the same data |

Installing again rewrites these files and restarts the service; project data is never modified. The
service works in `~/granum-training` (beside the project root), so pretrained weights the trainer
downloads are kept there.

The service starts when you log in. To keep it running when you are logged out (for example on a
shared workstation), enable lingering once: `sudo loginctl enable-linger $USER`.

On macOS and Windows the service and launcher are not installed; `granum open` starts Granum in the
background on demand.

## Security model

The service reads your data locally and serves it to the dashboard. Nothing is uploaded.

- **Paths**: every client-supplied URL is checked before it is opened. Object URLs must sit under a
  scan root, media URLs must be referenced by an indexed table or a running preflight, and import
  sources must sit under a data root.
- **Local access**: a service on 127.0.0.1 is still reachable from any web page open in the browser.
  Requests must carry a loopback `Host` (defeating DNS rebinding), cross-origin requests are refused
  unless allowed with `--allow-origin`, and writes must be JSON.
- **No authentication yet.** Binding to another address prints a warning. Shared deployments are not supported.

## REST API

Interactive documentation is served at `http://127.0.0.1:8000/docs`.

| Area | Endpoints |
|---|---|
| Meta | `GET /api/health`, `GET /api/stats`, `POST /api/reindex` |
| Projects | `GET /api/projects`, `GET /api/projects/{project}/tables`, `.../runs`, `.../lineage`, `.../imports`, `.../imports/{id}`, `POST /api/projects/{project}/rename`, `POST /api/projects/{project}/delete` |
| Tables | `GET /api/table`, `GET /api/table/rows`, `GET /api/table/arrow`, `GET /api/table/sample`, `POST /api/table/commit` |
| Runs | `GET /api/run`, `GET /api/run/joined`, `GET /api/run/learning`, `GET /api/run/image-rounds` |
| Media | `GET /api/media` (with optional `size` for thumbnails) |
| Import | `GET /api/import/browse`, `POST /api/import/preflight`, `POST /api/import/commit` |
| Jobs | `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel` |
| Review and shipping | `GET /api/qa`, `GET /api/qa/version`, `GET /api/qa/image`, `POST /api/qa/status`, `POST /api/qa/comment`, `POST /api/qa/isolate`, `POST /api/qa/return`, `POST /api/qa/delete`, `POST /api/qa/ship` |
| Curation | `GET /api/reviews`, `POST /api/reviews`, `GET /api/reviews/history`, `POST /api/datasets/remove`, `GET /api/datasets/removed`, `POST /api/datasets/restore` |
| Training | `GET /api/training/status`, `POST /api/training` |

Example: ship one set, as a chosen version, once every image in it is reviewed.

```bash
curl -s "http://127.0.0.1:8000/api/qa?project=aerial&dataset=human_aerial" | jq '.ready'
curl -s -X POST http://127.0.0.1:8000/api/qa/ship \
     -H 'Content-Type: application/json' \
     -d '{"project": "aerial", "dataset": "human_aerial", "author": "ana", "note": "batch 1",
          "sets": {"train": "<url of the train version to ship>"}}'   # omit "sets" to ship the newest version of every set'
```

`POST /api/training` returns `409` for any version that has not been shipped.

## Training jobs

`POST /api/training` starts `python -m granum.training.train` on the service's machine, one job at a time.
Trainings outlive the service: each trainer runs in its own session with its output in
`~/.local/state/granum/training/*.log`, the installed service stops only itself on restart (`KillMode=process`),
and a restarted service reconnects to trainers that are still running, so progress, the log and Cancel keep
working. A dashboard run whose trainer died while no service was watching is marked **Interrupted**. Progress, phase and log lines are available from `GET /api/jobs/{id}`, and cancelling
terminates the process and marks the run cancelled. Supported families are listed by
`GET /api/training/status` with whether each is installed and the GPU found.
