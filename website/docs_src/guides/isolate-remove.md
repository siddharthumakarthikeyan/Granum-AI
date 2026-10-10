---
title: Isolate, remove and restore
summary: Set images aside, take them out of a set, and put them back.
---

Two different problems, two different answers.

## Isolate: not now

Isolating moves images into the dataset's **isolated** set. Use it when a few images are blocking you —
a client has to decide whether a reflection counts as a person, an image may be a privacy problem, a
frame is too ambiguous to label today.

- Isolated images stay out of new dataset versions, so the rest of the work continues.
- They keep their status, comments and labels, and can still be reviewed and edited.
- They appear as an `isolated` chip beside the splits in the Images ribbon.
- **Return to set** puts each back into the newest version of the set it came from.

Isolating and returning each write a new version of the sets involved.

## Delete: not this

Deleting moves images into the dataset's **removed** set, after a confirmation, with an optional reason.
They leave the working sets and every future version.

Nothing is destroyed. The file on disk is not touched, earlier versions still contain the image, and the
removed set records where each image came from and why.

Use it for images that should not be in the dataset at all: duplicates, corrupt files, photographs from
the wrong site, images a customer has asked you to drop.

## Restoring

The **Removed** button in the Images header opens the removed set: each image with the set it came from,
the reason, and when. Select images and **Restore** to put them back into the newest version of their
original set. They return unverified.

## Which to use

| Situation | Use |
|---|---|
| Waiting on a decision | Isolate |
| Genuinely ambiguous, may come back | Isolate |
| Duplicate, corrupt, wrong dataset | Delete |
| Customer asked for removal | Delete |
| Image is fine but the labels are wrong | Neither — fix the labels |

!!! warning "Removing images changes row positions"
    Both operations write a new version in which rows have moved. Per-image metrics from an earlier run
    stay attached to the version they were collected on — Granum will not join them forward across a row
    change. Your existing runs keep working and keep showing the right images; they simply show the data
    as it was. → [Image identity](/docs/concepts/identity)
