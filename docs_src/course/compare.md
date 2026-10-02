---
title: 9. Make a controlled comparison
summary: Change the training schedule from three to twelve epochs on the same frozen data, then inspect compatibility, actual deltas and uncertainty.
---

**Goal:** compare a planned experiment without attributing its result to the wrong cause.
Complete [Read the model evidence](/docs/course/results) first. If you are not training locally, follow
the real recordings and [downloadable evidence](/assets/course/evidence.json).

## What changes, and why

Our first model is weak. A reasonable workflow experiment is to give the same nominal recipe a longer
training schedule. We change **epochs from 3 to 12**, keeping the same frozen baseline and split roles.

This is **not a label-edit experiment**. The review lesson restored its practice label before saving,
and both runs use the original aerial-baseline revisions anyway. It is also not an exact continuation
of the first run: each starts a fresh run from the selected pretrained weights. Framework schedules
and automatic settings may depend on the total epoch budget.

Before a real experiment, write a sentence naming the planned change and how it will be evaluated.
Here: “Compare a 12-epoch schedule with 3 epochs on the same 24 validation images and scoring labels.”

## Step 1: launch the candidate

1. Return to **Datasets → aerial-baseline → Train**.
2. Check **train 96**, **valid 24** and **Test on None** again.
3. Keep YOLO26 nano, 640 px and per-sample recording enabled.
4. Change **Epochs** to **12**.
5. In **Compare with**, choose the completed three-epoch baseline run.
6. Read and accept the exploratory acknowledgement, then **Start training**.
7. Wait for completion and inspect the log. Record the new run's name and recipe.

<figure class="doc-figure">
<a href="/assets/course/25-candidate-recipe.webp"><img src="/assets/course/25-candidate-recipe.webp" alt="Actual candidate training dialog keeps aerial-baseline and the same model settings while selecting twelve epochs and the earlier run for comparison." width="1440" height="960" loading="lazy"></a>
<figcaption>The planned change is schedule length. The earlier model is rescored on the candidate's evaluation labels for the training comparison.</figcaption>
</figure>

<figure class="doc-figure doc-video">
<video controls preload="none" playsinline poster="/assets/course/25-candidate-recipe.webp" aria-label="Recorded twelve-epoch candidate setup and submission" aria-describedby="candidate-video-caption">
<source src="/assets/course/07-experiment.mp4" type="video/mp4"><track kind="captions" src="/assets/course/07-experiment.vtt" srclang="en" label="English" default>
<a href="/assets/course/07-experiment.mp4">Download the recording</a>.
</video><figcaption id="candidate-video-caption">15 seconds · silent, with captions · submission, not the full training duration.</figcaption>
</figure>
<details class="doc-transcript"><summary>Read the experiment video transcript</summary>
<ol><li>Change the planned variable: 12 epochs rather than 3, on the same frozen dataset.</li><li>This is a schedule experiment, not evidence that label edits helped.</li><li>The earlier model is rescored on the same validation labels; different labels would confound the result.</li></ol>
</details>

## Step 2: check comparability before the delta

Open **Runs → Compare runs**. Select the three-epoch run as **Baseline** and the twelve-epoch run as
**Candidate**. Select **valid** when the Set selector offers multiple splits.

Read the verdict and expand the passed checks. The recorded report has:

- Matching evaluation set and exact evaluation version.
- Matching evaluator and class mapping.
- A **training recipe warning**: epochs intentionally changed.
- A **seeds warning**: one run per setting, one seed, no estimate of run-to-run variation.

<figure class="doc-figure">
<a href="/assets/course/26-comparison-checks.webp"><img src="/assets/course/26-comparison-checks.webp" alt="Actual comparison shows shared evaluation compatibility and warns that the recipe changed and only one seed was used." width="1440" height="960" loading="lazy"></a>
<figcaption>“Controlled comparison” describes compatible measured inputs. It is not a statistical significance certificate.</figcaption>
</figure>

If a report says **Not comparable**, resolve its input/version/policy mismatch. Do not copy the two
headline numbers into a spreadsheet and bypass the refusal.

