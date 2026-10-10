---
title: 3. Import with preflight
summary: Import both splits, read the real findings, choose duplicate-class and ignore-region handling, and verify the written result.
---

**Goal:** create aerial-walkthrough with the expected train/valid split and a record of the import
decisions. First complete [Understand the sample](/docs/course/data).

## What preflight is, and why we use it

Preflight inspects structure, annotations and the selected image-check coverage **before import**.
It can find broken references, invalid boxes, repeated classes and possible leakage. For actionable
findings it presents choices rather than quietly assuming that every source convention is correct.

Preflight is not a full human label review. Passing it does not make a release approved.

## Step 1: choose the project and both splits

1. In the sidebar choose **Create project**.
2. Enter **aerial-walkthrough** as the project name. Use a new name if you already have this project;
   do not overwrite unrelated work to follow the screenshots.
3. Choose **Object detection**.
4. Choose **Select folder** and navigate to the extracted aerial-mini folder.
5. Confirm that **train** and **valid** are found, then choose **Use 2 splits**. Do not select only
   the train folder's contents and accidentally omit validation.
6. For **Image check**, choose **All images**. The sample is small enough to inspect all 120 files.
7. Select **Create project** to run preflight. The flow then shows the report and its import confirmation.

<figure class="doc-figure">
<a href="/assets/course/01-source-folder.webp"><img src="/assets/course/01-source-folder.webp" alt="Folder picker identifies train and valid and offers Use 2 splits." width="1440" height="960" loading="lazy"></a>
<figcaption>Select the parent sample folder, keeping both detected splits.</figcaption>
</figure>
<figure class="doc-figure">
<a href="/assets/course/02-import-setup.webp"><img src="/assets/course/02-import-setup.webp" alt="Import setup for aerial-walkthrough with object detection and All images selected." width="1440" height="960" loading="lazy"></a>
<figcaption>All images checks media coverage; Annotations only would not establish that image bytes can be read.</figcaption>
</figure>

## Step 2: reconcile the summary

Read the split totals before resolving warnings. You should see **96 train images, 24 valid images,
7,500 annotation objects and 13 source categories**. There should be no test split.

If these differ, stop here and check the selected directory and archive checksum. Importing first and
explaining a surprising count later makes mistakes harder to trace.

<figure class="doc-figure">
<a href="/assets/course/03-preflight-summary.webp"><img src="/assets/course/03-preflight-summary.webp" alt="Actual preflight report shows the 96-image training and 24-image validation sources and their annotation totals." width="1440" height="960" loading="lazy"></a>
<figcaption>The report describes the source before decisions such as duplicate-category merging are applied.</figcaption>
</figure>

## Step 3: read each decision

1. Read the finding title, severity, counts and example—not just its recommended action.
2. For duplicate **people** category names, retain the duplicate-name merge. The unused ID 0 and used
   ID 9 do not need to remain two separate classes with the same display name.
3. For **A category looks like an ignore marker, not an object**, choose **Mark as ignore regions**.
   This preserves the boxes and marks them as crowd/ignore rather than ordinary positive targets.
4. Read any sequence/grouping or leakage warnings. Do not “fix” independence by arbitrarily moving
   sliders or suppressing a warning. The source test duplication and selection limitations remain
   documented even when this small subset has no byte-identical cross-split pairs.
5. Read all other findings. If your build proposes a different action, compare its build identity
   and the source evidence before proceeding.

<figure class="doc-figure">
<a href="/assets/course/04-preflight-decision.webp"><img src="/assets/course/04-preflight-decision.webp" alt="Ignore-marker finding explains why ignored regions should be retained as crowd or ignore regions instead of target objects." loading="lazy"></a>
<figcaption>This is an interpretation decision, not deletion of difficult objects. Preserve individually labelled pedestrians and vehicles.</figcaption>
</figure>

## Step 4: import and inspect the result

Select **Import**, then wait for **Imported into aerial-walkthrough**. Read the applied decisions.
The import writes versioned tables and the import report; it does not rewrite the original COCO files.
Open the project. The working dataset should be **aerial-mini** with the two original split sizes.

<figure class="doc-figure">
<a href="/assets/course/05-import-complete.webp"><img src="/assets/course/05-import-complete.webp" alt="Successful real import into aerial-walkthrough with the completed split results." width="1440" height="960" loading="lazy"></a>
<figcaption>Completion is a write result, not a statement that all labels have been reviewed.</figcaption>
</figure>

## Watch the actual import

<figure class="doc-figure doc-video">
<video controls preload="none" playsinline poster="/assets/course/03-preflight-summary.webp" aria-label="Recorded import and preflight demonstration" aria-describedby="import-video-caption">
<source src="/assets/course/01-import.mp4" type="video/mp4">
<track kind="captions" src="/assets/course/01-import.vtt" srclang="en" label="English" default>
Your browser cannot play this video. <a href="/assets/course/01-import.mp4">Download the recording</a>.
</video>
<figcaption id="import-video-caption">22 seconds · silent, with captions · actual local import. Pause to read each finding.</figcaption>
</figure>
<details class="doc-transcript"><summary>Read the video transcript</summary>
<ol><li>Create a new object-detection project named aerial-walkthrough.</li><li>Choose the extracted aerial-mini folder. Keep train and valid; there is no independent test.</li><li>Preflight checks 96 training and 24 validation images before writing the project.</li><li>Read the ignore-region decision and preserve those regions as ignore/crowd.</li><li>The completion report records applied decisions; original source files are unchanged.</li></ol>
</details>

## What we learn

You can distinguish a source count from a post-import class mapping, an automatic structural check
from a human judgement, and a recorded choice from an unexplained silent transformation. Those
distinctions matter when another person asks why a model saw a particular label set.

## Checkpoint

The project contains **120 images**, split 96/24. The source is untouched, duplicate-name handling is
recorded, and ignore boxes are retained with crowd/ignore semantics. You have not marked the dataset
verified or approved. Next: [explore the working data](/docs/course/explore).

## If something differs

| Symptom | What to check |
|---|---|
| One split or no splits detected | Select the extracted parent folder containing both COCO files |
| Missing or unreadable images | File permissions, extraction completeness and relative image references |
| Different totals | Course archive vs full source; nested duplicate folders; checksum |
| A blocking finding | Resolve it or obtain a correct source export; do not invent coordinates to bypass it |
| Import fails during writing | Preserve the error/log and inspect whether a project was created before retrying with a new name |

See the [preflight reference](/docs/reference/preflight) for individual check meanings.