---
title: Scale and limits
summary: Measured local workflows, enforced view budgets, and unqualified deployment limits.
---

## Measured, not universal

Qualification on 2 October 2026 used Linux x86-64, Python 3.10.12, Node 24.18.0 and headless Chromium
153, on a host exposing 20 logical CPUs. The reproducible fixture uses unique 128×128 PNG paths,
eight boxes per image and repeated synthetic values. It is not a real dense-data or GPU-training benchmark.

| Workflow | Observed result |
|---|---|
| 10,000 images, 12 epochs, 120,000 metric rows: collection without predictions | 0.257 seconds; 0.68 MiB Parquet |
| Same collection with predictions | 2.520 seconds; 0.90 MiB Parquet |
| Images API | 0.123 seconds; 2.55 MiB JSON |
| Joined run, cold / cached first page | 1.385 / 0.044 seconds; 6.08 MiB JSON |
| Whole benchmark process peak RSS, including fixture construction | 502 MiB |
| Browser gallery, 10,000 images and 2 epochs | 495 ms to first visible card; 47 ms status-filter interaction; 12.6 MiB JS heap snapshot |

These are individual measurements, not latency guarantees or percentile statistics. Synthetic repeated
values compress unusually well. JS heap is not total browser memory or peak GPU memory. Collection time
excludes inference and therefore is **not a percentage of training overhead**. The browser check loads
gallery metadata and a visible screenful, not every full-resolution image or a full multi-epoch run.
Both primary editors also passed reload recovery, failed-save retention and successful commit checks
at 120 and 10,000 images in that browser suite.

The run join was optimized to skip older epochs' unused geometry; the same cold API workload fell from
16.3 seconds to 1.4 seconds. A million-point rendering demonstration does not qualify the complete workflow.

## View budgets

- Images workspace/review: **25,000 images** across the requested sets.
- Materialized inspection/analysis: **250,000 rows** and **128 MiB uncompressed Parquet** per guarded request.
- Browser JSON: **64 MiB per response**, with a **64 MiB accumulated row-data budget** for paged inspection.
- Inconsistent or incomplete pages, changed source revisions and oversized responses fail explicitly.
  They are not silently displayed as complete data.

These are defensive ceilings, not tested maximum capacities. Narrow the dataset, omit older epochs or
heavy predictions, or use the SDK for larger offline analysis. Some background operations and media/backup
work still materialize data and need their own memory planning; the service is not a streaming warehouse.

## Current limits

- **Local mode:** loopback-only and self-reported authors; do not expose it as a public service.
- **Shared mode:** authenticated HTTPS and workspace-wide viewer, annotator, reviewer and administrator
  roles. All accounts read all projects. No SSO, per-project tenancy, assignment or sync platform.
- **Durability:** coordinated local writers, immutable metadata-last publication, stale-edit checks and
  checksummed project backup/restore. No distributed-writer guarantee for cloud stores or NFS.
- **Recovery:** primary editor drafts are in the same browser profile. Clearing browser data, storage
  failure or using another device can lose access to them. Stale drafts require export/reconciliation.
- **One training job at a time** per machine.
- **Boxes.** The importer reads COCO boxes; masks, keypoints and other fields are preserved and editable,
  but the checks, metrics, findings and training are box-based.
- **Detection only, for training.** Classification data can be held and reviewed; training it is not in
  the dashboard.
- **No video.** Frames imported as images work; there is no timeline, no tracking, no propagation.
- **Windows and Linux.** No macOS build today.

## What Granum deliberately does not do

- **It is not a labelling tool.** It corrects labels well — draw, move, relabel, delete, masks,
  keypoints — but a team labelling from scratch at volume wants a dedicated annotation platform, and
  Granum imports what that produces.
- **It is not a model registry or a deployment system.** It trains, scores and records; shipping the
  weights somewhere is your pipeline's job.
- **It is not an experiment tracker.** Runs are recorded because the data work needs them, not to
  replace the tool your team already uses.
- **It will not tell you a label is wrong.** It tells you which labels are worth your attention, and
  why. → [What the evidence is worth](/docs/concepts/evidence)
- **No telemetry is added.** Cloud storage and a shared service transfer data to destinations you configure.
  → [Your data and privacy](/docs/help/privacy)
