# Measured workflows and defensive budgets

## Reproduce

The fixture is temporary and does not touch existing projects:

```sh
python3 tools/benchmark_workflows.py --images 1000 --epochs 6 --boxes 8
python3 tools/benchmark_workflows.py --images 10000 --epochs 12 --boxes 8
cd web
npm run build
GRANUM_BENCHMARK_IMAGES=10000 npx playwright test --reporter=json
```

The Python benchmark requires the service/images extras and the test HTTP client. The browser suite
requires its installed Chromium (`npx playwright install chromium`). Python resource reporting in this
benchmark is Unix-specific. It serves an isolated fixture for browser tests and cleans it up afterward.

## Observations — 2 October 2026

Host: Linux 6.8 x86-64/glibc 2.35, 20 logical CPUs; Python 3.10.12, Node 24.18.0; Chromium
153.0.8010.12 via Playwright 1.63.0. Fixture: 128×128 PNG files, eight boxes per image, two classes,
repeated scores/predictions. One process per API benchmark; no model inference or GPU training.

| Measurement | 1,000 images × 6 epochs, initial run | 10,000 images × 12 epochs, optimized run |
|---|---:|---:|
| Metric rows | 6,000 | 120,000 |
| Collection, scores only | 0.132 s / 44,298 bytes | 0.257 s / 716,820 bytes |
| Collection, predictions included | 0.266 s / 69,396 bytes | 2.520 s / 947,628 bytes |
| Index refresh | 0.024 s | 0.159 s |
| Images API | 0.031 s / 266,178 bytes JSON | 0.123 s / 2,669,180 bytes JSON |
| Table first page | 0.108 s / 491,035 bytes JSON | 0.200 s / 2,459,036 bytes JSON |
| Joined run first page, cold | 0.784 s | 1.385 s |
| Joined run first page, cached | 0.023 s | 0.044 s |
| Joined first-page JSON | 2,176,684 bytes | 6,374,126 bytes |
| Process peak RSS, including fixture construction | 203 MiB | 502 MiB |

Before projection/reuse changes, the 120,000-row cold join took 16.267 s with 680 MiB process peak RSS.
The optimized join resolves each input once and avoids deserializing older epochs' hidden geometry.
It preserves last-epoch geometry, scalar history, input identity and collected-column behavior.

In the final **10,000-image / two-epoch browser** run: first visible gallery card in **495 ms**,
status filtering in **47 ms**, **12.6 MiB JS heap snapshot**. All three browser tests passed at both
120 and 10,000 images: gallery loading/filtering, annotation reload recovery through a failed save,
and review boxes plus a pending comment through a failed comment save and eventual commit.

These are individual observations, not percentiles or SLAs. Repeated synthetic values compress much
more than realistic dense predictions. Collection time is not total training overhead. JS heap is
not total or peak browser/GPU memory. Gallery qualification does not load every full-resolution image,
and is not a full multi-epoch browser-run benchmark. No million-image capacity claim follows from it.

## Enforced budgets

`WorkflowLimits` checks Parquet metadata before guarded materialization:

| Layer | Default |
|---|---:|
| Requested image workspace/review sets | 25,000 images |
| Guarded table/run/analysis input | 250,000 rows |
| Guarded uncompressed Parquet input | 128 MiB |
| Decoded browser JSON response | 64 MiB |
| Accumulated serialized inspection rows | 64 MiB / 250,000 rows |

Oversize requests fail with 413 and no misleading partial result. Paged loading checks total, offset,
source identity and exact page lengths. The joined cache is bounded by both run count and aggregate
row count. Tests exercise small injected budgets so refusal paths are reproducible without huge allocations.

These are ceilings, not certifications that every shape below them is fast. Object expansion, strings,
geometry, media dimensions and concurrent users change resource use. Some background/health/history and
backup workflows still materialize data; budgets are not a complete per-process memory sandbox.
For larger work, narrow the data and epochs, omit unnecessary predictions, or use the SDK offline.
Do not raise limits in a shared service without workload-specific memory and latency measurements.