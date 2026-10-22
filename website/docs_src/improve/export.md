---
title: Export a dataset version
summary: Choose a target annotation format and media strategy, then verify the exported data.
status: available
---

Export a frozen dataset version when handing data to another tool or team. This keeps the export tied
to the same revisions even if labels are edited later in the working dataset.

## Export from Datasets

1. Open the intended dataset version and choose **Export**.
2. Select the format and task variant supported by the receiving tool.
3. Choose how image files should be included.
4. Start the export and inspect the reported destination and outcome.
5. Open the result in the receiving tool or reimport a small selection into a separate project.

The normal destination is under the project's `exports` folder. Check available disk space when
copying images. An export writes dataset files; it is not a backup of reviews, runs, settings and
all project history.

## Choose the format

The interface offers COCO, YOLO, semantic PNG masks, Pascal VOC, KITTI, detection CSV, CVAT for images,
Label Studio tasks and folder-per-class outputs. Choose a format that can express the source task.
YOLO task variants include detection, instance segmentation, pose and oriented boxes.

Use COCO RLE or semantic PNGs for exact mask pixels. Polygon conversion can approximate masks.
Draft source/confidence is preserved where the chosen format has room for it; recheck downstream
behaviour rather than assuming every consumer reads those fields.

## Choose the media strategy

| Strategy | Result |
|---|---|
| Copy | A separate image copy travels with the export |
| Symbolic link | Minimal extra storage; still depends on the original target path |
| Hard link | Shares bytes on the same filesystem; cannot cross drives |
| Labels only | Annotation files reference existing images; unavailable for layouts requiring images |

Moving linked exports to another machine can break them. A hard link also does not protect against
external modification of the shared bytes. Choose copied media for an independent handoff.

## Python export

```python
import granum

granum.export_yolo({"train": train_table, "val": valid_table}, "out/yolo",
                   image_strategy="copy", task="detect")
```

Here `train_table` and `valid_table` are the exact loaded revisions. YOLO export remaps class IDs to its
contiguous class convention and excludes zero-weight rows. Inspect counts, class names, image hashes
and a few difficult annotations after export. For full workspace recovery, use
[backup and restore](/docs/course/backup).
