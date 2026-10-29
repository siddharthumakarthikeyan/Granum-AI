---
title: Runs and metrics
summary: What a run records, how sample observations connect to inputs, and when experiment scores can be compared.
---

A **run** records an experiment, training job or analysis process. A training run brings together the
recipe, aggregate measurements and sample observations.

## The recipe

Model family and weights, image size, batch size, epochs, seed, and the exact URL of every set it used —
train, validation and, if you chose one, test. Two runs can only be compared when this matches in the
ways that matter, so it is recorded rather than remembered.

## Scores per round

At the end of each round (an epoch), Granum logs the applicable task's measurements. Detection runs can
record average precision, precision, recall and losses; classification uses accuracy and loss, while
semantic segmentation includes pixel accuracy and mean class IoU. These drive task-appropriate charts.

## Per-image results

For detection, at the end of the rounds it collects on, Granum stores per image how many labels it found, how many it missed,
how many boxes it predicted with nothing to match, the per-image precision, recall and F1 — and, for the
rounds that keep boxes, every predicted box with its confidence and which label it matched.

With **Record per-sample metrics and predictions every epoch** on, supported training paths collect
repeated training/validation observations for [learning](/docs/guides/learning) and
[Findings](/docs/guides/findings). A held-out test set stays separate from routine collection.
Collection frequency and retained outputs depend on the integration and task; inspect the run's
recorded tables rather than assuming all epochs contain predictions.

The cost is disk, and it scales with how many boxes your images hold. On a dense aerial set — 11,335
training and 547 validation images, 55 boxes an image — a round with boxes stored is about 15 MB, so a
12-round run tracking every round is roughly 180 MB. On ordinary datasets with a handful of objects per
image it is a small fraction of that.

## Comparable scoring within a task

YOLO, RT-DETR and RF-DETR each report validation numbers computed with their own confidence thresholds,
matching rules and averaging. Those numbers do not compare with each other — a fact that has cost many
teams a wrong conclusion.

So after training, Granum scores the finished model itself, with its own matching rules, at a fixed
operating point, on the current labels of the validation set. That figure — recorded as the run's final
score — follows the common detection policy for compatible detector runs:

- **mAP50**: mean over classes of average precision at IoU 0.5, COCO-style 101-point interpolation.
- **Precision, recall and F1**: over all boxes at confidence 0.25 and above.
- Boxes marked as crowd or ignore regions are excluded from matching and never counted as missed.

Because predictions below a floor confidence are dropped, this mAP can read slightly lower than a
framework's own figure. It is consistent, which is what a comparison needs.

Mask, pose and oriented-box tasks use their own similarity measures. Classification accuracy and
semantic IoU are different quantities from detection mAP. Compare only compatible tasks, datasets,
class maps and scoring settings; see [comparison checks](/docs/guides/compare).

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
