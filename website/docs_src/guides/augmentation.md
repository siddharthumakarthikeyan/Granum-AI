---
title: Augmentation
summary: Generate augmented copies into a dataset version, and see exactly what the model will see.
---

Granum augments by **generating images into the dataset version**, not by transforming batches during
training. That costs disk and a few minutes; it buys two things:

- you can look at exactly what the model will be trained on, image by image;
- a run's input is a fixed set of files rather than a recipe plus a seed, so two runs on the same version
  saw the same pictures.

Only the **train** set is augmented. Validation and test sets are left alone, because augmenting what you
measure with makes the measurement meaningless.

## Building a recipe

In the Create dataset dialog, choose **Yes**, then how many augmented copies of each image to make
(1–5×). Below that is a grid of cards, one per operation, each showing that operation applied to a real
image from your own train set. Click a card to open its settings: the original, the minimum and the
maximum of the range, with the controls between them. **Add** puts it in the recipe.

| Group | Operations |
|---|---|
| **Geometry** | Flip (horizontal, vertical), 90° rotate, Crop, Rotation, Shear |
| **Colour and noise** | Grayscale, Hue, Saturation, Brightness, Exposure, Blur, Noise, Cutout |

Each copy draws each operation's value independently within its range, so a recipe of ±15° rotation and
±20% brightness gives copies that vary in both.

## What happens to the labels

Geometric operations are composed into a single transform and applied to the image and to everything on
it — boxes, mask polygons and keypoints together — so annotations stay attached to the pixels they
describe.

Two rules are worth knowing before you pick a range:

- **Boxes that end up less than 15% visible are dropped.** Heavy crops and large rotations therefore
  remove objects at the edges. The dataset version records how many were dropped, per set.
- **Run-length masks cannot be transformed and are dropped under geometry.** Polygon masks are
  transformed and clipped normally.

!!! warning "Flips and left/right keypoints"
    A horizontal flip mirrors keypoints but does not rename them, so a "left wrist" stays "left wrist"
    on what is now the right side. For keypoint projects with sided names, avoid horizontal flip until
    Granum swaps the pairs. The dialog says so where it matters.

## What it costs

The dialog estimates the disk the generated images will take before you commit. As a rough guide, 2×
copies of an 11,000-image set is 22,000 new JPEGs — a few gigabytes.

The version records, per set, how many originals, how many augmented copies, and how many boxes and masks
were dropped, and the Datasets screen shows the recipe, so nobody has to guess later what "v3 —
augmented" contained.

## When to use it

Augmentation is a way to make a small dataset go further, not a fix for a bad one. If Findings says 200
of your labels are wrong, augmenting produces five copies of each wrong label. Fix the data first, then
augment the version you trust.
