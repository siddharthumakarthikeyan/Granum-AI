---
title: Frequently asked questions
summary: Short answers about data, teams, formats, models and cost.
---

**Does anything leave my computer?**
No images, no labels, no metrics. The only requests Granum makes are licence activation and renewal,
which carry your email address, a machine id and the app version, and downloading the training add-on and
pretrained weights. → [Your data and privacy](/docs/help/privacy)

**Can two people work on the same project?**
Not at the same time, today. Granum is a single-user desktop application: one machine, one project root,
no accounts. Reviewer names are recorded so you can see who did what among colleagues, but they are not
credentials.

**What formats can I import?**
COCO JSON in the dashboard — one annotation file per set, which is what Roboflow, CVAT and Label Studio
export. YOLO and class-per-folder image directories are available from Python.
→ [Import data](/docs/guides/import)

**Does it change my image files?**
Never. Granum records the path to each image and reads it. The only images it writes are augmented copies
inside a dataset version.

**Do I have to review everything before training?**
No, and usually you should not. Verify the validation set, skim the training set, train, and let
[Findings](/docs/guides/findings) tell you where the remaining effort belongs.

**Why can I only train on dataset versions?**
So that a result is attached to a fixed, named body of data that cannot change afterwards. It is the
difference between "we trained on the training set" and a claim someone can check.
→ [Dataset versions](/docs/concepts/dataset-versions)

**Can I use my own training code?**
Yes. Log runs and per-image metrics from Python and every screen in Granum works on them —
[Use Granum from Python](/docs/guides/python).

**Which model should I pick?**
YOLO nano for the first run, YOLO small or medium for real work, RT-DETR when objects crowd each other,
RF-DETR when you have few images. → [Models you can train](/docs/reference/models)

**Do I need a GPU?**
For training, effectively yes. Everything else — import, review, editing, versioning — runs happily
without one.

**What happens when my plan ends?**
Granum becomes read-only: you can open, read and export everything, but not change or train. Nothing is
deleted or held hostage. → [Sign in and licences](/docs/start/activate)

**Can I move my projects to another machine?**
Copy `~/granum` (and `~/granum-training` for weights). Images are referenced by absolute path, so they
need to be at the same paths on the new machine.

**Is there an API?**
A local REST service the dashboard itself uses, and the Python package underneath it. Both are for local
tooling; neither is a hosted service.

**Does Granum support segmentation or keypoints?**
It stores, shows and edits masks and keypoints, and a project can declare those types. Checks, metrics
and training are box-based today. → [Scale and limits](/docs/reference/limits)
