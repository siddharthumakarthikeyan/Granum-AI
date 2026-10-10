---
title: 5. Freeze an exploratory baseline
summary: Preserve the full 120-image input before editing, and see why an immutable version is not the same thing as an approved release.
---

**Goal:** create **aerial-baseline** from the untouched imported working sets, before the next lesson's
practice edit. Complete [Explore the data](/docs/course/explore) first.

## What a dataset version is, and why it matters

The working collection can advance as you edit. A **dataset version** records an exact selection of
table revisions and images for an experiment or handoff. A later edit does not silently change which
table revision an earlier run used.

Granum distinguishes two states:

| State | Meaning | What it does not mean |
|---|---|---|
| Exploratory | A frozen input you can deliberately investigate | Every included image was reviewed |
| Approved | An explicit gate accepted current review evidence for the exact included rows, schema and media | Labels are infallible or the dataset is sufficient for deployment |

**Verified-only** is a selection policy. It still creates an exploratory version until you explicitly
approve it. External image files also need protection: freezing references is not a filesystem snapshot
that stops another program overwriting image bytes.

## Step 1: create the baseline

1. Return to **Images → aerial-mini**. Clear filters so the context is easy to understand.
2. Choose **Create dataset**. The dialog is titled **Create exploratory dataset version**.
3. Enter **aerial-baseline** for **Name**.
4. Enter a description such as: “Course baseline: 96 train / 24 valid. Unreviewed source labels;
   exploratory only. No independent test; no added version-creation augmentation.”
5. Explicitly choose **Use entire dataset**. Do not rely on defaults: once any images are verified,
   the default selection can differ.
6. Keep the existing 96/24 split and add no augmentation in this dialog.
7. Read the included image counts, then choose **Create dataset**.

<figure class="doc-figure">
<a href="/assets/course/14-create-baseline.webp"><img src="/assets/course/14-create-baseline.webp" alt="Create exploratory dataset version dialog names aerial-baseline and includes all 120 unreviewed images." width="1440" height="960" loading="lazy"></a>
<figcaption>The description records the experiment boundary. “No added augmentation” here refers to version creation, not all possible trainer defaults.</figcaption>
</figure>

## Step 2: check the frozen result

Open **Datasets**. Select aerial-baseline and inspect its contents: **120 images, train 96, valid 24**,
with **Exploratory** status. Record its version and description. Numeric version labels and timestamps
in your workspace may differ from the recording.

<figure class="doc-figure">
<a href="/assets/course/15-exploratory-version.webp"><img src="/assets/course/15-exploratory-version.webp" alt="Datasets page lists aerial-baseline as Exploratory with 120 images and separate train and valid counts." width="1440" height="960" loading="lazy"></a>
<figcaption>This is a reproducible input selection—not a release approval.</figcaption>
</figure>

## Step 3: understand an expected refusal

Choose **Approve…**, then **Check and approve**. Because the included contents have not all been
reviewed, approval should be refused. Read the reason and close the dialog. This is a successful
demonstration of a safeguard, not something to bypass.

<figure class="doc-figure">
<a href="/assets/course/16-approval-refused.webp"><img src="/assets/course/16-approval-refused.webp" alt="Approve exact dataset contents dialog refuses approval because the included images lack matching review evidence." width="1440" height="960" loading="lazy"></a>
<figcaption>Do not bulk-verify images to remove this message. Later we approve only a genuinely inspected two-image excerpt.</figcaption>
</figure>

## Watch the baseline and refusal

<figure class="doc-figure doc-video">
<video controls preload="none" playsinline poster="/assets/course/15-exploratory-version.webp" aria-label="Recorded baseline creation and expected approval refusal" aria-describedby="baseline-video-caption">
<source src="/assets/course/04-versions.mp4" type="video/mp4"><track kind="captions" src="/assets/course/04-versions.vtt" srclang="en" label="English" default>
<a href="/assets/course/04-versions.mp4">Download the recording</a>.
</video><figcaption id="baseline-video-caption">16 seconds · silent, with captions · the refusal is intentional.</figcaption>
</figure>
<details class="doc-transcript"><summary>Read the video transcript</summary>
<ol><li>Freeze aerial-baseline from the entire dataset with no added version augmentation.</li><li>It appears as Exploratory; later training records its exact inputs.</li><li>Approval correctly refuses unreviewed contents. Do not verify images merely to dismiss the warning.</li></ol>
</details>

## What we learn

You can preserve an honest unreviewed baseline and still investigate it. Approval and exploration
serve different purposes. A comparison is interpretable only when you know which inputs were frozen,
what changed later, and which scoring labels were held constant.

## Checkpoint

**aerial-baseline remains exploratory and contains all 120 images.** It was created before the
practice edit. Next: [review, edit and recover](/docs/course/review). Do not replace this version with
the two-image excerpt when you reach training.

## If something differs

| Symptom | What to do |
|---|---|
| Only two images included | You selected verified-only after doing review; create a clearly named full baseline from the intended original revisions |
| A split disappeared | Check included sets and image counts before creation; do not substitute train for validation |
| Approval succeeds unexpectedly | Inspect whether the contents already had valid review evidence from an earlier exercise |
| Missing or changed media blocks approval | Restore/protect the intended bytes or re-review changed contents; do not erase the integrity evidence |

Details: [Dataset versions](/docs/concepts/dataset-versions) and [Verification](/docs/concepts/verification).