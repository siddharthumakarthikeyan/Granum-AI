---
title: Create a dataset version
summary: Freeze what you agreed on into the named dataset that training uses.
---

**Create dataset** in the Images header turns the sets you have been working on into a named, frozen
dataset version. Training offers these and nothing else.

## The dialog

**Name and description.** Give it something a colleague could act on: *"v2 — crossing pedestrians added,
ignore regions fixed"*. Names must be unique within the dataset.

**The set table** shows each set with its images, how many are verified and how many are not. This is the
honest summary of what you are about to freeze.

**If anything is unverified**, Granum says how many and asks which you want:

| Choice | What is stored | Use it when |
|---|---|---|
| **Use entire dataset** | A reference to the current version of each set | You want everything; the unverified count is recorded and shown |
| **Use only verified** | Frozen copies of each set holding only its verified images | You want a clean training set while review continues |

Only-verified mode writes new, frozen sets rather than filtering at training time, so the version is a
fixed list of images that cannot change afterwards.

**Augmentation** is offered next: No, or Yes with a recipe and a number of copies. → [Augmentation](/docs/guides/augmentation)

Creating a plain version is instant. With augmentation it runs as a job — the images have to be generated
— and you can watch or leave it.

## What is recorded

Per set: the exact version, the image count and the verified count. Overall: the name, the description,
who made it, when, the mode, and the augmentation recipe if any. Version numbers count every version ever
made, so a deleted number is never reused.

Isolated images are never included. Removed images are never included.

## On the Datasets screen

Each version is a panel with its sets, an image strip, the split facts, and a **Train** button that opens
the train dialog with that version already chosen. The sidebar badge counts them.

## Deleting a version

The trash button shows what the version costs on disk and which runs used it, then removes its frozen
files. Runs that used it keep their scores and their record of which version they used — they simply no
longer have the images to hand. A version in use by a running training job cannot be deleted.

!!! tip "Name versions after what changed, not when"
    "v3" tells a colleague nothing in six weeks. "v3 — removed night frames, fixed ignore regions" is a
    sentence they can act on, and it is what the comparison report will print beside the numbers.
