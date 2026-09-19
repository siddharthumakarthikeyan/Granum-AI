---
title: Your first project
summary: Create a project from a folder of COCO annotations, or from the built-in example dataset, and see what arrived.
---

A **project** is one body of work: a dataset, its versions, the reviews and comments on it, and every
training run made from it. Most teams keep one project per problem — "aerial people", "shelf audit" —
rather than one per experiment.

## Option A: the example dataset

If you want to see the whole product before committing your own data, use the generated example. It is
120 small images of coloured shapes, drawn on your machine, with deliberate label problems planted in
them: boxes missing from shapes that are drawn, boxes carrying the wrong class, boxes far too large, one
box with no width, and two training images copied into the validation set.

Click **Create project → Use the example dataset**, or the *Try the example project* tile on the
Projects screen. Example projects do not count towards your plan's project limit.

Because you know what is wrong with it, the example is the honest way to judge whether the import
checks, the review tools and Findings actually earn their place.

## Option B: your own data

Granum imports COCO detection annotations — one annotation file per set, images beside it, which is what
Roboflow and most labelling tools export:

```
human_aerial/
├── train/  _annotations.coco.json  + images
├── valid/  _annotations.coco.json  + images
└── test/   _annotations.coco.json  + images
```

1. Click **Create project** in the sidebar.
2. Give the project a name and choose what its labels are for — object detection, instance segmentation,
   keypoints, classification, and so on. You can pick more than one; the choice is recorded with every
   table imported and decides which tools the editor offers later.
3. **Select folder**, and choose the dataset folder *or any one of its set folders*. The sets beside it
   are found together.
4. Choose how thoroughly to check the images, then run the preflight.
5. Read the findings, adjust any option you disagree with, and import.

Nothing is written until the last step. Every check, what you chose and how many images it affected is
kept with the import, so how a dataset came to be is always inspectable. The full list is in
[Import data](/docs/guides/import).

## What you get

After the import, the sidebar has five places:

| Screen | What it holds |
|---|---|
| **Overview** | The project at a glance: mosaic, headline counts, what needs attention |
| **Images** | Every image with its annotations — and the browse, review and edit modes |
| **Datasets** | The dataset versions you have created; training uses these only |
| **Runs** | Training runs, their charts and scores, and the comparison between two of them |
| **Findings** | Labels a finished run suggests are worth checking |

All the sets land in one dataset, named after the folder that held them, with `train`, `valid` and `test`
as splits inside it. Every image starts **unverified**.

Next, see what that data actually looks like: [Run the loop once](/docs/start/the-loop).
