---
title: Compare two runs
summary: Improved, regressed, unchanged and unmatched images — and what the comparison is worth.
---

**Compare runs** puts a baseline and a candidate side by side on the evaluation set they share. Reach it
from the Runs header, or from a run's **Compare** button, which compares it with the run before it.

The page answers three questions in order, and the order is the point.

## 1. May these two be compared at all?

Before any number is shown, Granum checks the pair and **refuses** rather than averaging when the
comparison would be meaningless:

| Check | Refuses when | Warns when |
|---|---|---|
| Evaluation set | The two were scored on different sets | — |
| Evaluation version | — | The same set, but a different version: the labels changed |
| Scoring rules | The runs used different matching or operating points | One did not record its policy |
| Classes | The class lists have nothing in common | They differ but overlap |
| Training recipe | — | Model, size, rounds or batch differ |
| Seeds | — | One seed each: small differences cannot be separated from noise |

Warnings are listed above the numbers, with the passed checks collapsed behind a count.

## 2. What may be read into it?

The verdict card names the comparison:

- **Controlled** — only the thing under test changed.
- **Observational** — the data changed too. "The comparison shows what happened alongside that change,
  not what any single edit caused."

And the headline score, with a **declared tolerance**: a difference smaller than it is reported as *too
close to call*, because with one seed per run nobody has measured the run-to-run spread. This is a
declared threshold, not a measured noise level, and the page says so.

## 3. What actually moved?

Five tiles count every image of the shared set: **improved**, **regressed**, **unchanged**, **only in
baseline**, **only in candidate**. Click one to filter the table below it.

- Images are paired by **image reference**, never by row, so a version that removed images cannot
  misalign the comparison.
- *Unchanged* means the same true positives, misses and false positives — not merely a similar score. An
  image that traded a miss for a false positive did not stay the same.
- The unmatched tiles are listed, not dropped. When you removed 200 images between runs, that is the
  most important fact on the page.

Below the table: **pooled scores** on the images both runs scored, with their support; **slices** by
class and by object size, each marked *too few to call* under 30 labels; **what changed in the data** —
images added, removed or edited, boxes drawn, deleted, relabelled or moved; and **what it cost** — rounds,
training time, and the review decisions recorded between the two runs, with observed counts separate from
the estimate.

## Download report

**Download report** saves the whole comparison as JSON: the versions of everything, every check and its
result, every image with its before and after counts, the slices, the data change and the costs.

It is meant for the places a screenshot will not do — a pilot write-up, a regression record attached to a
release, or a colleague who wants to check your arithmetic.

!!! tip "Getting a comparison worth reading"
    Change one thing at a time. If you fix labels *and* switch from nano to medium *and* add 5,000
    images, the page will tell you honestly that it cannot attribute anything — which is correct, and
    not what you wanted to learn. Keep the evaluation set fixed across the comparison, and the honest
    version of the question stays answerable.
