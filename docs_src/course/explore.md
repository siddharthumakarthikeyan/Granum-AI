---
title: 4. Explore before changing labels
summary: Use the gallery, statistics, object patches, fields and Health to form testable questions rather than automatic cleanup rules.
---

**Goal:** understand what is in the imported data and choose what to inspect next.
Your [import](/docs/course/import) should contain 96 train and 24 valid images.

## What these views are for

The **Images** page is your working collection. **Stats** summarises the current selection. **Patches**
compares individual labelled objects. **Fields** filters recorded attributes. **Health** summarises
available measurements and their limitations. These are different views of evidence, not five
independent approvals of the dataset.

## Step 1: find your way around

1. Open **aerial-walkthrough**. The overview connects images, dataset versions and runs.
2. Open **Images**, with **aerial-mini** selected.
3. Start with all splits and no class, review-status or field filters. Confirm the total is 120.
4. Choose **train**, then **valid**, and confirm 96 and 24 respectively.
5. Return to all splits. Open a few full images and compare the labels with what is actually visible.
   At this stage, look rather than edit.

<figure class="doc-figure">
<a href="/assets/course/07-images.webp"><img src="/assets/course/07-images.webp" alt="Real aerial-mini gallery with image thumbnails, split controls and the Stats, Fields, Patches, Review and Edit actions." width="1440" height="960" loading="lazy"></a>
<figcaption>A gallery filter changes what you see. It does not, on its own, define the membership of a future dataset version.</figcaption>
</figure>

## Step 2: ask a question with Stats

Open **Stats**. Read the current scope before interpreting a number: all data or a filtered subset?
Look at class counts and object sizes. Ask:

- Are a few classes much more common than the rest?
- Are there many small boxes that will become tiny when an image is resized for training?
- Is validation representative of the training conditions you want to measure?
- Is a class absent from a split, so that its performance cannot be estimated there?

<figure class="doc-figure">
<a href="/assets/course/08-image-statistics.webp"><img src="/assets/course/08-image-statistics.webp" alt="Statistics panel beside the gallery displays measured class and object-size distributions for the working images." width="1440" height="960" loading="lazy"></a>
<figcaption>Counts describe this dataset and filter scope. They do not decide which classes your application needs.</figcaption>
</figure>

Do not immediately delete common classes to make a balanced chart. A class distribution may reflect
real deployment—or a collection bias. That is a question for sampling and domain review, not a rule
that “all bars should have the same height.”

## Step 3: compare objects with Patches

1. Close **Stats**, then choose **Patches**.
2. Inspect repeated objects within a class. Look for obviously inconsistent naming or unexpected crops.
3. Open an interesting object back in its full image. Context can reveal an occlusion, edge truncation
   or annotation convention that the crop alone hides.
4. Return to the gallery when done.

<figure class="doc-figure">
<a href="/assets/course/09-patches.webp"><img src="/assets/course/09-patches.webp" alt="Actual object-patch grid shows individual cars, pedestrians and other labelled aerial objects rather than whole images." width="1440" height="960" loading="lazy"></a>
<figcaption>Patches helps compare annotation consistency. The loaded page is a subset of objects, not necessarily all 7,500 source annotation objects at once.</figcaption>
</figure>

Small or ambiguous patches are reasons to inspect the original image, not automatically wrong labels.
Do not relabel “people” to “pedestrian” based only on a crop and the English words.

## Step 4: use Fields without losing your scope

Open **Fields**. Controls are generated from columns that actually exist. This COCO sample includes
**Image id**, a numeric identifier—not a measurement of image quality. Its range controls are useful
for locating a known sample, as in the review lesson. A richer dataset might also have camera, site
or capture-time fields; the course does not invent those columns.

After narrowing a view, use **Clear** in Fields and reset the split/class/status filters when you want
the whole collection again. A zero-result view often means filters intersect to nothing, not that the
images have been deleted.

## Step 5: read Health as a coverage report

Open **Health** for aerial-mini. Read each check, its evidence and its scope. Some checks summarise
measurements already available; a check marked **not looked at** has not become a pass simply because
you opened this screen.

<figure class="doc-figure">
<a href="/assets/course/10-health.webp"><img src="/assets/course/10-health.webp" alt="Actual Health report presents dataset risks and measurement coverage, including checks without enough evidence." width="1440" height="960" loading="lazy"></a>
<figcaption>With only 24 validation images, small-support warnings are expected. A threshold is a triage policy, not a statistical law.</figcaption>
</figure>

Similarity, uniqueness and duplicate analysis can require additional computed features. If a view
offers to compute them, inspect the job and dependency requirements first. Similar-looking pairs are
candidate duplicates; byte-identical files are a stronger but narrower finding. Neither detects every
form of sequence leakage.

## Watch the exploration

<figure class="doc-figure doc-video">
<video controls preload="none" playsinline poster="/assets/course/09-patches.webp" aria-label="Recorded gallery, statistics, patches and Health tour" aria-describedby="explore-video-caption">
<source src="/assets/course/02-browse.mp4" type="video/mp4"><track kind="captions" src="/assets/course/02-browse.vtt" srclang="en" label="English" default>
<a href="/assets/course/02-browse.mp4">Download the recording</a>.
</video><figcaption id="explore-video-caption">20 seconds · silent, with captions · real imported images.</figcaption>
</figure>
<details class="doc-transcript"><summary>Read the video transcript</summary>
<ol><li>The overview connects working data, dataset versions and model runs.</li><li>Images is the working collection; filters do not define version membership.</li><li>Stats shows class imbalance and object sizes before a recipe is chosen.</li><li>Patches compares individual labels; inspect the full image before changing one.</li><li>Health flags measurable risks, not universal label correctness.</li></ol>
</details>

## What we learn

Write down at least two questions, such as “Will 640-pixel training preserve enough detail for these
small objects?” and “Do the rare classes have enough validation examples?” These questions motivate
experiments. They are not conclusions that a label or a model is wrong.

## Checkpoint

You can recover the unfiltered 120-image view and explain the difference between image counts and
object counts. You have questions to investigate, without silently deleting or relabelling anything.
Next: [freeze the baseline before review practice](/docs/course/baseline).

## If something differs

| Symptom | What to do |
|---|---|
| Fewer images than expected | Clear Fields, class, split and status filters; check loaded-page vs total counts |
| Blank or broken thumbnails | Check source-file locations and service permissions, not just annotation rows |
| Duplicate analysis has no results | Check whether the required features were computed; “not measured” is not “none exist” |
| Health warning on a tiny split | Read the minimum-support policy; do not copy train images into validation to silence it |
| Patches shows only a few hundred objects | Load more if needed; the grid is paginated for responsiveness |