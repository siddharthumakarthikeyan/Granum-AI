---
title: Keypoints and pose
summary: Preserve landmark order, visibility and identity through import, editing, augmentation and evaluation.
status: partial
---

Keypoints describe named positions on an object. Their order is part of the label contract: left eye
and right eye must keep the same meaning through data loading, horizontal flips and prediction.

## Import and inspect

Use COCO keypoints or `Table.from_yolo_url(..., task="pose")`. Keep skeleton definitions, keypoint
names, visibility and any left/right flip mapping with the dataset. A model expecting a different
number or order of points cannot be compared directly with those labels.

Open Images in Edit mode. Select the object, use the Keypoint tool to add or adjust points, and check
the selected point's visibility. An unlabelled point is different from an occluded point with a known
position. Clearing a landmark must retain the layout expected by the model.

## Analyse individual landmarks

In a table or run workspace containing keypoint metadata, open **Landmarks**. Choose the landmark
slot and inspect its observations. Per-object properties such as `keypoint_0_oks` and
`keypoint_0_confidence` can be used in numeric filters and charts when predictions were collected.

A missing score is not zero. Unlabelled ground-truth landmarks have no score; filtering to a low
score must not silently include them as failures. Mixed class-specific landmark layouts require
care when interpreting a slot index. Automatic name display across all mixed layouts remains
**Not yet included**.

## Train and export

YOLO pose training, predictions and export use `task="pose"`. Matching uses Object Keypoint Similarity
(OKS), with object scale and the supplied keypoint tolerance configuration. Inspect the prediction
coordinate frame before comparing it to the original image.

Horizontal pose augmentation requires declared `flip_idx` metadata to swap left/right landmarks.
If it is absent, do not enable that transform as though it preserved labels. Start with one example,
inspect every transformed point, then create the [augmented dataset version](/docs/guides/augmentation).

Export a small pose dataset and reimport it to check landmark count, class mapping and visibility.
[Sample metrics](/docs/measure/metrics) and [Ultralytics integration](/docs/integrations/ultralytics)
explain how to attach observations to the right images across epochs.
