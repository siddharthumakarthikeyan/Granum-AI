---
title: 1. Prepare the workspace
summary: Check the installed build, download and verify the real sample, and separate source data, project records and backups.
---

**Goal:** open Granum and place the sample somewhere it can safely remain throughout the course.
You need permission to use the application and enough local disk space for the sample and project copies.
You do not need training dependencies yet.

## What you are setting up, and why

Granum's **dashboard** is the interface. Its **service** reads images and writes project records. In the
default local mode both run on your machine. Closing an editor, closing a desktop window and stopping
the service are different actions.

An imported image may remain a **reference to the source file**. Moving or deleting that folder can
therefore break a project even though its annotation table still exists. Keep source data separate
from generated project records and from backups.

## Step 1: check the build before starting

1. Open the [download page](/download). Use an artifact explicitly qualified for your platform, or an
   authorized development checkout supplied by the project maintainer.
2. Compare the artifact's published SHA-256 and build manifest with the file you received. A matching
   version string alone is not enough: two files can both say 0.1.0 and contain different source changes.
3. Follow [Install Granum](/docs/start/install). Do not bypass a security warning merely because this
   documentation mentions the installer. Confirm its origin and checksum first.
4. Launch **Granum**. The local dashboard normally uses `http://127.0.0.1:8000`; an explicitly configured
   port can differ. The recordings use an isolated service on port 18861.
5. If the CLI is available, record the output of `granum version`, `granum app status` and
   `granum build-info`. Check that the running service points at the intended project root.

!!! note "If no qualified download is available"
    Ask the rollout maintainer for the approved pilot build. Do not substitute an older installer and
    assume it includes current approval and recovery safeguards. You can still read the entire course
    and its real recordings. Source-build instructions are for authorized developers, not a claim of
    clean-machine installer qualification.

## Step 2: download and check the sample

1. Download the [aerial-mini archive](/assets/course/aerial-mini.zip) and its
   [SHA-256 checksum](/assets/course/aerial-mini.sha256).
2. Verify the archive before extracting it. On Linux, place both downloads in one folder and run the
   command below there. On Windows, compare the output of `Get-FileHash` with the published checksum.
3. Extract the **whole** archive. Do not pick out only the JPEGs or only the annotation JSON.
4. Move the extracted aerial-mini directory to a permanent data folder you own, not a temporary or
   automatically cleaned Downloads location.
5. Keep its attribution and manifest with it. The [next lesson](/docs/course/data) explains their scope.

```bash
sha256sum --check aerial-mini.sha256
```

```powershell
Get-FileHash .\aerial-mini.zip -Algorithm SHA256
```

The archive is **27,693,885 bytes (26.4 MiB)**. Its expected SHA-256 is:

```text
2641dcdfbd88fea0bea27b59689f68b3b9a1d1fbd4b3d8c4da1a2c62789efa5d
```

The checksum detects an unexpected or incomplete file; it does not independently establish ownership
of the images or make the annotation content correct.

## Step 3: check the extracted layout

```text
aerial-mini/
  ATTRIBUTION.txt
  START-HERE.txt
  manifest.json
  train/
    _annotations.coco.json
    ...96 image files...
  valid/
    _annotations.coco.json
    ...24 image files...
```

There is deliberately **no test directory**. Do not manufacture one by copying validation.
Annotation files contain both image records and box records; their counts are not the same.

## Step 4: choose safe locations

| Purpose | Example on Linux | Keep in mind |
|---|---|---|
| Source images and COCO files | `~/datasets/aerial-mini` | Leave in place; Granum may reference these bytes |
| Granum project root | `~/granum` | Project directories are created under its projects subdirectory |
| Training output | `~/granum-training` | Weights and framework caches can be much larger than the sample |
| Backups | A separate protected backup folder or volume | Never create the backup inside the project being backed up |

Windows uses corresponding user-profile folders. Read [Files and settings](/docs/reference/files)
for platform-specific paths. Avoid a network share or cloud-synced writable folder for this first
exercise; those storage systems are not qualified by the local writer-lock tests.

## Optional: prepare to train

The training dialog can offer **Install training support**. Its packages, CUDA runtime and model
weights require additional space and may need network downloads. Granum's core browsing/review route
does not require a GPU. A supported NVIDIA driver is needed for CUDA; package installation does not
install that driver for you.

The recorded run used PyTorch 2.12.0+cu130, Ultralytics 8.4.65 and an NVIDIA RTX PRO 4000 Blackwell
Generation Laptop GPU. These are **capture facts**, not the only supported combination or a recommended
upgrade for every computer. Do not replace a working environment merely to match a screenshot.

## What we learn

The application, source data, versioned project records and training environment have different
lifetimes. A backup of only the project folder may miss externally referenced media. Unsaved editor
drafts live in the browser profile, not in the project backup.

## Checkpoint

- Granum opens, and you have recorded its version/build identity.
- The archive checksum matches.
- The extracted folder contains train and valid with their COCO files.
- Source data is outside the project and backup destinations.

Next: [understand the sample before importing it](/docs/course/data).

## If something differs

| Symptom | What to do |
|---|---|
| Checksum differs | Stop. Re-download from the same trusted source; do not suppress the check |
| Dashboard does not open | Check service status, logs and port; do not expose it to the network as a workaround |
| Folder picker cannot see the data | Check configured data roots and file permissions; do not widen access to the entire filesystem |
| Training support is unavailable | Follow the review-only route and use the recorded evidence in the results lessons |
| Recovery/approval controls are missing | Compare build identities; an older artifact may not include the documented source changes |