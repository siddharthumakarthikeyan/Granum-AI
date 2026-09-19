---
title: Files and settings
summary: Where everything lives on disk, every setting, and the command line.
---

## On disk

```
~/granum/                                   the project root
└── projects/<project>/
    ├── datasets/<dataset>/tables/<version>/ every version of every set (Parquet + a JSON descriptor)
    ├── releases/<dataset>/<id>/             frozen dataset versions, and augmented images
    ├── reviews/<dataset>.qa.jsonl           image statuses and comments
    ├── reviews/<dataset>.jsonl              findings and review decisions
    ├── reviews/<dataset>.ships.jsonl        dataset versions
    ├── runs/<run>/                          parameters, per-round scores, per-image metrics
    ├── imports/<id>.json                    preflight reports and the choices made
    └── example.json                         marks a project made from the example dataset

~/granum-training/                           weights, exports and framework run folders
~/.config/granum/config.granum.yaml          settings, incl. the pinned project root
~/.local/state/granum/service.log            service log
~/.local/share/granum/                       the installed app, its window storage, licence and add-ons
```

Everything is a plain file. Object descriptors are JSON, rows are Parquet, logs are JSON Lines. You can
read any of it without Granum, which is the point.

## Settings

Settings resolve, highest priority first: command-line flags, environment variables, then the project,
user and system config files, then defaults. `granum config show` reports where each value came from and
`granum config path` says which files are in play.

| Setting | Environment variable | Default |
|---|---|---|
| `project-root-url` | `GRANUM_PROJECT_ROOT_URL` | `~/granum` |
| `service.port` | `GRANUM_SERVICE_PORT` | `8000` |
| `service.data-roots` | `GRANUM_SERVICE_DATA_ROOTS` | your home folder |
| `service.allowed-origins` | `GRANUM_SERVICE_ALLOWED_ORIGINS` | none |
| `licence.server` | `GRANUM_LICENCE_SERVER` | the Granum licence server |
| `log-level` | `GRANUM_LOG_LEVEL` | `WARNING` |
| `log-file` | `GRANUM_LOG_FILE` | none |

The project root may be a local path or an fsspec URL (`s3://`, `gs://`, `az://`) with the matching extra
installed.

## Commands

```bash
granum open [--browser] [--no-window]     # open the window, starting the service if needed
granum app install [--port N] [--no-autostart] [--no-launcher]
granum app status
granum app uninstall                      # removes the service and launcher; data is kept
granum service [--host 127.0.0.1] [--port 8000] [--data-root DIR]... [--allow-host H]...
granum import coco SPLIT=PATH... --project NAME [--dataset NAME] [--media full|sample|none]
                   [--choose CODE=OPTION]... [--check-only] [--fail-on block|warn|never] [--json]
granum thumbnails create <table-or-run-url>
granum config show | path | validate | project-root PATH
granum version
```

Global options go before the command: `granum --project-root-url /data/granum service`.

## The service

One process, listening on `127.0.0.1:8000`. On Linux it is a systemd user unit:

```bash
systemctl --user status granum      # also restart, stop
journalctl --user -u granum -f      # or tail ~/.local/state/granum/service.log
```

It starts at login. `sudo loginctl enable-linger $USER` keeps it running while you are logged out.

## Security model

The service reads your data locally and serves it to the dashboard. Nothing is uploaded.

Three rules make a local web service safe to leave running:

- **Every URL is checked.** Object URLs must sit under a scan root, media must be referenced by an
  indexed table, and import sources must sit under a configured data root. Without that,
  `/api/media?url=/etc/passwd` would turn a local dashboard into a file-exfiltration endpoint.
- **The Host header must be one Granum allows**, which defeats DNS rebinding — a web page you have open
  in another tab resolving its own domain to `127.0.0.1`.
- **Writes must be JSON**, and cross-origin requests from origins not explicitly allowed are refused, so
  a page cannot make your browser change your data.

There is no authentication: anyone who can reach the port can use it. Keep it on the loopback address —
the default — unless you understand exactly what you are exposing.