## Step 3: read the actual result

The recorded candidate is **run-1002-170617**. The result was modest numerically and poor operationally:

| Measurement | 3 epochs | 12 epochs | Interpretation |
|---|---:|---:|---|
| Last framework-history mAP50 | 0.00345 | 0.01308 | Same framework metric, but not the final Granum score |
| Final Granum mAP50 | 0.000 | 0.001 | Delta 0.001; report says **too close to call** |
| Validation F1 from stored predictions at confidence 0.25 | 0.000 | 0.000 | No useful operating-point gain demonstrated |
| Counted validation labels | 1,710 | 1,710 | Same support |
| Found / false / missed at that operating point | 0 / 0 / 1,710 | 0 / 0 / 1,710 | Every counted label still missed |

The comparison's tolerance was **0.02**. That is a reporting policy, **not a confidence interval or
hypothesis test**. A delta inside it does not prove equivalence; a delta outside it would not by itself
prove a statistically reliable or practically useful gain.

## Step 4: inspect image-level outcomes

Read **Improved**, **Regressed**, **Unchanged**, **Only in baseline** and **Only in candidate**. In this
recording: **0 improved, 0 regressed, 24 unchanged, 0 baseline-only, 0 candidate-only** at the reported
operating point. Inspect the pooled support and underlying images, not only the top-line delta.

<figure class="doc-figure">
<a href="/assets/course/27-comparison-outcomes.webp"><img src="/assets/course/27-comparison-outcomes.webp" alt="Actual comparison pools the same 24 validation images, showing no operating-point improvement and unchanged image outcomes." width="1440" height="960" loading="lazy"></a>
<figcaption>Different final AP and unchanged operating-point counts can coexist: they summarise different aspects of the predictions.</figcaption>
</figure>

Use **Download report** to preserve your actual comparison. The course's
[evidence record](/assets/course/evidence.json) keeps both histories, evaluator settings, compatibility
checks and observed counts. It is not a downloadable trained model or a production recommendation.

## Watch the comparison

<figure class="doc-figure doc-video">
<video controls preload="none" playsinline poster="/assets/course/26-comparison-checks.webp" aria-label="Recorded compatibility checks and actual image-level comparison" aria-describedby="compare-video-caption">
<source src="/assets/course/08-compare.mp4" type="video/mp4"><track kind="captions" src="/assets/course/08-compare.vtt" srclang="en" label="English" default>
<a href="/assets/course/08-compare.mp4">Download the recording</a>.
</video><figcaption id="compare-video-caption">20 seconds · silent, with captions · genuine weak-model comparison.</figcaption>
</figure>
<details class="doc-transcript"><summary>Read the comparison video transcript</summary>
<ol><li>Check the same validation images, labels, class mapping and scoring policy first.</li><li>Read improved, regressed and unchanged images, not just an average.</li><li>More epochs is the planned change; no label-improvement claim follows.</li><li>The evidence download preserves actual poor numbers. Data approval is separate from model acceptance.</li></ol>
</details>

## What we learn

The longer schedule did not demonstrate a useful detector at the chosen operating point. A sensible
next investigation could inspect resize effects, training adequacy, class policy or a better-suited
recipe—but change and record those deliberately. Collect independent, representative evaluation data
and repeated runs before making deployment claims.

## Checkpoint

Write a decision such as: “Do not deploy either model. The 12-epoch experiment changed the schedule,
not the labels; final mAP50 rose by 0.001, within the reporting tolerance, while validation F1 stayed
zero. Evidence is one small split and one seed.” Next: [approve and export only inspected data](/docs/course/handoff).

## If something differs

| Symptom | What to do |
|---|---|
| Candidate not listed | Check it finished and belongs to the same project; inspect failures first |
| Evaluation version mismatch | Use the intended frozen labels or explicitly rescore; do not relabel the comparison as controlled |
| Unexpected recipe differences | Read recorded parameters, framework versions and defaults, not just the two dialog screenshots |
| Large gain on a tiny slice | Inspect support and repeated-run variation before claiming improvement |