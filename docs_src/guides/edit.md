---
title: Edit annotations
summary: Draw, move, relabel and delete boxes, masks and keypoints — and what each save writes.
---

Turn on **Edit** in the Images ribbon and open an image. The editor fills the screen: the image with its
objects, a toolbar, and a panel with the selected object's class and properties.

## Tools

Which tools appear follows the project's [type](/docs/concepts/projects).

| Tool | Key | What it does |
|---|---|---|
| **Select** | <kbd>V</kbd> | Click an object to select it. Drag it to move, drag a handle to resize, drag a vertex or keypoint to move that point |
| **Box** | <kbd>B</kbd> | Drag on the image to draw a box |
| **Polygon** | <kbd>P</kbd> | Click points to trace a mask; <kbd>Enter</kbd> closes it. Double-click an edge to add a vertex |
| **Keypoint** | <kbd>K</kbd> | Click to add points to the selected object; with nothing selected, starts a new one |
| **Image label** | — | For classification projects: one label for the whole image |

Detection projects get Box. Segmentation projects get Polygon. Keypoint projects get Keypoint, and a box
is fitted around the points automatically when the project has no box tool. Classification projects get
no drawing tools at all, only the image label.

## Moving around

| Action | How |
|---|---|
| Zoom | Wheel |
| Pan | Drag empty space |
| Fit the image | <kbd>0</kbd> |
| Previous / next image | <kbd>←</kbd> <kbd>→</kbd> — saves first |
| Undo / redo | <kbd>Ctrl</kbd>+<kbd>Z</kbd> / <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd> (or <kbd>Ctrl</kbd>+<kbd>Y</kbd>) |
| Save | <kbd>Ctrl</kbd>+<kbd>S</kbd>, and automatically when you leave the image |
| Delete | <kbd>Delete</kbd> removes the picked vertex or keypoint, otherwise the whole object |

## Classes

The selected object's class is in the side panel; pick another to relabel it. **+ Class** adds a new
class to the dataset — available immediately on every set in it, because the class list belongs to the
dataset rather than to one image.

A class that is still in use cannot be removed, which is deliberate: silently dropping a class would
change the meaning of every box that referred to it.

## Crowd and ignore regions

Each object has a **crowd** toggle. A crowd object — COCO's `iscrowd`, or an "ignored region" in
aerial datasets — is neither rewarded nor penalised: it is never matched, never counted as missed, and
predictions lying mostly inside it are ignored rather than counted as false positives.

Use it for regions you have deliberately not labelled individually. Getting this wrong is a common source
of mysteriously bad precision: a dense crowd exported as one ordinary box means every correct person the
model finds inside it counts against it.

## What a save writes

One save writes **one new version of that set**, however many objects you changed, and sets the image
back to **unverified** with a note saying what changed. The previous version is untouched.

That is why the editor saves per image rather than per box: a session correcting forty images writes
forty versions, not four hundred. If you are making a large sweep of edits, expect the version list to
grow; it is the record of who changed what.

!!! note "Unsaved work is recoverable"
    Edits live in the browser until they are saved, and are kept in local storage as you make them. If
    the window closes with unsaved changes, Granum offers them back when you return to that image.
