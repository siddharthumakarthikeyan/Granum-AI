---
title: Scale and limits
summary: What Granum handles comfortably, what is slow, and what it does not do.
---

## Scale

Measured on one modern laptop with an NVIDIA GPU, on a real aerial dataset of 11,335 training and 547
validation images with 621,000 boxes.

| Operation | Behaviour |
|---|---|
| Opening a dataset of 12,000 images | Under a second; the grid pages 120 at a time and box geometry loads a screenful at a time |
| Filtering, sorting, class filters | Instant — done in the browser over one payload |
| An edit saved | One new version, well under a second |
| Import preflight, all images | Annotations are read in seconds; decoding every image dominates, so minutes for tens of thousands |
| A version of a set | About 9 MB for 11,335 images with 621,000 boxes |
| Per-image metrics with boxes | About 15 MB per round for 11,900 dense images; roughly 180 MB for a 12-round run |
| Findings over a finished run | A few seconds, then cached until the run changes |
| A dataset version | Instant; with augmentation, minutes and gigabytes |

Where it gets slow: the browser holds one row per image, so a set of tens of thousands is comfortable
and much beyond that is not. Very dense images — hundreds of boxes each — make the box overlay the cost
rather than the images, which is why geometry is fetched a screenful at a time.

## Current limits

- **One user at a time.** No accounts, no permissions, no locking. Reviewer names are self-reported.
- **One machine.** Projects are local; there is no shared server and no sync.
- **One training job at a time** per machine.
- **Boxes.** The importer reads COCO boxes; masks, keypoints and other fields are preserved and editable,
  but the checks, metrics, findings and training are box-based.
- **Detection only, for training.** Classification data can be held and reviewed; training it is not in
  the dashboard.
- **No video.** Frames imported as images work; there is no timeline, no tracking, no propagation.
- **Windows and Linux.** No macOS build today.

## What Granum deliberately does not do

- **It is not a labelling tool.** It corrects labels well — draw, move, relabel, delete, masks,
  keypoints — but a team labelling from scratch at volume wants a dedicated annotation platform, and
  Granum imports what that produces.
- **It is not a model registry or a deployment system.** It trains, scores and records; shipping the
  weights somewhere is your pipeline's job.
- **It is not an experiment tracker.** Runs are recorded because the data work needs them, not to
  replace the tool your team already uses.
- **It will not tell you a label is wrong.** It tells you which labels are worth your attention, and
  why. → [What the evidence is worth](/docs/concepts/evidence)
- **It does not upload anything.** No telemetry, no images leaving the machine.
  → [Your data and privacy](/docs/help/privacy)
