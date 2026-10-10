---
title: 2. Understand the sample
summary: Learn images, boxes, classes and splits, then examine the real taxonomy and duplicated-holdout problems in the supplied export.
---

**Goal:** know what you are importing and which conclusions the data can support.
Complete [workspace setup](/docs/course/setup) first. No model has to be trained to do this inspection.

## What is object-detection data?

An **image** is the input a detector sees. An **annotation** says where a particular object is and
which **class** it belongs to. One image can contain zero, one or hundreds of objects.

In COCO, an image record has an ID, a file name, width and height. Each annotation refers to that image
ID and a category ID. A COCO bounding box is `[x, y, width, height]` in image pixels, measured from the
top-left. Granum's internal box representation can instead use two corners; the importer performs that
conversion. Do not copy coordinate arrays between formats without checking their meaning.

For example, the course's one-pedestrian training image is 960 × 540. Its source box starts at
`(425, 228)` and is 53 × 95 pixels; the corresponding opposite corner is `(478, 323)`. A good-looking
rectangle is not by itself proof of the right class or of complete annotation coverage.

## Why split data?

| Split | Job | What goes wrong if reused carelessly? |
|---|---|---|
| Train | Fit the model's weights | Training performance alone overstates generalisation |
| Validation | Select settings/checkpoints and inspect development behaviour | Repeatedly tuning against it makes it part of model development |
| Test | Evaluate the selected final procedure on an independent holdout | Copies, neighbouring frames or tuning on test destroy that independence |

Frames from the same flight or capture sequence can be nearly identical without having the same file
hash. Splitting individual files randomly is not sufficient protection. Prefer a documented group
boundary such as flight, site, day or camera appropriate to the deployment question.

## Where this sample came from

The local supplied export identifies itself as **Aerial Person Detection**, v1, exported on
16 September 2026 at 12:22:18 UTC, from
[val-data on Roboflow Universe](https://universe.roboflow.com/val-data/aerial-person-detection-fhrsh).
It declares [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The course subset keeps selected image bytes and annotation objects unchanged. Its attribution names
the source and explains the subset selection. That licence notice is the supplied export's declaration,
**not independent verification of upstream ownership**. Check applicable rights and privacy requirements
for your intended use; keep attribution when redistributing. No source-provider endorsement is implied.

## What the source actually contains

The source was inspected, not inferred from the dataset's name:

| Original source folder | Images | Annotation objects |
|---|---:|---:|
| train | 11,335 | 621,186 |
| valid | 547 | 40,126 |
| test | 547 | 40,126 |

**The validation and test annotation files are byte-identical, and all 547 corresponding image pairs
are byte-identical.** The repeated test folder is not an independent holdout. The export's stated
11,882-image count corresponds to train plus validation, not counting that repeated folder again.

The source description also mentions horizontal-flip augmentation and multiple versions per source
image. The course does not assume that differently named variants are independent observations.

## What the course includes

| Course split | Images | Source annotation objects | Ignore-region objects | Other objects |
|---|---:|---:|---:|---:|
| train | 96 | 5,720 | 158 | 5,562 |
| valid | 24 | 1,780 | 70 | 1,710 |
| Total | 120 | 7,500 | 228 | 7,272 |

Selection is deterministic with seed **20261002**. Validation is selected first. Training excludes
filename-prefix sequences found anywhere in the source validation split. Selected byte-identical
images and repeated frame variants are excluded. The manifest records per-file sizes and SHA-256 hashes.

**Filename-prefix separation is a heuristic, not proof of scene independence.** This tiny subset is
learning material, not a benchmark. No images were resized and no labels were deliberately corrupted
to create an impressive “before and after.”

## Read the classes before training

The 13 source category entries are: people (ID 0), awning-tricycle, bicycle, bus, car, ignored regions,
motor, others, pedestrian, people (ID 9), tricycle, truck and van.

Two things need an explicit decision:

1. **“people” appears twice.** ID 0 is unused; ID 9 is used. The import merges duplicate names. It does
   not mean that **pedestrian** should also be merged with **people**. Similar words may encode different
   labelling policies. Resolve that with the data owner rather than guessing.
2. **“ignored regions” is not an ordinary target class.** The source marks those boxes with `iscrowd=0`.
   Preflight recommends preserving them as ignore/crowd regions (`iscrowd=1`). Otherwise a model may be
   rewarded or penalised for regions intentionally not individually labelled.

Under the recorded import decisions, 12 category entries remain and all 228 ignore-region boxes are
retained as ignore/crowd. YOLO training export omits those boxes as positive training targets; an
evaluator must separately implement the intended ignore semantics. Not every third-party format does.

## What we learn

Dataset names and README totals are starting points, not guarantees. Structural checks can identify
repeated files and taxonomy problems. They cannot determine whether every distant object is labelled,
whether your class definitions fit the business problem, or whether the sample represents deployment.

## Checkpoint

Explain, in your own words: “120 images is not 120 boxes; there is no independent test; duplicate class
names and ignore regions need different decisions.” Then [import with preflight](/docs/course/import).

## If something differs

If your extracted counts differ, check that you downloaded the course archive rather than the full
source export. If your organisation has a different labelling policy, preserve the sample for this
exercise and start a separate project for the policy change. Do not silently rewrite the course archive.