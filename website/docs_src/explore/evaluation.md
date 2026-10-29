---
title: Inspect model errors
summary: Read confusion, per-class results, operating thresholds and the individual objects behind each metric.
status: partial
---

Open Evaluation for a run with stored predictions. Start with the evaluation dataset version and
epoch, then inspect errors by class and object. An aggregate score alone does not identify the labels
or failure modes worth working on.

## Read the confusion view

The detection confusion matrix pairs overlapping labels and predictions without first requiring the
same class. This makes a class mix-up visible in one cell. Select a cell to inspect the objects
behind it, comparing the stored label with the predicted geometry.

Class-aware scoring treats that same wrong-class prediction as a false positive and the unmatched
label as a false negative. These are two useful interpretations of the same observation; do not
expect their object counts to be identical to a class-agnostic confusion cell.

## Inspect class performance

Read precision, recall, F1, support and available average-precision measurements per class. A class
with very few labelled examples needs a different interpretation from a well-represented class.
Inspect its images before using a small difference to choose a model.

The threshold view shows how precision and recall change with confidence. Choose an operating point
based on the task's costs and a held-out evaluation; a suggested best F1 threshold is not universally
the best deployment threshold.

## Review the objects

Use the found, invented and missed filters to inspect crops. A supposed false positive may expose a
missing source label; a supposed miss may reveal an ambiguous or very small object. Open the source
image to check the context and record a [review decision](/docs/guides/review).

Changes to labels belong in a new revision. Keep the previous run's evaluation context and perform
a new evaluation when you need scores against the corrected labels. Use
[Compare runs](/docs/guides/compare) to check compatibility before drawing a before/after conclusion.

## Task boundaries

Granum has task-specific overlap and keypoint metrics, and a Python semantic-mask collector. The
specialised detection views do not make every task-specific evaluation dashboard available.
New classification and semantic training paths are described in [training tasks](/docs/measure/tasks).
Inspect their recorded metrics in the run workspace; a complete set of specialised evaluation screens
for every task is **Not yet included**.
