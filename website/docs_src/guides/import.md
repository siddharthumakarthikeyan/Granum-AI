---
title: Import data
summary: Preflight checks, what each finding means, re-cutting splits, and adding data to a project.
---

Import is deliberately not a single click. Granum opens your annotation files, reads them, checks them
against the images, and shows you what it found **before writing anything**. You decide what to do about
each finding; only then is a project created.

## What Granum reads

| Source | Dashboard | Command line | Python |
|---|---|---|---|
| COCO JSON, one file per set | Yes | `granum import coco` | `Table.from_coco` |
| YOLO (`data.yaml`) | No | No | `Table.from_yolo_url` |
| Image folder, one folder per class | No | No | `Table.from_image_folder` |

The dashboard path is COCO, which is what Roboflow, CVAT, Label Studio and most other tools export. The
layout it expects:

```
human_aerial/
├── train/  _annotations.coco.json  + images
├── valid/  _annotations.coco.json  + images
└── test/   _annotations.coco.json  + images
```

## Step by step

**1. Create project.** Name it, choose its [type](/docs/concepts/projects) — one or several — and pick
the data: a folder, another project's classes, or the example dataset.

**2. Select folder.** Choose the dataset folder or any one of its set folders; the sets beside it are
found together. Set names can be edited and must be unique. A single `.json` file can be added on its own.

**3. Choose how hard to look at the images.**

| Option | What it does | When |
|---|---|---|
| **All images** | Decodes every image: finds missing, corrupt, resized and byte-identical files | The default. Do this once per dataset |
| **Sample, 200 per set** | Decodes a sample | Very large datasets you have imported before |
| **Annotations only** | Never opens an image | Annotation-only checks, or images on slow storage |

**4. Run preflight** and read the report. Each finding has a severity, the counts per set behind it,
example images with the boxes in question, and a recommended option. Change any you disagree with.

**5. Review.** The last step shows the project type against what was actually found, the images per split,
and a segmented bar for re-cutting them. If the type does not fit — you chose instance segmentation and
there are no masks — Granum says so and offers to go back rather than importing quietly.

**6. Import.** Now it writes.

## Findings and what to do about them

Findings come in three severities. **Blocking** ones must be resolved before importing — a broken
annotation file, boxes referring to images that are not listed, categories whose ids disagree between
sets. **Warnings** are real problems with a sensible default — an "ignore region" category exported as a
normal class, zero-area boxes, images byte-identical across train and valid. **Information** is context
you should see and probably accept — unused categories, images with no boxes, very small boxes.

Every check, with the options it offers, is listed in [Import checks](/docs/reference/preflight).

!!! warning "The leakage checks are the ones to read"
    `media.identical_files`, `images.export_copies`, `split.shared_source` and `split.shared_sequence`
    find the same image, the same export copy or the same capture sequence on both sides of a split. That
    inflates validation scores and no amount of later work will tell you it happened. Granum groups them
    and offers to move or drop them; take it seriously.

## Re-cutting the splits

The review step shows how many images are in each split and a bar with draggable handles between them.
Dragging moves images from one split to its neighbour; the total never changes, because the point is to
re-cut the dataset you have rather than to sample from it.

Images stay where they already are wherever the target allows, so a small adjustment moves few images.
Ones that do move are renumbered so the annotation files stay consistent. If you do not touch the slider,
the source split is kept exactly.

## Adding data later

**Add data** on an existing project (the Images empty state, or Create project with a project chosen)
runs the same flow and adds to what is there: new sets appear beside the existing ones, and data for an
existing set name becomes a new version of that set. The project's type is fixed at this point and shown
read-only.

## What gets recorded

- The preflight report: `<project>/imports/<id>.json`, linked from **Overview → Attention** and from each
  set.
- The option chosen for each finding and how many images or boxes it affected: in the producer record of
  every version the import wrote.
- COCO fields as they were — category ids, annotation ids, `iscrowd`, `area`, segmentation and any extra
  fields — so an unedited export reproduces the file.

## From the command line

```bash
# Report only; exits non-zero when there are blocking findings
granum import coco train=data/train/_annotations.coco.json valid=data/valid/_annotations.coco.json \
    --project aerial --check-only

# Import, overriding one finding's default option
granum import coco train=… valid=… --project aerial --choose categories.ignore_region=drop
```

`--media full|sample|none` chooses how hard to look at the images, `--fail-on block|warn|never` what
makes the command fail, and `--json` prints the report for a CI job to read.

## Where Granum may read from

The service only opens import sources under its configured **data roots** — your home folder by default.
Narrow that with `granum service --data-root /mnt/datasets` (repeatable) or the `service.data-roots`
setting. This is a deliberate limit on a local web service, not an inconvenience:
see [Files and settings](/docs/reference/files).
