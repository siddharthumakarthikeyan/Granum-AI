---
title: Frequently asked questions
summary: Short answers about data, teams, formats, models and cost.
---

**Does anything leave my computer?**
Local workflows do not upload datasets to Granum. Optional cloud storage, shared access and model/package
downloads use the destinations you configure. The current alpha requires no licence-server activation
or renewal. → [Your data and privacy](/docs/help/privacy)

**Can two people work on the same project?**
The current source supports HTTPS-authenticated shared access with workspace-wide roles and stale-edit
checks. All accounts can read the whole workspace; it is not per-project tenancy or an assignment system.
Local mode remains loopback-only with self-reported names. Check that your installer contains these changes.

**What formats can I import?**
COCO JSON in the dashboard — one annotation file per set, which is what Roboflow, CVAT and Label Studio
export. YOLO and class-per-folder image directories are available from Python.
→ [Import data](/docs/guides/import)

**Does it change my image files?**
Never. Granum records the path to each image and reads it. The only images it writes are augmented copies
inside a dataset version.

**Do I have to review everything before training?**
Not for an explicitly acknowledged exploratory version. **Approval is separate**: every included image's
exact labels, schema and media must match review evidence. Approved-only training rechecks that evidence.
[Findings](/docs/guides/findings) helps prioritize further review; it does not automatically approve data.

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
The current unrestricted alpha has no enforced subscription expiry. Use and paid support remain subject
to written agreement, and future terms may differ. No automatic checkout is active.
→ [Alpha access and licences](/docs/start/activate)

**Can I move my projects to another machine?**
Stop project writers, create a checksummed project snapshot with `granum backup create`, and restore it
under a new project name with `granum backup restore`. Supported local media paths are relocated.
External project/table dependencies are refused rather than silently omitted; environments and training
caches are not a complete system backup. Rehearse on a disposable destination before relying on it.

**Is there an API?**
A REST service and a Python SDK. The default is local; explicitly configured shared access requires
authentication and HTTPS. Neither is a managed hosted service.

**Does Granum support segmentation or keypoints?**
It stores, shows and edits masks and keypoints, and a project can declare those types. Checks, metrics
and training are box-based today. → [Scale and limits](/docs/reference/limits)
