---
title: Video frames and sequences
summary: Reserved video ingestion workflows and the supported route for externally extracted images.
status: planned
---

**Not yet included.** Granum does not currently provide a dedicated video-to-table importer,
frame-extraction controls or a synchronised timeline for editing video annotations.

## Intended workflow

This section is reserved for selecting a video, choosing frame intervals, keeping timestamps and
source-video identity, and reviewing labels across a sequence. A complete implementation will need
explicit rules for frame numbering, variable frame rates, media paths and sequence-aware splits.
Commands and screenshots will be added with the implementation.

## Work with extracted frames today

Extract frames with your existing media pipeline, then import the resulting image dataset through
[COCO or another supported format](/docs/data/formats). Include the source video, frame number,
timestamp and sequence ID as metadata when your input format or Python construction allows it.

Keep related frames together when designing train and evaluation sets. Nearly adjacent frames can
make an evaluation look stronger simply because the same scene appeared in training. Check the
[duplicate and leakage tools](/docs/explore/duplicates) after import, and retain the original grouping
information even when individual images are very different.

## Scope of current sequence analysis

Numeric sequence metadata can be sorted, filtered and grouped in a table. A multi-epoch metrics
trajectory follows a model observation through training; it is not a video playback timeline or an
object-tracking system. Point-cloud and synchronised sensor workflows have their own
[reserved section](/docs/planned/spatial).

When video ingestion is included, this page will contain supported containers, extraction settings,
annotation transfer rules, a worked sequence and a troubleshooting example. Until then, only the
externally prepared image workflow is supported.
