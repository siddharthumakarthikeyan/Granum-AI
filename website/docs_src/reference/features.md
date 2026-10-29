---
title: Feature availability
summary: Find every workflow, its current availability and the guide that explains how to use it.
---

Use this index to find a capability before choosing a workflow. These statuses describe the **current
development source**, reviewed on 19 October 2026. A downloaded installer can contain an earlier
revision; compare `granum build-info` with the build supplied to you.

| Status | Meaning |
|---|---|
| **Available** | The named workflow is implemented. Its guide states dependencies and limits. |
| **Partially included** | A useful part works; the missing part is explicitly identified in the guide. |
| **Not yet included** | A reserved feature section. There is no supported Granum workflow for it yet. |

A status is specific to the capability in its row. For example, displaying a three-dimensional scatter
plot does not provide point-cloud annotation, and importing semantic masks does not provide a dashboard
semantic trainer. Optional dependencies and workspace permissions still apply to available features.

## Follow the complete workflow

Start with [installation](/docs/start/install), then follow the [guided course](/docs/course/start).
For your own data, move through [import](/docs/guides/import), [inspection](/docs/explore/workspace),
[review](/docs/guides/review), [dataset versions](/docs/guides/dataset-versions),
[training](/docs/guides/train), [comparison](/docs/guides/compare) and [export](/docs/improve/export).
Python users can enter the same workflow through [tables](/docs/python/tables) and
[per-sample metrics](/docs/measure/metrics).

The feature groups below link to working instructions or to a reserved section labelled **Not yet
included**. Reserved sections describe scope without inventing commands, configuration or release dates.
