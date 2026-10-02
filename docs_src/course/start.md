---
title: Start the guided course
summary: Learn Granum on a real aerial dataset: import, inspect, review, train, compare, approve, export and restore, with recorded examples.
---

You have a folder of images and labels. Which labels should you trust? What did a model actually
learn? Can someone else reproduce the version you handed over? This course answers those questions
one operation at a time, using the same small dataset throughout.

**No previous Granum experience is needed.** The course introduces boxes, splits, precision, recall
and dataset versions before asking you to use them. It does not require you to write Python.

<div class="course-intro">
<p class="course-eyebrow">First-rollout learning path · Granum 0.1.0</p>
<p><strong>120 real images. One complete, inspectable workflow.</strong></p>
<p>96 training images · 24 validation images · 7,500 source annotation objects · no independent test set</p>
<div class="course-actions"><a class="btn primary" href="/docs/course/setup">Begin: prepare your workspace</a><a class="btn" href="/assets/course/aerial-mini.zip" download>Download sample · 26.4 MiB</a></div>
</div>

## What you will have at the end

- A project called **aerial-walkthrough**, with the source's import problems explained and recorded.
- An **exploratory baseline** containing all 120 images, frozen before any review practice.
- A browser-draft recovery exercise, followed by genuine inspection of **two** images.
- If you choose the training route: two runs on the same frozen input, and a comparison you can explain.
- An **approved two-image excerpt**, a portable COCO export, and an independently checked project restore.
- A written decision about what the evidence supports—and what is still unknown.

!!! warning "This is a workflow course, not a model benchmark"
    The recorded models are poor. The sample is small, only one seed was used, and the source's test
    folder duplicates validation. Do not describe the sample as fully reviewed, the models as production
    ready, or the excerpt's approval as approval of the other 118 images.

## Choose a route

| Route | What to do | Hardware |
|---|---|---|
| Complete workflow | Follow all lessons; run both model experiments | Training dependencies and preferably a supported NVIDIA GPU |
| Review and delivery | Follow setup through review, read the recorded results, then approve/export and restore | No GPU required |
| Experienced user | Use the course checkpoints, then open the linked task guides | Depends on your task |

Downloads, training and human review time vary. The clips are short demonstrations, not a promise
that a careful review takes only as long as the recording. Pause at each checkpoint; do not race the video.

## The learning path

| Step | Lesson | The question it answers |
|---|---|---|
| 1 | [Prepare the workspace](/docs/course/setup) | Which build, which folders, and what must be installed? |
| 2 | [Understand the sample](/docs/course/data) | What is an image, an annotation, a class and a split? |
| 3 | [Import with preflight](/docs/course/import) | What should be fixed or explained before the project is written? |
| 4 | [Explore the data](/docs/course/explore) | What can images, statistics, patches and Health tell us? |
| 5 | [Freeze a baseline](/docs/course/baseline) | How do we preserve exactly what an experiment uses? |
| 6 | [Review, edit and recover](/docs/course/review) | What did a person inspect, and did their change really save? |
| 7 | [Train the first model](/docs/course/train) | What does each recipe setting mean? |
| 8 | [Read the evidence](/docs/course/results) | What do scores, predictions and an empty findings queue mean? |
| 9 | [Run a controlled comparison](/docs/course/compare) | Did a planned change produce a credible difference? |
| 10 | [Approve and export](/docs/course/handoff) | Exactly what are we approving and handing over? |
| 11 | [Back up, restore and share](/docs/course/backup) | Can the work survive relocation and controlled collaboration? |
| 12 | [Move to your own project](/docs/course/next) | What must change before this becomes a real production workflow? |

## How to use the screenshots and videos

Screenshots and **10 captioned clips** were captured from the actual dashboard, against a real local
service—not a mock interface. Select a screenshot to open the full-resolution image. Each video has
native playback controls, English captions and a text transcript. The videos are silent and never autoplay.

<figure class="doc-figure">
<a href="/assets/course/06-overview.webp"><img src="/assets/course/06-overview.webp" alt="Actual aerial-walkthrough project overview, connecting imported images, dataset versions and runs." width="1440" height="960" loading="lazy"></a>
<figcaption>The real course workspace after import. Later lessons add revisions, runs and a separate approved excerpt; your timestamps and version suffixes will differ.</figcaption>
</figure>

The clips were recorded on Linux on **2 October 2026**, using a Granum 0.1.0 source checkout and
Chromium at 1440 × 960. They document those source workflows; they do **not** certify a downloadable
Windows installer, AppImage, a different GPU or every supported model family. Check your build identity
in the next lesson. Some recording order differs from lesson order; the baseline was frozen before review.

Download the [measured run evidence](/assets/course/evidence.json),
[backup/restore receipt](/assets/course/operations-evidence.json) and
[sample checksum](/assets/course/aerial-mini.sha256). They preserve the observed results, including zeros.

## What we learn—and what we do not

Granum connects data, human decisions and model measurements. It cannot infer a correct labelling
policy from a dataset name, turn a duplicate holdout into independent evidence, or replace domain review.
Throughout the course, **“saved,” “verified,” “frozen,” “approved” and “good model” mean different things**.

## Checkpoint

You know which route you will follow, and you understand that this course approves only a tiny inspected
excerpt. Next: [prepare the workspace and download the sample](/docs/course/setup).

## If you get stuck

Start with the lesson's troubleshooting table. Keep the exact error, build identity, operation and image
or run identifier. Do not send private images or credentials to support without permission. General
help is in [Troubleshooting](/docs/help/troubleshooting).