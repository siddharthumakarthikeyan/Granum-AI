---
title: Runs and metrics
summary: What a training run records, what a round is, and why Granum scores every model the same way.
---

A **run** is one training job. It records three things.

## The recipe

Model family and weights, image size, batch size, epochs, seed, and the exact URL of every set it used —
train, validation and, if you chose one, test. Two runs can only be compared when this matches in the
ways that matter, so it is recorded rather than remembered.

## Scores per round

At the end of each round (an epoch) Granum logs the trainer's own metrics: mAP50, mAP50-95, precision,
recall, and the loss terms. These drive the chart on the Runs screen and the progress card while
training.

## Per-image results

This is the part that makes Granum more than a training launcher. At the end of the rounds it collects on,
Granum runs the model over each set and stores, per image: how many labels it found, how many it missed,
how many boxes it predicted with nothing to match, the per-image precision, recall and F1 — and, for the
rounds that keep boxes, every predicted box with its confidence and which label it matched.

With **Record per-sample metrics and predictions every epoch** on, that happens every round for every
set, which is what makes [per-image learning](/docs/guides/learning) and [Findings](/docs/guides/findings)
possible. Without it, boxes are kept for the middle and final rounds only.

The cost is disk, and it scales with how many boxes your images hold. On a dense aerial set — 11,335
training and 547 validation images, 55 boxes an image — a round with boxes stored is about 15 MB, so a
12-round run tracking every round is roughly 180 MB. On ordinary datasets with a handful of objects per
image it is a small fraction of that.

## One scorer, so runs compare

YOLO, RT-DETR and RF-DETR each report validation numbers computed with their own confidence thresholds,
matching rules and averaging. Those numbers do not compare with each other — a fact that has cost many
teams a wrong conclusion.

So after training, Granum scores the finished model itself, with its own matching rules, at a fixed
operating point, on the current labels of the validation set. That figure — recorded as the run's final
score, and the one the comparison uses — is computed identically for every model family and every run:

- **mAP50**: mean over classes of average precision at IoU 0.5, COCO-style 101-point interpolation.
- **Precision, recall and F1**: over all boxes at confidence 0.25 and above.
- Boxes marked as crowd or ignore regions are excluded from matching and never counted as missed.

Because predictions below a floor confidence are dropped, this mAP can read slightly lower than a
framework's own figure. It is consistent, which is what a comparison needs.

## Rounds, epochs and "observations"

Granum says *round* in the interface where the literature says *epoch*; they are the same thing. A round
the model was *observed* in is one where per-image metrics were collected. A run can have 60 epochs but
only 12 observations if collection was every fifth round — which is why dynamics and findings talk about
observations rather than epochs, and why an image seen in too few of them gets no verdict at all.

## A held-out test set

The train dialog has an optional **Test on** set. It is scored once, on the finished weights, and never
used for anything else: no early stopping, no model selection, no threshold tuning. If you choose sets by
validation score and then report validation score, you are reporting a number you tuned against; the test
column exists so you have one you did not.
