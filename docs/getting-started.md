# Getting started

## Start with the complete guided course

The [Granum aerial-data course](https://granum.app/docs/course/start) is the primary first-use guide.
It uses a real, attributed 120-image sample and includes screenshots, captioned videos, transcripts,
numbered actions, expected results, checkpoints and troubleshooting. No previous Granum experience or
Python code is required. A no-GPU route uses the recorded evidence.

| Step | Lesson |
|---|---|
| 1 | [Check the build and prepare the workspace](https://granum.app/docs/course/setup) |
| 2 | [Understand images, boxes, classes and the source's duplicate holdout](https://granum.app/docs/course/data) |
| 3 | [Import 96 train and 24 validation images with explicit preflight decisions](https://granum.app/docs/course/import) |
| 4 | [Explore gallery, Stats, Patches, Fields and Health](https://granum.app/docs/course/explore) |
| 5 | [Freeze the exploratory baseline before editing](https://granum.app/docs/course/baseline) |
| 6 | [Inspect two images and practise browser-draft recovery](https://granum.app/docs/course/review) |
| 7 | [Train a small, traceable baseline](https://granum.app/docs/course/train) |
| 8 | [Interpret runs, dynamics, Evaluation and Findings](https://granum.app/docs/course/results) |
| 9 | [Compare three and twelve epochs on the same frozen data](https://granum.app/docs/course/compare) |
| 10 | [Approve and export only the two inspected images](https://granum.app/docs/course/handoff) |
| 11 | [Verify a portable backup and a separate restore](https://granum.app/docs/course/backup) |
| 12 | [Plan your own project's policy, evidence and rollout](https://granum.app/docs/course/next) |

Download the [sample](https://granum.app/assets/course/aerial-mini.zip),
[checksum](https://granum.app/assets/course/aerial-mini.sha256) and
[actual run evidence](https://granum.app/assets/course/evidence.json). The sample has 7,500 source
annotation objects, including 228 ignore regions. It is learning material, not a benchmark. The source's
test folder duplicates validation, so the course deliberately includes no test folder.

The recordings document a Linux 0.1.0 source checkout and small YOLO GPU runs. They do not qualify every
installer, OS, GPU or model family. Neither recorded model is accepted for deployment. Only a two-image
excerpt is approved; the other 118 images are not represented as reviewed.

## Install and verify the intended build

Use a platform-qualified artifact from the maintainer, verify its SHA-256 and build manifest, and
follow the [installation guide](https://granum.app/docs/start/install). If no qualified artifact is
available, request the intended pilot build rather than trusting an older file with the same version.
Do not bypass an operating-system security warning without verifying the artifact's origin.

```bash
granum version
granum build-info
granum app status
granum open --browser
```

The default local dashboard is at http://127.0.0.1:8000; check the configured port/root. Local mode is
loopback-only. Wider access is an explicit [authenticated HTTPS setup](hardening.md), not a port-forward.

Authorized developers can run `./install.sh` from their checkout (optionally `--training` for model
support). See [Development](development.md) for requirements and build/test commands. Training packages,
weights and third-party framework integrations may need network access; core local browsing/review does
not require a GPU.

## The distinctions to remember

- **Saved:** a server-acknowledged table revision. Unsaved recovery copies remain browser-profile data.
- **Verified:** a human review decision for inspected contents; editing resets the affected image.
- **Frozen:** exact experiment inputs in an exploratory dataset version.
- **Approved:** a separate gate validates matching review evidence for all included rows/schema/media.
- **Useful model:** a modelling judgement requiring appropriate held-out evidence, not an approval badge.
- **Exported:** a data handoff; not a complete backup of the project's history.

Do not bulk-verify to bypass a warning or treat a weak model's missed objects as automatically bad labels.
Protect externally referenced image bytes; frozen table metadata does not make their filesystem immutable.

## Keep the work recoverable

Common Linux defaults are `~/granum` for project records and `~/granum-training` for training output.
Source images may remain elsewhere. Inspect the actual configuration rather than assuming every install
uses those paths. Stop writers before backup and restore into a new root:

```bash
granum --project-root-url "$HOME/granum" backup create aerial-walkthrough \
  --output /your/protected/backup/aerial-walkthrough.zip
granum --project-root-url "$HOME/granum-rehearsal" backup restore \
  /your/protected/backup/aerial-walkthrough.zip --name aerial-restored
```

Choose real protected output paths outside the project. Follow the full [integrity/restore
procedure](https://granum.app/docs/course/backup) before trusting a backup. Credentials, audit logs,
browser drafts and Python/CUDA environments need separate protection.

## Task and developer references

- [Importing data](importing.md): preflight and CLI controls.
- [Review and approval](review-and-shipping.md): decisions, edits, versions and the explicit gate.
- [Python SDK](python-sdk.md): tables, runs, metric identity and integrations.
- [Operational hardening](hardening.md): access, integrity, durability and recovery limits.
- [Measured scale](scaling.md) and [release qualification](release-qualification.md): what has actually been checked.
