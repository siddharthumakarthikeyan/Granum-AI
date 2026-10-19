---
title: Command line reference
summary: Look up the current command groups for launching, importing, configuring and protecting a workspace.
status: available
---

The executable is `granum`. Global options go before the command:

```bash
granum --project-root-url /data/granum --log-level INFO service
```

Other global options are `--config-file PATH` and `--no-config-file`. Use `granum --help` and
`granum COMMAND --help` for the complete flags in your installed build.

## Launch and inspect

| Command | Purpose |
|---|---|
| `granum version` | Print package version |
| `granum build-info` | Inspect build provenance/source identity |
| `granum service` | Serve the dashboard and API |
| `granum open --browser` | Open the application in a browser |
| `granum app install` | Install the supported background-service/launcher flow |
| `granum app status` | Inspect installed app/service state |
| `granum app uninstall` | Remove app integration; handle project data separately |

Service options include `--host`, `--port`, `--open`, `--data-root`, `--allow-host`, `--allow-origin`,
`--scan-interval`, `--watch`/`--no-watch`, `--cache-size` and `--cache-timeout`. Shared mode adds
`--auth-file`, `--tls-cert` and `--tls-key`; follow [shared setup](/docs/operate/shared).

## Import and media

```bash
granum import coco train=/data/train.json valid=/data/valid.json   --project inspection --dataset parts --check-only --json
```

Inspect the check result before running the commit form. Relevant flags include `--media full|sample|none`,
`--choose CODE=OPTION` and `--fail-on block|warn|never`. The CLI COCO importer is distinct from the
broader dashboard/Python format catalogue. `granum thumbnails create TABLE_OR_RUN_URL` builds previews.

## Configuration and access

`granum config show`, `config path`, `config validate` and `config project-root` inspect or set
configuration. Use [the settings reference](/docs/operate/configuration) for precedence and environment
variables. `granum access add-user NAME --role ROLE --file PATH` provisions a shared account using a
hidden password prompt.

## Integrity and backup

```bash
granum integrity snapshot inspection --output /backups/inspection-media.json
granum integrity verify /backups/inspection-media.json
granum backup create inspection --output /backups/inspection.zip
granum --project-root-url /data/granum-restore backup restore /backups/inspection.zip --name restored
```

Stop writers and use output destinations outside the source project. Snapshot and restore refuse
unsafe overwrites; restoration also checks archive content and limits. Read
[operations](/docs/guides/operations) before using these commands on important data.

## Training modules

The built-in trainer is a Python module: `python -m granum.training.train --help`. It expects explicit
project, table, model and run settings. Creating an SDK Run does not invoke this module. Choose the
[task-specific workflow](/docs/measure/tasks) and preserve exact input revisions.
