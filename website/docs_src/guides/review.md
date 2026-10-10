---
title: Review and verify
summary: Work through a dataset image by image or in bulk, with comments, rework and a progress bar.
---

Review is a mode of the Images screen, not a separate place: turn on **Review** in the ribbon and the
same grid becomes selectable, with a review bar above it and a decision tray below.

## Set up

Type your name in the **Reviewer** box. It is remembered in this browser and attached to every decision
and comment you make. There is no login; the name is a record among colleagues, not a credential.

## Working in bulk

Tick images and act on all of them at once. <kbd>Shift</kbd>-click selects a range. **Select shown**
takes the images loaded on the page; **Select all** takes everything matching the current filters,
including images not yet loaded.

The tray offers:

| Decision | What it does |
|---|---|
| **Verify** | The labels are right |
| **Unverify** | Back to unverified, e.g. after fixing something |
| **Rework…** | Asks for a note saying what is wrong, and records it |
| **Isolate…** | Sets the images aside, out of new dataset versions, until returned |
| **Return to set** | Puts isolated images back where they came from |
| **Delete…** | Moves them to the removed set, recoverable |

The progress bar counts verified images against the total for the current filters, so the number moves as
you work.

## Working one image at a time

Click an image to open the inspector: the picture with its boxes on the left, the decision buttons,
class counts and the comment thread on the right.

| Key | Action |
|---|---|
| <kbd>←</kbd> <kbd>→</kbd> | Previous / next image, saving any box edits first |
| <kbd>A</kbd> | Verify and move to the next image |
| <kbd>R</kbd> | Rework — write the reason in the comment box first |
| <kbd>U</kbd> | Back to unverified |
| <kbd>I</kbd> | Isolate |
| <kbd>B</kbd> | Show or hide boxes |
| <kbd>Delete</kbd> | Delete the selected box |
| <kbd>Ctrl</kbd>+<kbd>S</kbd> | Save box edits |
| <kbd>Ctrl</kbd>+<kbd>Enter</kbd> | Post the comment |
| <kbd>Esc</kbd> | Deselect the box, then close |

Boxes can be fixed here: drag on the image to draw one, click to select, <kbd>Delete</kbd> to remove.
Anything more — moving, resizing, masks, keypoints, new classes — belongs in the
[editor](/docs/guides/edit), which the inspector links to.

## The rework loop

Rework is how a reviewer hands an image back without losing the thread:

1. The reviewer marks the image **Rework** with a note: *"two pedestrians at the crossing are
   unlabelled"*.
2. The annotator filters to rework, reads the note, fixes the boxes, replies *"added both"*, and the
   image returns to **unverified**.
3. The reviewer checks it again and verifies.

Every step is appended to the image's thread with a name and a time, and nothing is overwritten, so the
history of an image is always readable.

## How much to review

You do not have to review everything before training, and usually should not. A sensible first pass:

- Verify the validation set properly. Every conclusion you draw later rests on it.
- Skim the training set for convention breaks rather than checking each image.
- Train, then let [Findings](/docs/guides/findings) tell you where in the training set to spend the rest
  of the effort.

That ordering matters: reviewing 11,000 training images by hand before the first run is weeks of work,
and the model can tell you which few hundred of them are worth your time.
