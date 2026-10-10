---
title: 10. Approve and export an excerpt
summary: Approve exactly the two inspected images and export a portable COCO copy, without calling the remaining sample reviewed or the model ready.
---

**Goal:** make an explicit, limited handoff. You need the two individual reviews from
[Review, edit and recover](/docs/course/review). Training is not a prerequisite for approving those
contents, and a good training score would not replace their review.

## What we are approving, and why

The full course sample contains 120 images, but only **two** were individually inspected in the
demonstration. We will approve a named **two-image excerpt**, not aerial-baseline and not the whole
working collection. It is too small for meaningful training or evaluation.

Approval binds a review decision to exact included rows, schema and media hashes. It records what
passed the gate. It does not certify objective label truth, complete dataset coverage, sufficient
sample size or model readiness. Filesystem owners remain trusted; this is not a signed legal attestation.

## Step 1: create the verified-only excerpt

1. Return to **Images → aerial-mini**. Clear all filters and inspect the review count.
2. For a fresh course run, expect **2 verified** images: one train and one valid. If the count differs,
   inspect the decisions before continuing.
3. Choose **Create dataset**.
4. Name it **aerial-reviewed-excerpt**.
5. Describe the scope explicitly: “Two inspected images only: one train / one valid. Approval/export
   demonstration, NOT a sufficient training or evaluation dataset.”
6. Choose **Use only verified**. Keep the existing split membership and add no version augmentation.
7. Check **2 included images**, then **Create dataset**.

<figure class="doc-figure">
<a href="/assets/course/28-verified-excerpt.webp"><img src="/assets/course/28-verified-excerpt.webp" alt="Create exploratory dataset version dialog selects only the two verified images and names the limited aerial-reviewed-excerpt." width="1440" height="960" loading="lazy"></a>
<figcaption>Verified-only selects contents. The newly created excerpt is still exploratory until approval is explicitly performed.</figcaption>
</figure>

## Step 2: approve those exact contents

Open **Datasets**, select **aerial-reviewed-excerpt**, then **Approve… → Check and approve**. The gate
checks that every included image has matching current review evidence and readable, unchanged media.
For the recorded two-image excerpt it passed and the badge became **Approved**.

<figure class="doc-figure">
<a href="/assets/course/29-approved-excerpt.webp"><img src="/assets/course/29-approved-excerpt.webp" alt="Actual Datasets page shows aerial-reviewed-excerpt approved while the full aerial-baseline remains exploratory." width="1440" height="960" loading="lazy"></a>
<figcaption>Only the two-image excerpt is approved. The other 118 images have not acquired review evidence by association.</figcaption>
</figure>

If approval is refused, read the exact reason. Later edits, stale review evidence, changed/missing media,
empty sets or duplicate image references can invalidate the requested approval. Fix the actual problem
and re-review if necessary; do not edit the approval log to make the badge appear.

## Step 3: choose a portable export

Choose **Export** on the approved excerpt. Keep **COCO** as the format. For **Image files**, choose
**Copy them**, then **Write 2 images**. Wait for **Written**, and note the output directory.

<figure class="doc-figure">
<a href="/assets/course/30-export-options.webp"><img src="/assets/course/30-export-options.webp" alt="Export aerial-reviewed-excerpt dialog selects COCO and Copy them for a two-image portable export." width="1440" height="960" loading="lazy"></a>
<figcaption>Copy them is intentional: recipients should not depend on your original image locations.</figcaption>
</figure>

| Image-files option | Meaning | Handoff consequence |
|---|---|---|
| Link to them | References source image locations | Can break when moved to another machine or after source deletion |
| Copy them | Writes separate image copies with exported labels | The straightforward portable choice for this lesson |
| Hard link them | Shares local file content through filesystem hard links where supported | Not an independent backup; filesystem constraints apply |
| Labels only | Omits image copies | Recipient must already have the exact corresponding media |

Export writes to the service machine's project export directory. It is not automatically a browser ZIP
download, and in shared mode the service's filesystem is not necessarily your laptop's filesystem.

<figure class="doc-figure">
<a href="/assets/course/31-export-complete.webp"><img src="/assets/course/31-export-complete.webp" alt="Actual export completion dialog reports Written and the output directory for the one-image train and valid splits." width="1440" height="960" loading="lazy"></a>
<figcaption>Read the destination and inspect its contents before sending anything to a recipient.</figcaption>
</figure>

## Step 4: inspect the delivery, not just the success message

1. Open the output directory on the service machine.
2. Confirm one image in train and one in valid, with their COCO annotation files. The recorded export
    retained five objects: one in train and four in valid.
3. Open both images and check that exported image references resolve within the copied delivery.
    The actual layout has an annotation file and a separate image folder **inside each split**:

```text
export-directory/
   train/
      annotations.json
      images/           one copied image
   valid/
      annotations.json
      images/           one copied image
```

For a COCO reader, use the split's **images directory as its image root**. The JSON's `file_name` is
relative to that image root, not necessarily to the annotation file's parent. The recorded export's
two files were checked as independent copies with hashes matching the originals.

Continue the handoff checks:

4. Inspect the labels and class mapping with the recipient's intended reader. COCO and YOLO use
   different coordinates/class conventions; file extensions alone do not establish compatibility.
5. Include the source attribution and a handoff note naming the excerpt, approval scope, format,
   image-copy mode and limitations. Preserve the original full dataset separately.

Do not call this two-image package a useful evaluation holdout. A format round trip proves that
records can be read; it does not prove label quality or model performance.

## Watch approval and export

<figure class="doc-figure doc-video">
<video controls preload="none" playsinline poster="/assets/course/29-approved-excerpt.webp" aria-label="Recorded verified-only excerpt approval and portable COCO export" aria-describedby="handoff-video-caption">
<source src="/assets/course/09-handoff.mp4" type="video/mp4"><track kind="captions" src="/assets/course/09-handoff.vtt" srclang="en" label="English" default>
<a href="/assets/course/09-handoff.mp4">Download the recording</a>.
</video><figcaption id="handoff-video-caption">24 seconds · silent, with captions · two inspected images only.</figcaption>
</figure>
<details class="doc-transcript"><summary>Read the video transcript</summary>
<ol><li>Create a verified-only excerpt from the two inspected images, not the other 118.</li><li>Approval pins exact annotations and media, recording a review decision rather than certifying model quality.</li><li>Export COCO with Copy them for portability; links depend on original paths.</li><li>Confirm the destination and the one-image train and valid splits. Export is not a project-history backup.</li></ol>
</details>

## What we learn

Selection, approval and export are separate operations. A COCO handoff contains data for another tool;
it is **not a complete backup of Granum reviews, runs, lineage and approval history**. Protect those
records with the project-backup workflow next.

## Checkpoint

The full baseline remains exploratory; aerial-reviewed-excerpt is approved; the copied COCO output
contains exactly the two intended images. Your handoff note does not claim a production model or a
fully reviewed 120-image sample. Next: [back up and rehearse a restore](/docs/course/backup).

## If something differs

| Symptom | What to do |
|---|---|
| More than two images selected | Cancel and inspect which images are verified; do not approve an unexplained selection |
| Approval fails after editing | Inspect the latest contents, re-review them and create/select the intended version |
| Export images fail on another machine | Check whether you exported links instead of copies, and whether all files travelled together |
| Output folder is not on your computer | Export runs on the service host; arrange an authorized transfer from that host |
| Recipient's labels look wrong | Check class IDs, coordinate conventions, ignore semantics and image dimensions before use |