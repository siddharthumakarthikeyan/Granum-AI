---
title: Map of the app
summary: Every screen, what it is for, and what its controls do.
---

The sidebar provides project navigation and the available data, training and review screens. Some
analysis views open from a dataset or run. Licence controls depend on the build's enforcement mode.

## Projects

Every project on this machine as cards or a list, with a mosaic, its type and sets, counts, how much is
verified, and the last run's status. Search, sort, and create a project. Rename and delete live here too.
→ [Manage projects](/docs/guides/projects)

## Overview

One project at a glance: the data as a mosaic, headline numbers, the hardest sample from the last run,
training progress, sample dynamics, and an **Attention** list of what Granum thinks needs looking at —
import findings, unverified sets, runs that stopped.

## Images

The main working screen, in three modes.

| Mode | Turn on with | For |
|---|---|---|
| **Browse** | default | Looking: filters, ordering, annotations, the full-screen viewer → [guide](/docs/guides/browse) |
| **Review** | *Review* in the ribbon | Verifying, rework, comments, isolate, delete → [guide](/docs/guides/review) |
| **Edit** | *Edit* in the ribbon | Drawing and correcting boxes, masks, keypoints → [guide](/docs/guides/edit) |

The image workflow also provides **Create dataset**, **Removed**, **Pre-label**, **Duplicates**,
**Stats** and **Fields**. Follow [duplicate inspection](/docs/explore/duplicates),
[draft labels](/docs/improve/prelabel) and [annotation tools](/docs/guides/edit) for the full workflow.

## Table and run workspace

Linked Rows, Filters and Charts expose the data behind a dataset or run. Calculate derives columns;
Workflows saves analysis settings; Embeddings creates projections; Landmarks inspects pose properties.
→ [Inspect tables and runs](/docs/explore/workspace)

## Health

The dataset readiness view brings import, split, similarity, model-draft and review evidence together.
Follow a check to the screen that can act on it. → [Check dataset health](/docs/explore/health)

## Evaluation

Inspect a run's confusion, class results, thresholds and individual object outcomes. Its specialised
views depend on the task and stored predictions. → [Inspect model errors](/docs/explore/evaluation)

## Datasets

The dataset versions created from Images — the only data training uses. One panel each, with its sets, an
image strip, the split facts, its augmentation recipe if any, a **Train** button, and a trash button that
shows what deleting would cost. → [Dataset versions](/docs/concepts/dataset-versions)

## Runs

Every training run: model, data versions, rounds, scores, and the chart. **Train model** starts one.
Each row can open the run itself, its **Samples** (per-image learning) or a **Compare** with the run
before it. → [Read a run](/docs/guides/runs)

**Compare runs**, from the header, is the full comparison of two runs with its downloadable report.
→ [Compare two runs](/docs/guides/compare)

## Findings

A ranked queue of labels worth checking, from a run that recorded predictions each round, with split
tabs, rule and status filters, close-up cards and a full-screen reviewer.
→ [Work the Findings queue](/docs/guides/findings)

## Create project

The import wizard: name and type, then the data (a folder, other projects, or the example dataset), then
preflight, then the review step with the split slider, then import. With a project chosen it becomes
**Add data**. → [Import data](/docs/guides/import)

## Licence

The legacy activation/key screen is hidden when enforcement is disabled. Current unrestricted-alpha
builds need no in-app licence activation. Shared-workspace login is separate.
→ [Alpha access and licences](/docs/start/activate)

## Addresses

Every screen has one, so a link can be pasted into a message:

```
#/                                     Projects
#/p/<project>                          Overview
#/p/<project>/images?dataset=<name>    Images  (&review=1, &edit=1, &open=<image>)
#/p/<project>/datasets                 Datasets
#/p/<project>/runs                     Runs
#/p/<project>/table?url=<table>        Table workspace
#/p/<project>/health?dataset=<name>    Dataset health
#/p/<project>/evaluation?url=<run>     Evaluation
#/p/<project>/run?url=<run>            One run
#/p/<project>/learning?url=<run>       Samples
#/p/<project>/findings?url=<run>       Findings
#/p/<project>/compare?baseline=<run>&candidate=<run>
#/p/<project>/removed?dataset=<name>   Removed images
#/licence                              Licence
```
