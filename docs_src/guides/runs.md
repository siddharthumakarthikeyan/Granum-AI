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

- **A curve still climbing at the last round** suggests investigating schedule length, convergence
  and noise. It does not guarantee that more epochs will produce a useful detector.
- **Validation flattening while training loss keeps falling** can indicate overfitting, but also inspect
  support, split differences and measurement noise. It does not prove that particular labels are wrong.
  Held-out evidence matters, especially when training-set findings become quiet.

## The columns

| Column | What it is |
|---|---|
| **Status** | Running (with the round it is on), finished, cancelled or failed |
| **Model** | Family, weights and image size |
| **Train / validation / test data** | The exact set versions, so two rows can be compared honestly |
| **Epochs** | Rounds logged |
| **mAP50**, **mAP50-95**, **Precision**, **Recall** | The trainer's own metrics for the last round |
| **Test mAP50** | The held-out score, when the run had a test set |

The trainer's metrics are useful for watching progress, but can differ from Granum's final checkpoint
scoring and Evaluation of stored per-epoch predictions. Compare the same evaluator, label version,
checkpoint definition, split and prediction/threshold policy. The dedicated comparison checks these
boundaries; a metric name alone is not enough. The [course results](/docs/course/results) show an actual
case where framework-history and final Granum mAP differ. → [Runs and metrics](/docs/concepts/runs)

## From a run to the images

- **Samples** opens per-image learning: which images were learned early, late, unstably or never.
- **Findings** ranks individual labels worth checking.
- **Compare** puts this run beside the one before it.

Opening a run gives the joined view: per-image metrics beside their recorded versioned input samples.
Later working-label edits do not rewrite the historical measurement. Inspect the input version before
interpreting a disagreement.

!!! note "A run that produced nothing"
    A run cancelled before its first round finished has no metrics and no predictions, so the evidence
    screens have nothing to show and say so rather than displaying an empty chart. It still appears in
    the list, with its status, because it happened.
