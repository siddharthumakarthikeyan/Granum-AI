---
title: Projects and project types
summary: What a project holds, how its type changes the tools, and how to organise several.
---

## What a project holds

```
~/granum/projects/aerial-people/
├── datasets/human_aerial/tables/…   every version of every set
├── releases/human_aerial/…          frozen dataset versions
├── reviews/human_aerial.qa.jsonl    statuses and comments, append-only
├── reviews/human_aerial.jsonl       findings and review decisions, append-only
├── runs/run-…/                      each run: parameters, scores, per-image metrics
└── imports/…json                    every import's preflight report and choices
```

Everything about a project is inside its folder, in plain files. Copying the folder copies the work;
deleting it deletes the work. Nothing is in a database you cannot read.

## Project types

When you create a project you say what its labels are for. You can choose several:

| Type | What it means | Editor tools |
|---|---|---|
| **Object detection** | Boxes around objects | Box |
| **Instance segmentation** | A mask per object | Polygon (and Box) |
| **Semantic segmentation** | A class per pixel, no instances | Polygon |
| **Panoptic segmentation** | Things and stuff together | Polygon |
| **Keypoint detection** | Points on each object | Keypoint, Box |
| **Classification** | One label for the whole image | Image label only |

The type is recorded with every table that is imported, shown in the Images subtitle and on dataset
versions, and used in three places: the editor offers the tools that fit, the import review warns when
the annotations do not match the type you chose (masks declared but none present, for example), and the
train dialog warns when you ask to train boxes on a project whose labels are not boxes.

!!! note "What the importer currently reads"
    The COCO importer reads boxes. Masks, keypoints and other COCO fields ride along as properties on
    each object and are preserved on export, and the editor can draw and change them, but the checks,
    metrics and training in Granum today are box-based. Choosing a segmentation or keypoint type sets up
    the right tools; it does not yet give you a segmentation evaluator.

## Several projects

The Projects screen lists every project on the machine as a card: a mosaic of its images, its type, its
sets, counts of images, objects, classes and dataset versions, how much of it is verified, and the
status of its last run. Search, sort by recent, name or size, and switch between cards and a list — the
choice is remembered.

How to split work into projects:

- **One project per problem**, not per experiment. Experiments are runs; runs already live inside a
  project and compare there.
- **One project per customer or site** when the label conventions differ. Two shelf-audit contracts with
  different class lists are two projects; the same contract's four stores are one.
- **A project per model generation is a mistake.** You lose the review history, which is the expensive
  part.

Projects can be renamed (the pencil on the card, or next to the title on Overview) and deleted (a typed
confirmation; it also removes that project's training runs and exports). A project cannot be renamed or
deleted while it is training.

## Pulling data between projects

New projects do not have to start from a folder. **Create project → Import from existing projects** lets
you pick classes out of projects you already have — every "person" from three projects, or everything
from one — and builds a new project from those images. → [Build from existing projects](/docs/guides/pull-from-projects)
