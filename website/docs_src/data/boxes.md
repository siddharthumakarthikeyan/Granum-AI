---
title: Bounding boxes and rotated boxes
summary: Import, edit and measure ordinary detection boxes and oriented object annotations.
status: available
---

Boxes identify object extent and class within an image. Ordinary boxes align with image axes;
oriented boxes retain four rotated corners. Choose the task before import so coordinate interpretation,
editing tools and evaluation agree.

## Ordinary detection boxes

A stored geometry value has image `width`, `height` and an `instances` list. Each ordinary box uses
`vertices: [x_min, y_min, x_max, y_max]` in source-image pixels and a numeric `label`. COCO's
`[x, y, width, height]` and YOLO's normalised coordinates are converted by the importers.

1. Import a COCO or YOLO detection dataset.
2. Open **Images → Edit** and select an image.
3. Choose Box to draw, or Select to move and resize an existing object.
4. Check the selected class, crowd flag and any draft provenance.
5. Save, then review the image again. Editing invalidates review evidence for the changed contents.

`granum.BoundingBoxes2D`, `box_iou`, `match_boxes` and `nms` support Python detection workflows.
Custom instance properties must be declared in the schema; see [schemas](/docs/python/schemas).

## Oriented boxes

Use the oriented-box task and a YOLO OBB dataset. The editor supports creating and adjusting rotated
rectangles, including rotation and resizing within image bounds. Inspect all four corners after a
change, especially near the edge of an image. The enclosing axis-aligned rectangle alone does not
retain the object's orientation.

Export using `export_yolo(..., task="obb")`. Out-of-range normalised coordinates are rejected. The
YOLO adapter and task-aware metrics use rotated overlap for OBB matching. A detector evaluated with
ordinary enclosing-box overlap answers a different question.

## Measure and export

Use [Evaluation](/docs/explore/evaluation) to inspect true positives, false positives and missed labels.
A class disagreement may appear differently in a confusion matrix and in class-aware scoring.
For a round trip, export a small version and import it into a separate project; compare class maps,
image references and geometry before exporting the entire collection.

Three-dimensional cuboids are **Not yet included**; see [spatial data](/docs/planned/spatial).
