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

Project records live in plain files under this folder. Referenced images and model resources can live
elsewhere, so copying only this directory is not necessarily a portable backup. Use
[backup and restore](/docs/course/backup) to include supported referenced resources.

## Project types

When you create a project you say what its labels are for. You can choose several:

| Type | What it means | Editor tools |
|---|---|---|
| **Object detection** | Boxes around objects | Box |
| **Oriented object detection** | Rotated rectangles around objects | Oriented box |
| **Instance segmentation** | A mask per object | Polygon, Paint, Erase |
| **Semantic segmentation** | A class per pixel, no instances | Polygon, Paint, Erase |
| **Panoptic segmentation** | Things and stuff together | Mask editing; complete training workflow not yet included |
| **Keypoint detection** | Points on each object | Keypoint, Box |
| **Classification** | One label for the whole image | Image label only |

The type is recorded with every table that is imported, shown in the Images subtitle and on dataset
versions, and used in three places: the editor offers the tools that fit, the import review warns when
the annotations do not match the type you chose (masks declared but none present, for example), and the
train dialog warns when you ask to train boxes on a project whose labels are not boxes.

!!! note "Match the task across the workflow"
    Import, annotation tools, model variants and scoring must agree on the task. Granum has task-aware
    mask, pose and oriented-box paths, plus newly implemented classification and semantic trainers.
    Some specialised views and broader qualification remain incomplete. Check
    [training tasks](/docs/measure/tasks) and [feature availability](/docs/reference/features).

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
