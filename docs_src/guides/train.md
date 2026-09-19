---
title: Train a model
summary: Choose data, model and schedule; watch the run; know what it is doing to your machine.
---

**Runs → Train model** trains a detector on this computer, on a dataset version, and records everything
about it. Training runs as a separate process, so a long job cannot take the app down with it, and the
app can be closed and reopened while it runs.

## The dialog

**Dataset version.** Choose one; then which of its sets to **train on**, which to **validate on**, and
optionally a **test** set. Only dataset versions are offered — if the list is empty, create one from
Images first.

**Model.** Three families, each with sizes:

| Family | Character | Start here when |
|---|---|---|
| **YOLO** | Fast, reliable, the most widely used | Always, for a first run |
| **RT-DETR** | Transformer; often better in crowded scenes | Many overlapping objects, and you have GPU memory |
| **RF-DETR** | Modern transformer on a large pretrained backbone | Few images, and you want the most from them |

Sizes run from nano to extra large. Nano trains in minutes and tells you whether the pipeline works;
medium is where most real runs land. → [Models you can train](/docs/reference/models)

**Image size** decides how much detail survives. The default 640 px is right for most datasets; raise it
when your objects are small in frame — aerial and satellite work usually wants 1024 or more — and expect
memory and time to rise with the square of it. RF-DETR uses its own input size and ignores this.

**Epochs** are full passes over the training set. Ten to fifteen is a reasonable first run on a few
thousand images. Long schedules matter more than people expect for the evidence features: a model that
never becomes competent produces no findings worth reading.

**Record per-sample metrics and predictions every epoch** keeps the per-image record that
[learning](/docs/guides/learning) and [Findings](/docs/guides/findings) are built on. Leave it on. The
cost is disk — on a dense dataset of 12,000 images it is roughly 15 MB per round — and it is what makes
the difference between a score and a list of images to look at.

**Compare with** scores an earlier run's weights on the same labels at the end, giving an immediate
like-for-like number. The fuller picture is [Compare runs](/docs/guides/compare).

## While it runs

The progress card shows the phase — preparing images, loading the model, training round *n* of *m*,
recording per-image results, scoring — with a progress bar within the round so a long round does not look
stuck. The chart and the per-image dynamics update at the end of each round.

You can leave the page, close the window, or restart the service; the run keeps going and is picked up
again. **Cancel** stops it; what it recorded up to that point is kept.

One training job runs at a time per machine. The dialog says so if another is already going.

## What it does to your machine

- **GPU**: it will use all of it. Training a medium model at 640 px needs roughly 8 GB; RT-DETR large
  wants about 8 GB at batch 8. If you run out of memory, drop the size or the image size.
- **Disk**: weights in `~/granum-training`, per-image metrics in the project. Both are listed in
  [Files and settings](/docs/reference/files).
- **First run**: pretrained weights are downloaded once, into `~/granum-training`.

## The final score

When training ends, Granum scores the finished model itself — same matching rules, same operating point,
for every family — on the validation set's current labels, and records that as the run's score. If you
chose a test set, it is scored once here too, and never used for anything else.
→ [Runs and metrics](/docs/concepts/runs)
