---
title: Instance and semantic masks
summary: Import mask labels, correct pixels and choose an export that preserves the information you need.
status: partial
---

Instance segmentation gives each object its own mask. Semantic segmentation assigns each pixel a
class, with an optional ignore value. Treat these as different tasks even when both are drawn as
coloured overlays.

## Import masks

COCO supports polygon and run-length encoded instance masks. YOLO segmentation uses polygons. Native
semantic import uses lossless PNG masks and a `semantic.json` manifest. This minimal manifest names
one image, its mask and the class IDs stored in that mask:

```json
{
  "format": "granum-semantic-masks",
  "version": 1,
  "ignore_index": 255,
  "categories": [{"id": 0, "name": "background"}, {"id": 1, "name": "part"}],
  "images": [{"file_name": "images/sample.png", "mask": "masks/sample.png"}]
}
```

Paths resolve relative to the manifest unless an explicit image root is supplied. Mask dimensions
must match the source image. Class IDs and the ignore value must be distinct, valid integers; RGB
mask inputs need an explicit colour mapping. See the [Python API](/docs/python/api).

## Correct a mask

1. Open an image in Edit mode and select the intended object or semantic class.
2. Use Polygon for outlines, Paint for pixel additions, and Erase for pixel removal.
3. Adjust brush diameter and inspect boundaries at a useful zoom level.
4. In semantic work, confirm that painting one class has not left overlapping class regions.
5. Save and reopen the image to verify the stored result. Re-review the changed image.

[SAM assistance](/docs/improve/sam) can propose a mask from points or a box. Inspect the proposal
before applying it; it remains a model suggestion until reviewed.

## Export and measure

COCO RLE and native semantic PNGs preserve exact mask pixels. YOLO polygon conversion can change
fine edges, holes or disconnected shapes. Semantic PNG export rejects conflicting class overlaps
and writes the class/ignore metadata with the masks.

Instance metrics use mask IoU. `SemanticMetricsCollector` accepts original-resolution class-ID maps
and records pixel accuracy, per-class intersections/unions and IoU. Ignored pixels do not contribute;
a class absent from the relevant data has no IoU, rather than a perfect one.

## Training boundary

YOLO instance-segmentation training and prediction collection are included. The development branch
also includes a Torchvision LR-ASPP semantic-training path, with broader workflow qualification
still in progress. Follow [training tasks](/docs/measure/tasks) for its input requirements. Connect
other semantic architectures through the [custom metrics contract](/docs/python/custom-metrics).
