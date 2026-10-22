---
title: Configure a workspace
summary: Resolve settings, environment variables, data roots and service options in a predictable order.
status: available
---

Configuration controls where Granum stores records and which resources its service may read. Confirm
the resolved settings before creating data or pointing a second process at an existing workspace.

## Inspect effective values

```bash
granum config show
granum config path
granum config validate
```

Resolution proceeds from defaults through system, user and project configuration, then environment
variables, then explicit overrides. `config show` reports provenance so an unexpected environment
variable can be distinguished from a saved file. Global CLI options precede the subcommand.

## Settings reference

| Setting | Environment variable | Default or meaning |
|---|---|---|
| `project-root-url` | `GRANUM_PROJECT_ROOT_URL` | `~/granum`; project record root |
| `service.port` | `GRANUM_SERVICE_PORT` | `8000` |
| `service.data-roots` | `GRANUM_SERVICE_DATA_ROOTS` | Import roots; platform path separator between roots |
| `service.allowed-origins` | `GRANUM_SERVICE_ALLOWED_ORIGINS` | Additional browser origins, comma-separated |
| `indexing.scan-interval` | `GRANUM_INDEXING_SCAN_INTERVAL` | `10` seconds |
| `table.row-cache` | `GRANUM_TABLE_ROW_CACHE` | `true`; current reads require the persisted row cache |
| `display-progress` | `GRANUM_DISPLAY_PROGRESS` | `true` |
| `log-level` | `GRANUM_LOG_LEVEL` | `WARNING` |
| `log-file` | `GRANUM_LOG_FILE` | Empty unless configured |
| `licence.server` | `GRANUM_LICENCE_SERVER` | Legacy licence service location; current alpha enforcement is disabled |

Do not disable the row-cache setting expecting automatic reconstruction; that path is
[Not yet included](/docs/python/storage#row-caches-and-indexing).

## Set the storage location

A YAML configuration can include:

```yaml
project-root-url: /srv/granum
service:
  port: 8000
  data-roots: /srv/datasets
```

Changing the project root selects another location; it does not migrate existing records or media.
Restart a long-running service when changing the environment it inherited. CLI `--data-root` can be
repeated; `--allow-host` and `--allow-origin` serve different purposes from authentication.

## Configure Python separately

```python
import granum

config = granum.Config.load(overrides={"project-root-url": "/tmp/granum-example"})
granum.set_config(config)
```

Python overrides affect that process. They do not modify an already running service's configuration.
Use [URL aliases](/docs/python/storage#urls-and-aliases) for logical media roots and
[shared access](/docs/operate/shared) for authentication/TLS. File locations vary by platform; see
[Files and settings](/docs/reference/files).
