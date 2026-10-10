---
title: 8. Read the model evidence
summary: Interpret runs, sample dynamics, evaluation objects and findings using the actual weak baseline, including its zero operating-point scores.
---

**Goal:** move from a number to its underlying images and make a defensible interpretation.
Use your [finished baseline](/docs/course/train), or the [recorded run evidence](/assets/course/evidence.json).

## What the numbers mean

Metrics compare **predictions** with **annotations under a specified policy**. They are not direct
measurements of unknowable perfect labels.

| Term | Read it as | Important limit |
|---|---|---|
| True positive / Found | An accepted prediction matched a labelled object under the policy | Depends on class, overlap, confidence and ignore handling |
| False positive / Invented | An accepted prediction was not matched to a counted annotation | It may be a real but unlabelled object; inspect before judging |
| False negative / Missed | A counted labelled object had no accepted matching prediction | The model may be weak; the label is not automatically wrong |
| Precision | Of accepted predictions, how many matched counted labels? | High precision with very few predictions can hide poor coverage |
| Recall | Of counted labels, how many were found? | Depends on annotation completeness and the chosen threshold |
| F1 | A combined precision/recall measure | One scalar hides which kinds of errors occurred |
| AP / mAP | Precision–recall performance over ranked predictions, averaged as defined by the evaluator | Not the same as accuracy or F1 at one confidence threshold |
| mAP50 vs mAP50–95 | Matching at IoU 0.50 vs an average over stricter IoU thresholds | Do not compare them as if they were the same metric |

Ignore regions are excluded from ordinary labelled-object support. This explains why the course's
validation scoring counts **1,710 labels**, not all **1,780 raw annotation objects**.

## Step 1: read the run before the score

Open **Runs** and the baseline. Check its finished state, input versions and recipe. Then inspect the
history. The recording's last framework epoch scalars were:

| Framework history, last epoch of the three-epoch baseline | Recorded value |
|---|---:|
| Precision | 0.00354 |
| Recall | 0.04204 |
| mAP50 | 0.00345 |
| mAP50–95 | 0.00303 |

These values are fractions, not percentages. The stored epoch index is zero-based: `epoch: 2` is the
third observation. Do not infer missing epochs from that index.

<figure class="doc-figure">
<a href="/assets/course/19-finished-baseline.webp"><img src="/assets/course/19-finished-baseline.webp" alt="Actual finished baseline run lists its parameters and poor recorded training metrics." width="1440" height="960" loading="lazy"></a>
<figcaption>A completed run can be a failed modelling hypothesis. Completion and model usefulness are separate.</figcaption>
</figure>

The run workspace joins per-image measurements back to the exact versioned inputs. Select an image
or metric slice and inspect the row behind it. A historical run describes its historical inputs, not
whatever annotation you edited most recently in the working collection.

<figure class="doc-figure">
<a href="/assets/course/20-run-workspace.webp"><img src="/assets/course/20-run-workspace.webp" alt="Run workspace joins recorded per-image metrics with the corresponding input images and versioned rows." width="1440" height="960" loading="lazy"></a>
<figcaption>Identity joins make a score investigable. They do not transfer review approval from one version to another.</figcaption>
</figure>

## Step 2: inspect sample dynamics

Open the run's **Samples** view (the sample-dynamics page). Read the selected split and the number of
observations. Dynamics uses per-image F1 across epochs to describe patterns such as early learning,
late learning, forgetting or not learned under its policy.

<figure class="doc-figure">
<a href="/assets/course/21-sample-dynamics.webp"><img src="/assets/course/21-sample-dynamics.webp" alt="Actual baseline sample-dynamics screen groups images by the recorded per-epoch learning behaviour." width="1440" height="960" loading="lazy"></a>
<figcaption>Three observations are only the minimum for these categories. Not learned is not a removal recommendation.</figcaption>
</figure>

Open an image and step through the available epochs. Ask whether an apparent failure could be due to
small objects, insufficient training, class confusion, thresholding or a genuinely incorrect label.
Do not choose Remove simply because an image is hard. A “never/not learned” summary is a retrospective
policy result, not proof that the image was impossible or always wrong at every moment.

## Step 3: read Evaluation at a known operating point

Open **Evaluation**, select the baseline and **valid**, and read the confidence setting before
interpreting the display. At operating confidence **0.25** and matching IoU **0.5**, the recorded
baseline's stored validation predictions gave:

| Count or metric | Observed result |
|---|---:|
| Validation images | 24 |
| Counted labels | 1,710 |
| Found (TP) | 0 |
| Invented/unmatched accepted predictions (FP) | 0 |
| Missed (FN) | 1,710 |
| Precision, recall and F1 reported by Granum | 0, 0, 0 |

