---
title: 6. Review, edit and recover
summary: Inspect two real images, practise recovery without leaving a false label, and separate annotation saves from human review decisions.
---

**Goal:** learn the editor and its recovery boundary, then verify only two images you actually inspect.
The [120-image baseline](/docs/course/baseline) must already be frozen. This lesson does not claim a
label-quality improvement: the demonstrated practice change is deliberately restored before saving.

## What review is, and why it is separate from saving

An **annotation save** writes a table revision. A **review decision** records a person's judgement
about the image's contents. Saving a box does not prove it was inspected. Verification requires looking
at the full image, checking classes, geometry, missing objects and the applicable labelling policy.

Changing annotations resets the affected image to unverified. Comments explain a decision but do not
change a box. In local mode the **Reviewer** name is self-reported; it is not authenticated identity.

## Step 1: locate the first image

1. Open **Images → aerial-mini**, select **train**, and clear previous class/status filters.
2. Open **Fields**. Under **Image id**, set both numeric range endpoints to **11155**. There should be
   one image. Close Fields if you need more space.
3. Its file name starts **0000099_00149**. Turn on **Edit** and open it.
4. Inspect the complete 960 × 540 image, not only the box crop. It contains one visible pedestrian.
5. Select the existing box. In the recorded inspection its pedestrian class and visible bounds were
   retained; there was no need to invent a correction.

Image IDs are scoped to an imported split; do not assume ID 11155 means the same image in another
project. The file-name prefix and screenshot provide a second check.

<figure class="doc-figure">
<a href="/assets/course/11-annotation-editor.webp"><img src="/assets/course/11-annotation-editor.webp" alt="Actual annotation editor shows the one pedestrian in training image 11155 with its existing bounding box selected." width="1440" height="960" loading="lazy"></a>
<figcaption>Inspect the whole image for missing objects as well as the selected rectangle. The source pedestrian label is retained in this exercise.</figcaption>
</figure>

## Step 2: practise draft recovery safely

Do this in a browser tab connected to your course service. Keep the same browser profile and service
origin throughout; the desktop window may have a different storage profile.

1. With the object selected, temporarily change **Class of the selected object** from **pedestrian**
   to **people**. This is an intentionally wrong **practice draft**, not a proposed label correction.
2. Do **not** save and do **not** close the editor: leaving an image can save pending changes.
3. Wait for **Recovery copy saved in this browser**. If storage reports an error, stop this exercise
   and restore the original class; do not assume a recovery copy exists.
4. Reload the browser tab. Confirm leaving if the browser asks. On reopening, read
   **Recover unsaved annotations**.
5. Choose **Recover edits**. The temporary people label should return as a draft.
6. Immediately restore **pedestrian**. Check that the geometry and all other properties still match
   the original. Do not leave the deliberate practice label in the dataset.
7. Move focus out of the class select (for example, press Escape), then press **Ctrl+S**.
8. Wait for save confirmation before navigating. Reopen the image to verify the original class persisted.

<figure class="doc-figure">
<a href="/assets/course/12-recover-annotations.webp"><img src="/assets/course/12-recover-annotations.webp" alt="Real Recover unsaved annotations dialog offers recovery of the browser's pending image edits after reload." width="1440" height="960" loading="lazy"></a>
<figcaption>Recovery restores a local draft. It does not mean the draft was committed to the project.</figcaption>
</figure>
<figure class="doc-figure">
<a href="/assets/course/13-saved-annotation.webp"><img src="/assets/course/13-saved-annotation.webp" alt="Editor after the original pedestrian class is restored and saved, with the original box retained." width="1440" height="960" loading="lazy"></a>
<figcaption>The recorded workflow checked the stored boxes against the original and found them equal. Version suffixes can differ if an exercise is repeated.</figcaption>
</figure>

!!! warning "A draft is not a backup"
    Recovery uses IndexedDB in this browser profile. Clearing site data, changing origin/profile,
    private browsing, quota failures or a crash before storage acknowledges the write can lose edits.
    A different base revision prevents automatic replay. Export the draft and reconcile it against
    the latest version; do not repeatedly force a stale save.

If you do not want to practise a temporary relabel, skip that part and inspect the screenshots.
Never create a bad annotation merely so a demonstration can show “improvement.”

## Step 3: record a review decision

