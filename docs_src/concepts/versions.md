---
title: Versions and lineage
summary: Why every change writes a new version, what that costs, and how to read the history.
---

Granum never edits a set in place. Every change — a corrected box, ten images removed, an isolated image
returned — writes a **new version** of that set and leaves its parent untouched.

## What creates a version

| Action | Writes |
|---|---|
| Saving an image in the editor or the review inspector | one version of that set, however many boxes you changed |
| Verifying, unverifying, commenting | nothing: decisions are kept beside the data, not in it |
| Isolate, delete, return to set | one version of each set involved |
| Adding a class | one version (the class list is part of the set's schema) |
| Creating a dataset version | a record; with "only verified" or augmentation, frozen copies |
| Importing more data | new sets or new versions of existing ones |

Note the second row. Review status is *about* an image, not *part of* it, so verifying thousands of
images does not multiply your data. Editing does, which is why an editing session saves once per image
rather than once per box.

## Reading the history

Each version records its parent, the operation that made it, and the arguments of that operation — "1 box
added, 1 removed on image 4172", "removed 12 images: unusable", "imported from
`/data/aerial/train/_annotations.coco.json` with `categories.ignore_region = drop`". The Datasets screen
shows each dataset version's sets and where they came from; the workspace shows a table's lineage back to
the import.

That chain is the answer to the question that otherwise ends an investigation: *what exactly was this
model trained on, and who changed it?*

## What it costs

A version is the set's rows plus its schema. Granum stores rows in Parquet and writes a complete copy per
version. On a real aerial dataset — 11,335 images with 621,000 boxes — one version is about 9 MB, so ten
versions of it cost under 100 MB. Images are never copied: a version points at the same files on disk.

Two exceptions copy images deliberately, because a frozen dataset must not change if you later move or
edit the originals:

- a dataset version created with **only verified** images writes frozen copies of the chosen sets;
- **augmented** dataset versions write the generated images as new JPEGs.

If disk is tight, the lever is dataset versions and augmentation, not ordinary editing.

## Sets you did not make

Two sets appear when you need them, and behave like any other set:

- **isolated** — images set aside during review. They stay out of new dataset versions until returned.
- **removed** — images deleted from a set. They keep where they came from and why, and can be put back.

Both are reachable from the Images tab; removed images through the **Removed** button in the header.
→ [Isolate, remove and restore](/docs/guides/isolate-remove)

!!! note "Deleting is not destroying"
    Deleting an image takes it out of the *current* version of its set. Every earlier version still
    contains it, and the file on disk is never touched. There is no operation in Granum that destroys
    an image, which is why *delete* is offered with so little ceremony.
