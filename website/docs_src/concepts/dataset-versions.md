---
title: Dataset versions
summary: The frozen, named datasets that training uses — why they exist and what goes into one.
---

A **dataset version** is a named, frozen choice of one version of each set: "v2 — after the first review
pass", made of `train` v3, `valid` v2 and `test` v1. You create one from the Images header with
**Create dataset**; they are listed on the Datasets screen.

Training offers dataset versions and nothing else.

## Why the app insists on this

Without a line between working data and agreed data, three things happen, and they happen to everyone:

1. **Results stop being reproducible.** A run says it trained on "the training set". Which one? The set
   changed four times that week.
2. **Comparisons quietly stop meaning anything.** Two runs trained a fortnight apart were trained on
   different data, so the difference between them measures nothing in particular.
3. **Nobody can answer for the data.** "Was this reviewed before we trained on it?" has no answer you can
   check.

A dataset version answers all three by being immutable and named. It records who made it, when, from
which version of each set, with how many images in each, and how many of those were verified.

## What a version contains

| Mode | What is stored | When to use it |
|---|---|---|
| **Use entire dataset** | A reference to the current version of each set | The normal case: you want everything, verified or not |
| **Use only verified** | Frozen copies of each set holding only its verified images | A clean training set while review is still in progress |
| **With augmentation** | The above, plus generated copies of the train set written as new images | When you want the augmented images to be a fixed, inspectable part of the dataset |

Isolated images are never included. Removed images are never included.

Version numbers count every version you have ever made, including deleted ones, so a number is never
reused: if v4 is deleted, the next one is v5.

## Augmentation belongs here

Granum augments by generating images into the dataset version rather than by transforming batches during
training. It is slower and uses disk, and it buys two things worth more than that: you can *look* at
exactly what the model will see, and a run's inputs are a fixed set of files rather than a recipe plus a
seed. Only the train set is augmented. → [Augmentation](/docs/guides/augmentation)

## Deleting one

The trash button on the Datasets screen shows what a version costs on disk and which runs used it before
it goes. Deleting removes its frozen files; the runs that used it keep their scores and their record of
which version they used. A version cannot be deleted while a training job is using it.

!!! note "Unverified images are allowed"
    Granum does not force a fully reviewed dataset before you can train. Most useful first runs happen on
    data nobody has reviewed — that first run is often what tells you *where* to review. The dialog says
    how many images are unverified, the version records the count, and the Datasets screen shows it, so
    nobody is misled about what went in.
