---
title: Browse images
summary: Filters, ordering, annotations, and the full-screen viewer with per-class isolation.
---

**Images** is where a dataset is actually looked at. It opens on the dataset's images with their
annotations, and nothing you do here writes anything — filtering, sorting and opening images are free.

## The ribbon

| Control | What it does |
|---|---|
| **Split chips** | `train`, `valid`, `test`, plus `isolated` when images are set aside. Click to switch |
| **Classes** | Show only images containing the classes you tick |
| **Status** | All, Verified, Unverified. A corner dot marks rework or comments |
| **Order by** | Filename, last updated or date added, ascending or descending |
| **Annotations** | Draw the boxes on the cards, or hide them to judge the images themselves |
| **See in list** | Swap the grid for a table: file, split, objects, classes, status, updated |
| **Review**, **Edit** | The two other modes of this screen |
| **Create dataset** | Freeze what you see into a [dataset version](/docs/guides/dataset-versions) |
| **Removed** | The images taken out of this dataset, and the way back |

Filtering and ordering happen in the browser over one payload, so they are instant even on tens of
thousands of images. Box geometry is far bigger, so it is fetched a screenful at a time as you scroll —
which is why boxes appear a moment after the images on a fast scroll.

## Reading a grid quickly

The card shows the image, its boxes coloured per class, the number of labelled objects, and small marks
for its state: a tick for verified, a dot for rework or a comment thread, a tag for images that came from
another set.

Three habits find most problems in a few minutes:

1. **Sort by object count** (in list view) and look at both ends. Images with 400 boxes and images with
   zero are where conventions break.
2. **Filter to one class** and scroll. Inconsistent labelling of a single class is obvious in a grid and
   invisible one image at a time.
3. **Turn annotations off, then on.** Off, you see what the images are. On, you see what someone claimed
   about them.

## The full-screen viewer

Click any card. The image fills the screen, with its labels drawn on it.

- **Classes used in this image** are listed beside it. Click one and everything else darkens: only that
  class's boxes stay lit. This is the fastest way to check whether a class is labelled consistently.
- **Instances** lists every object; clicking one lights that box alone.
- <kbd>←</kbd> <kbd>→</kbd> move to the next image, <kbd>Esc</kbd> closes.
- <kbd>C</kbd> adds a comment. Commenting sets the image back to unverified, because a comment means
  something needs another look.
- **Edit** opens the same image in the [editor](/docs/guides/edit).

There is no Verify button here on purpose: verifying is a review action, and review is its own mode with
a reviewer name, progress and bulk decisions. → [Review and verify](/docs/guides/review)
