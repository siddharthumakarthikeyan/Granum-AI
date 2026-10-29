---
title: Choose an import format
summary: Select the right input layout, preserve annotation meaning and verify the imported result.
status: partial
---

Choose a format based on the labels you need to retain. Granum's project import runs a preflight before
committing data. Python table constructors provide another entry point; they do not substitute for
checking a dataset's splits and annotation quality.

## Supported paths

| Source | Entry point | Check after import |
|---|---|---|
| COCO JSON and image folders | Import wizard or `Table.from_coco` | Class IDs, image dimensions, crowd flags and masks/keypoints |
| YOLO YAML and labels | Import wizard or `Table.from_yolo_url` | Task, split paths, normalised coordinates and class order |
| Semantic class-ID PNGs | Semantic manifest or `Table.from_semantic_masks` | Pixel IDs, ignore value and mask dimensions |
| Pascal VOC, KITTI, detection CSV, CVAT for images, Label Studio | Recognised exchange layouts in the import wizard | Which annotation fields the source layout can represent |
| Folder per class | Classification import or `Table.from_image_folder` | Each directory becomes a class; inspect names before training |
| CSV, Parquet, pandas or column dictionaries | [Python tables](/docs/python/tables) | Explicit types, labels and sample identity |

A format name alone does not guarantee every variant is supported. In particular, detection-oriented
exchange formats cannot represent every mask, pose or rotated-box property. Keep the original source
when converting and inspect several complex examples before using the result.

## Import a vision dataset

1. Open **Create project** or **Add data** and choose the task and source.
2. Read preflight findings. Resolve blocking issues and make each offered repair choice deliberately.
3. Confirm train, validation and test assignments. Related frames or augmented copies should not leak
   across evaluation and training sets.
4. Commit the import. Open Images and check labels, class names, dimensions and split counts.
5. Keep the saved import report with the project. Continue with [Health](/docs/explore/health).

## Preserve the geometry

YOLO supports explicit `detect`, `segment`, `pose` and `obb` tasks. Do not interpret an eight-coordinate
rotated box as an ordinary detection line. Polygon export can approximate bitmap masks; use COCO RLE
or native semantic PNG export for exact mask pixels. See [masks](/docs/data/masks),
[keypoints](/docs/data/keypoints) and [boxes](/docs/data/boxes).

## Formats needing preparation

Direct video extraction, point-cloud imports and arbitrary dataset-specific downloaders are
**Not yet included**. Prepare supported images/labels externally or use the reserved
[video](/docs/data/video) and [spatial](/docs/planned/spatial) sections to check the intended scope.
