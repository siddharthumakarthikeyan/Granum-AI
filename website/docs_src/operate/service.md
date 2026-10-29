---
title: Run the Granum service
summary: Serve the dashboard, discover projects and inspect background jobs from one workspace service.
status: available
---

The Granum service reads project records, supplies media and metrics to the dashboard, and supervises
supported jobs. The default deployment is on the same machine as the browser or desktop window.

## Start locally

```bash
granum --project-root-url ~/granum service --host 127.0.0.1 --port 8000 --open
```

Open `http://127.0.0.1:8000` for the application. The interactive service API reference is at `/docs`
on that address; it is separate from this public product documentation. `/api/health` reports the
running build and defensive limits, while `/api/access` identifies the access mode.

`granum open --browser` starts or opens the local app flow. On a configured Linux desktop install,
`granum app status` reports the background service. Use the foreground terminal when running a
manual development service rather than assuming it belongs to systemd.

## Discover projects

The index scans configured locations for Granum object directories. Watch mode and scan interval
control discovery; CLI flags include `--watch`/`--no-watch` and `--scan-interval`. When a new Python
process writes a table to the same root, it should become visible through the index.

If a table is missing, compare the writer's root with the service root, then check aliases, permissions
and the object's metadata/payload. `POST /api/reindex` refreshes discovery. Reindexing does not
reconstruct missing row data or move images into the project.

## Jobs and recovery

Imports, projections, training and related work expose job status through `/api/jobs/{id}`. Read the
phase, progress and error before repeating a request. Cancellation is explicit and can wait for a
calculation boundary.

Supervised training processes can outlive a service restart, and the service reconnects to them.
A dead trainer may be marked interrupted. Do not interpret a closed browser as a cancelled job or
start a duplicate training process without checking status.

## Shared access

Local mode rejects non-loopback peers. For team access, use the
[authenticated shared-workspace setup](/docs/operate/shared) with HTTPS. Changing only the bind host
is insufficient. Use [configuration](/docs/operate/configuration) for roots and network settings and
[operations](/docs/guides/operations) for backup, audit and recovery procedures.
