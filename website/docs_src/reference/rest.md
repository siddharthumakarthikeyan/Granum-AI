---
title: Service API reference
summary: Find endpoint families, inspect the live schema and handle jobs, access errors and conflicting revisions.
status: available
---

The running service publishes its interactive OpenAPI documentation at
`http://127.0.0.1:8000/docs` and its schema at `/openapi.json`. These are the authoritative request
fields for that installed build. Replace the address when using a configured port or shared HTTPS host.

## Read workspace state

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/projects
```

Shared mode requires authenticated HTTPS. Local Host/Origin checks are separate from authentication;
do not disable them to make an unconfigured remote client work.

## Endpoint map

| Area | Paths |
|---|---|
| Service | `/api/health`, `/api/access`, `/api/stats`, `/api/reindex`, `/api/service/quit` |
| Projects | `/api/projects`, `/api/projects/summary`, `/api/projects/{project_name}/tables`, `/runs`, `/lineage`, `/imports` |
| Project management | `/api/projects/{project_name}/rename`, `/delete`, `/imports/{import_id}` |
| Tables | `/api/table`, `/api/table/rows`, `/sample`, `/arrow`, `/commit` |
| Runs | `/api/run`, `/api/run/joined`, `/learning`, `/image-rounds`, `/findings` |
| Evaluation and comparison | `/api/run/evaluation`, `/examples`, `/outcomes`, `/api/runs/compare`, `/api/runs/compare-vision` |
| Images and import | `/api/images`, `/api/images/boxes`, `/api/media`, `/api/import/browse`, `/preflight`, `/commit` |
| Review | `/api/reviews`, `/api/reviews/history`, `/api/qa`, `/api/qa/image`, `/status`, `/comment`, `/isolate`, `/return`, `/delete` |
| Versions and approval | `/api/qa/version`, `/api/qa/release`, `/api/qa/ship`, `/api/qa/approve`, `/api/releases`, `/usage`, `/delete` |
| Dataset tools | `/api/datasets/remove`, `/removed`, `/restore`, `/export`, `/health`, `/prelabel` |
| Training and findings | `/api/models`, `/api/training/status`, `/api/training/install`, `/api/training`, `/api/findings/screen` |
| Embeddings | `/api/embeddings`, `/api/embeddings/report`, `/scores`, `/similar`, `/map` |
| Projection | `/api/analysis/methods`, `/api/analysis/reducers`, `/api/analysis/project` |
| SAM | `/api/annotations/segment/models`, `/api/annotations/segment` |
| Supporting data | `/api/formats`, `/api/library`, `/api/library/pull`, `/api/tags`, `/api/views`, `/api/augment/examples` |
| Jobs | `/api/jobs/{job_id}`, `/api/jobs/{job_id}/cancel` |

Shortened paths in a row continue that row's immediately preceding resource prefix; consult the live
schema for exact paths and HTTP methods. For example, table commits use `POST /api/table/commit`, while
table row reads use `GET /api/table/rows`.

## Mutations and jobs

Writes use JSON request bodies and enforce the current workspace role. A request can start a job;
poll its returned ID until a terminal status and inspect its result. A cancelled request is not
necessarily proof that no intermediate work happened. Confirm current state before retrying.

Stale revisions and incompatible version/approval requests can return conflicts. Refresh the source,
retain the user's draft and reconcile explicitly. Repeated arbitrary POSTs are not a general
idempotency strategy. Audit completion failures can occur after a change was saved; follow the
[recovery procedure](/docs/guides/operations).

## Scope

Legacy `/api/licence/*` routes remain in the service, but the current alpha disables licence enforcement.
A public versioned external API guarantee, organisation API-key platform and compute-plugin API are
[Not yet included](/docs/planned/enterprise). Use exact build versions for automated clients.
