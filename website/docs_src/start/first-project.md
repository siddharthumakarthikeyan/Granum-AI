---
title: Your first project
summary: Choose the guided real-data course, the generated shapes example or your own data, and understand what the import creates.
---

A **project** is one body of work: a dataset, its versions, the reviews and comments on it, and every
training run made from it. Most teams keep one project per problem — "aerial people", "shelf audit" —
rather than one per experiment.

## Recommended: the real-data course

Follow [the guided aerial course](/docs/course/start) for your first complete project. It includes a
verified download of 120 real images (96 train, 24 valid), explains source taxonomy and holdout problems,
and walks through actual import, review, recovery, training, comparison, approval, export and restore.
Each stage has screenshots, a checkpoint and troubleshooting; the main application flows have captioned
recordings and transcripts. The observed models are weak, and the course explains that honestly.

The course's sample is **not** the built-in generated example below. Its source labels were not
deliberately corrupted to make a demonstration work. It approves only two genuinely inspected images,
not the full sample.

## Alternative: the generated example dataset

If you want to see the whole product before committing your own data, use the generated example. It is
120 small images of coloured shapes, drawn on your machine, with deliberate label problems planted in
them: boxes missing from shapes that are drawn, boxes carrying the wrong class, boxes far too large, one
box with no width, and two training images copied into the validation set.

Choose the example-dataset action on project creation where your build offers it. This synthetic
fixture is useful for learning known defects, not for measuring real-world model performance. The
current unrestricted alpha does not enforce a paid-plan project limit.

Knowing how the fixture was generated helps explain some expected findings. It does not replace
testing your own data and environment.

## Bring your own data

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

After import, the project connects these main screens:

| Screen | What it holds |
|---|---|
| **Overview** | The project at a glance: mosaic, headline counts, what needs attention |
| **Images** | Every image with its annotations — and the browse, review and edit modes |
| **Health** | Available measurements of data risks and evidence coverage |
| **Datasets** | Frozen exploratory versions and separately approved releases |
| **Runs** | Training runs, their charts and scores, and the comparison between two of them |
| **Evaluation** | Class/object outcomes under a selected scoring scope and threshold |
| **Findings** | Labels a finished run suggests are worth checking |

The selected sets land in one dataset, normally named after the parent folder. Keep only genuine split
roles; do not copy validation into a new test folder. Imported images start unverified; creating a
dataset version does not automatically approve them.

Next: [import the course sample](/docs/course/import), or use [the workflow overview](/docs/start/the-loop)
as a map for your own project.
