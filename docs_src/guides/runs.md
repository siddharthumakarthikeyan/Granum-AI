---
title: Read a run
summary: Scores per round, the framework-neutral final score, and where each number comes from.
---

The **Runs** screen lists every run in the project with its model, the data versions it used, its rounds
and its scores, best value marked. Click a row to open the run itself; the buttons on the right lead to
its per-image views.

## The chart

Rounds along the bottom, one line per run, metric chosen at the top left. Two shapes are worth
recognising:

- **A curve still climbing at the last round** means the schedule was too short. Train longer before
  concluding anything about the data.
- **Validation flattening while training loss keeps falling** is the usual overfitting picture. On small
  datasets it often means the model has memorised the training labels — including the wrong ones, which
  is exactly when findings on the *training* split go quiet and held-out evidence matters.

## The columns

| Column | What it is |
|---|---|
| **Status** | Running (with the round it is on), finished, cancelled or failed |
| **Model** | Family, weights and image size |
| **Train / validation / test data** | The exact set versions, so two rows can be compared honestly |
| **Epochs** | Rounds logged |
| **mAP50**, **mAP50-95**, **Precision**, **Recall** | The trainer's own metrics for the last round |
| **Test mAP50** | The held-out score, when the run had a test set |

The trainer's metrics are useful for watching progress, but they are computed differently by each
framework. The number to compare across runs is the **final score** Granum computes itself, shown on the
run and used by the comparison. → [Runs and metrics](/docs/concepts/runs)

## From a run to the images

- **Samples** opens per-image learning: which images were learned early, late, unstably or never.
- **Findings** ranks individual labels worth checking.
- **Compare** puts this run beside the one before it.

Opening a run itself gives the joined view: every per-image metric beside the sample it was measured on,
filterable and sortable, with the images shown against their current labels where that join is safe.

!!! note "A run that produced nothing"
    A run cancelled before its first round finished has no metrics and no predictions, so the evidence
    screens have nothing to show and say so rather than displaying an empty chart. It still appears in
    the list, with its status, because it happened.