1. Exit Edit after the confirmed save, then enable **Review**.
2. Enter your name in **Reviewer**. Shared authenticated mode uses the account identity instead.
3. Open the same image. In the comment field, record what you inspected. The course used:
   “Inspected full image: one visible pedestrian. Practice relabel restored; no source-label correction claimed.”
4. Choose **Comment** to post it. Posting and verifying are separate actions.
5. Choose **Verify (A)** only if you agree with the inspection. It normally advances to the next image
   when one is available. Return with **Previous image** to check the **Verified** state if needed.

<figure class="doc-figure">
<a href="/assets/course/13a-review-verified.webp"><img src="/assets/course/13a-review-verified.webp" alt="Review inspector shows the actually inspected pedestrian image as Verified with the explanatory comment." width="1440" height="960" loading="lazy"></a>
<figcaption>Verification is tied to inspected contents. It is not a button for silencing a training or release warning.</figcaption>
</figure>

## Step 4: inspect one validation image

Close the inspector. Clear the Image id filter, select **valid**, then set both Image id endpoints to
**292**. The file name begins **0000103_01734**. Open it in Review.

The recorded full-image inspection retained **three car boxes and one pedestrian box**, including
visible objects cut by image edges. Inspect them yourself: a truncated object is not automatically
an invalid annotation. If your labelling policy is unclear, use Rework rather than copying the course's
decision. The course comment was: “Inspected full image: three cars and one pedestrian. Retain the
visible edge-truncated objects.” Post the comment and verify only if that decision is justified.

## When not to verify

| Action | Use it when | What to record |
|---|---|---|
| Rework (R) | A fix or policy clarification is needed | A concrete reason; “bad image” is not an actionable instruction |
| Unverify (U) | A previous review decision should no longer stand | Why the previous decision needs another look |
| Isolate (I) | An unresolved example must be set aside explicitly | Why it is excluded and who will decide its return |
| Recoverable delete | Removal is justified under the dataset policy | Reason and review trail; inspect the removed set before permanent deletion |

Do not isolate hard validation images merely to improve a score. That changes the evaluation question.
Do not use bulk verification on images you have not inspected.

## Watch recovery and review

<figure class="doc-figure doc-video">
<video controls preload="none" playsinline poster="/assets/course/12-recover-annotations.webp" aria-label="Recorded editor recovery, restoration of the original label and individual verification" aria-describedby="review-video-caption">
<source src="/assets/course/03-review.mp4" type="video/mp4"><track kind="captions" src="/assets/course/03-review.vtt" srclang="en" label="English" default>
<a href="/assets/course/03-review.mp4">Download the recording</a>.
</video><figcaption id="review-video-caption">30 seconds · silent, with captions · practice change restored before save.</figcaption>
</figure>
<details class="doc-transcript"><summary>Read the video transcript</summary>
<ol><li>The pedestrian already has a reasonable box; do not manufacture a correction.</li><li>Temporarily relabel it as people only for unsaved-draft practice.</li><li>Reload offers the browser's draft; nothing is thereby committed.</li><li>Recover it, restore pedestrian, then save. This demonstrates recovery and versioning, not label improvement.</li><li>Record what was inspected and verify only that image.</li><li>Separately inspect and record the second image's review.</li></ol>
</details>

## What we learn

Draft persistence, server save and human verification are three separate checkpoints. A model's poor
score cannot justify changing a source label without looking. An honest “no correction needed” is a
valid outcome of review.

## Checkpoint

Clear filters. In the recorded fresh course project **2 images are verified and 118 are not**. The
working annotation for the practice image equals the source annotation. The frozen aerial-baseline
still points to the original input versions. Next: [train the baseline](/docs/course/train), or read
the recorded evidence if you are following the no-GPU route.

## If something differs

| Symptom | What to do |
|---|---|
| No recovery offer | Check acknowledged draft storage, same profile/origin, and whether leaving the image already saved it |
| Save shortcut does nothing | Move focus out of an input/select; check for an in-progress save or unresolved comment |
| Conflict / stale revision | Keep or export the draft, open the latest image and reconcile intentionally |
| Verify appears to show another image | It advances; return to the inspected image to check the saved review state |
| Review count exceeds two | An earlier exercise already left decisions; inspect them rather than claiming this run reviewed them |

More: [Edit annotations](/docs/guides/edit) and [Review](/docs/guides/review).