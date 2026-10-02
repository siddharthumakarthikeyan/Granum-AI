---
title: 7. Train the first model
summary: Train a deliberately small YOLO baseline on the frozen 96/24 input, understand the recipe, and check that the run really finished.
---

**Goal:** create one traceable training run, not a production detector. You need the frozen
[aerial-baseline](/docs/course/baseline). Review practice may have advanced a working table; training
must still select that baseline's original revisions.

No training environment? Read this lesson and continue with the recorded evidence in
[Read the results](/docs/course/results). Never create a fake run to populate the screens.

## What training does, and why we start small

A detector learns numerical weights from the training images and labels. Validation measures how it
behaves on a separate development split and helps select a checkpoint. Starting with a small model
and three epochs makes it practical to check the pipeline, identity joins, output files and metrics
before spending more compute. It does not establish adequate training or useful accuracy.

An **epoch** is one scheduled pass through the training data. A **batch** is the group processed in a
training step. **Image size** controls the trainer's input resizing. A **checkpoint** is a saved set
of model weights. A **seed** controls some sources of randomness but does not guarantee identical
results across devices, library versions or kernels.

## Step 1: check training support

1. Confirm the original sample images remain accessible.
2. Open **Datasets** and select **aerial-baseline**.
3. Choose **Train**. If offered **Install training support**, read and complete the installation before
   starting a run. A GPU driver is a separate prerequisite for CUDA.
4. Check the detected device and available disk space. On CPU, use the same small exercise only if
   the runtime is acceptable; you can instead follow the recorded result.
5. Inspect logs for environment or dependency failures. Do not treat package installation as a
   successful training job.

Packages and pretrained weights may be downloaded. Some framework integrations perform version
checks or connect to an already-configured experiment tracker. Review that environment before using
private data; “local-first” does not make third-party training libraries universally offline.

## Step 2: set the recipe explicitly

| Control | Course setting | Why |
|---|---|---|
| Dataset version | aerial-baseline | Pins the original 120-image experiment input |
| Train on | train, 96 images | These images fit the weights |
| Validate on | valid, 24 images | Separate development observations; still too small for a strong claim |
| Test on | None | The supplied source has no independent test set |
| Model family | YOLO | The recorded exercise uses the Ultralytics integration |
| Weights | YOLO26 nano | Small starting model; model parameter name is yolo26n.pt |
| Image size | 640 px | Small workflow recipe, not necessarily adequate for tiny aerial objects |
| Epochs | 3 | Enough to exercise repeated logging; not an adequate convergence study |
| Compare with | None | This is the first run |
| Per-sample metrics and predictions | Enabled every epoch | Lets Granum connect measurements to each input image |

The recorded backend recipe used **batch 16, seed 0, initial learning-rate parameter 0.01 and optimizer
auto**. Not all backend parameters have separate controls in this dialog; inspect the saved run rather
than assuming a hidden setting. Framework defaults can include augmentation even though the dataset
version added none.

Read and check **I understand this is exploratory training. This version has not passed the release
approval gate.** That acknowledgement is appropriate for this unreviewed baseline. It is not a claim
of approval and should not be replaced by bulk verification.

<figure class="doc-figure">
<a href="/assets/course/17-training-recipe.webp"><img src="/assets/course/17-training-recipe.webp" alt="Actual Train model dialog selects aerial-baseline, YOLO26 nano, 640 pixels, three epochs, no test set and exploratory acknowledgement." width="1440" height="960" loading="lazy"></a>
<figcaption>Confirm version membership and split roles before the model settings. A polished loss curve cannot repair an incorrect split.</figcaption>
</figure>

## Step 3: start and follow the job

Choose **Start training** once. The service starts a separate process and creates a run entry. Open
**Runs**, note the generated name, and inspect the progress and log. Do not launch another model job
while this one is active. Avoid stopping the service or moving the input data during training.

<figure class="doc-figure">
<a href="/assets/course/18-training-started.webp"><img src="/assets/course/18-training-started.webp" alt="Real submitted training job appears in Granum with progress and a run identifier." width="1440" height="960" loading="lazy"></a>
<figcaption>This screenshot is job submission, not completion. The short video does not include the full training runtime.</figcaption>
</figure>

## Step 4: verify completion and provenance

Wait for the job to finish, then inspect the run's status, parameters, input versions, history and
weights path. If it failed, preserve the log and investigate; a partial history is not a finished model.

The recorded baseline is **run-1002-165347**, with three completed epochs. Your generated name, time
and precise numbers may differ. Its saved evaluation policy is **granum-detection-1**, operating
confidence **0.25**, matching IoU **0.5**, and final-scoring prediction floor **0.01**.

**Confidence** is the model's score used to accept or reject a prediction; it is not automatically a
calibrated probability of truth. **IoU** measures box overlap relative to their combined area. The
chosen matching threshold determines whether a prediction can match a labelled object.

## Watch the submission

<figure class="doc-figure doc-video">
<video controls preload="none" playsinline poster="/assets/course/17-training-recipe.webp" aria-label="Recorded three-epoch baseline recipe and real job submission" aria-describedby="train-video-caption">
<source src="/assets/course/05-train.mp4" type="video/mp4"><track kind="captions" src="/assets/course/05-train.vtt" srclang="en" label="English" default>
<a href="/assets/course/05-train.mp4">Download the recording</a>.
</video><figcaption id="train-video-caption">14 seconds · silent, with captions · setup/submission only, not elapsed training time.</figcaption>
</figure>
<details class="doc-transcript"><summary>Read the video transcript</summary>
<ol><li>Use YOLO nano, 640 pixels and three epochs for a small workflow exercise.</li><li>Keep Test on None and record per-sample history.</li><li>The actual job is submitted to a separate process. Read progress and logs; running is not finished.</li></ol>
</details>

## What we learn

A useful experiment has identifiable inputs, settings, a completed outcome and inspectable artifacts.
That is distinct from having a good model. This baseline's very poor result is evidence to investigate,
not a reason to declare the sample labels wrong.

## Checkpoint

You can identify the finished three-epoch baseline, its train/valid versions and its scoring policy.
If you skipped local training, you can identify those facts in the
[recorded evidence](/assets/course/evidence.json). Next: [read results without overclaiming](/docs/course/results).

## If something differs

| Symptom | What to do |
|---|---|
| Start is disabled | Check dependencies, split/version selection, exploratory acknowledgement and existing active jobs |
| CUDA out of memory | Stop the failed job, inspect the recipe/device and use an appropriate smaller workload; record any changed settings |
| No model weights download | Check the model source and permitted network access; do not execute arbitrary replacement weights |
| No per-image history | Check that per-sample logging was enabled and completed, not just framework epoch scalars |
| Different scores from the recording | Record your environment, seed, inputs and evaluator; a course run is not a reproducibility guarantee across environments |
| Shared user cannot train | A viewer or annotator does not have reviewer/admin job permissions |