There were no accepted predictions to reward at this operating point. **Zero false positives is not
good performance when every counted label was missed.** Granum reports zero for these empty-prediction
metric cases; do not reinterpret that as perfect precision.

<figure class="doc-figure">
<a href="/assets/course/22-evaluation-matrix.webp"><img src="/assets/course/22-evaluation-matrix.webp" alt="Actual Evaluation matrix for the weak baseline shows missed labelled objects rather than useful detections." width="1440" height="960" loading="lazy"></a>
<figcaption>Read the selected run, split, confidence and support before interpreting any matrix cell.</figcaption>
</figure>

Scroll to **Every object, one tile each**. Inspect a missed object in its image. Solid boxes are
annotations; dashed boxes are predictions. The crop is an entry point into inspection, not sufficient
context for changing the source class.

<figure class="doc-figure">
<a href="/assets/course/23-evaluation-objects.webp"><img src="/assets/course/23-evaluation-objects.webp" alt="Evaluation object tiles expose the actual labelled objects behind the baseline's missed detections." width="1440" height="960" loading="lazy"></a>
<figcaption>A missed object can be correctly labelled. Inspect the evidence before proposing a correction.</figcaption>
</figure>

### Why can two mAP values differ?

The framework's epoch history, Granum's **final checkpoint scoring**, and Evaluation of **stored
per-epoch predictions** are separate measurements. They can differ in selected checkpoint, prediction
floor, matching/ignore semantics and evaluator implementation. The baseline's final Granum `score_map50`
was **0.0**, while the last framework-history mAP50 was **0.00345**.

Compare like with like. Moving a slider cannot recreate low-confidence predictions that were never
recorded. Do not subtract a framework-history number from a final Granum score and call it improvement.
For a fixed-policy comparison, use the dedicated comparison report and its compatibility checks.

## Step 4: interpret Findings—even when empty

Open **Findings** for the run. Read the evidence and competence notes before acting on ranked items.
Findings can require repeated, useful model evidence; this weak three-epoch model is not a reliable
label-quality judge.

<figure class="doc-figure">
<a href="/assets/course/24-findings-evidence.webp"><img src="/assets/course/24-findings-evidence.webp" alt="Actual Findings screen exposes evidence limitations for the weak baseline instead of claiming the labels are clean." width="1440" height="960" loading="lazy"></a>
<figcaption>An empty queue can mean insufficient evidence. It does not mean every annotation is correct.</figcaption>
</figure>

When findings exist, inspect the full image, supporting predictions, repeated observations and the
class policy. Record Keep, Rework or another justified decision with a reason. **Check labels** can
also perform a separate screening pass; check class mapping and coverage first. Single-pass screening
is weaker than consistent repeated evidence and is not part of the recorded baseline's proof.

## Watch the evidence tour

<figure class="doc-figure doc-video">
<video controls preload="none" playsinline poster="/assets/course/22-evaluation-matrix.webp" aria-label="Recorded baseline run, sample dynamics, evaluation and findings tour" aria-describedby="results-video-caption">
<source src="/assets/course/06-results.mp4" type="video/mp4"><track kind="captions" src="/assets/course/06-results.vtt" srclang="en" label="English" default>
<a href="/assets/course/06-results.mp4">Download the recording</a>.
</video><figcaption id="results-video-caption">31 seconds · silent, with captions · actual poor results, not simulated metrics.</figcaption>
</figure>
<details class="doc-transcript"><summary>Read the video transcript</summary>
<ol><li>Read the finished run, recipe and exact inputs; the three-epoch exercise produced poor scores.</li><li>The run workspace joins historical metrics to historical inputs.</li><li>Not learned after three epochs does not mean an image should be deleted.</li><li>Evaluation separates misses, unmatched predictions and class confusion; read split and confidence first.</li><li>Inspect objects: solid boxes are labels, dashed boxes predictions.</li><li>Findings needs useful evidence; a weak run or empty queue does not prove correct labels.</li></ol>
</details>

## What we learn

The pipeline ran and produced inspectable evidence, but this model did not find the counted validation
objects at the chosen operating point. That supports investigating training adequacy and recipe design.
It does **not** support deleting those objects, approving the full sample, or deploying the model.

## Checkpoint

You can explain the 1,780-to-1,710 support difference, why zero false positives is not success here,
and why an empty findings queue is not a clean bill of health. Next: [change one planned variable](/docs/course/compare).

## If something differs

| Symptom | What to check |
|---|---|
| Different counts | Run, split, epoch, confidence, ignore handling and whether predictions were actually stored |
| Dynamics absent | Per-sample logging and number of completed observations; scalar epoch history alone is insufficient |
| Empty Findings | Model competence, class support and required evidence; do not relax thresholds just to populate a demo |
| Historic labels differ from working labels | Open the run's exact input version; later edits do not rewrite historical evidence |