---
title: Manage projects
summary: Rename, delete, back up and move projects; keep several without losing track.
---

## The Projects screen

Every project on the machine, as cards or a list: a mosaic of its images, its type and sets, counts of
images, objects, classes and dataset versions, how much of it is verified, and the status of its last
run. Search by name, sort by most recent, name or size. The view you choose is remembered.

## Rename

The pencil on a project's card, or beside its name on Overview. Names may use letters, numbers, spaces,
dots, dashes and underscores, and must not clash with another project.

Renaming rewrites every reference inside the project — dataset versions and their history, runs and their
metrics, reviews, comments, isolated images — so nothing is orphaned. Image files are never touched. The
whole rewrite is planned before anything moves and rolled back if any part fails. A project cannot be
renamed while it is training.

## Delete

The trash on the card, with a typed confirmation of the project's name. It removes the project folder and
the training runs and exports that belonged to it. Images on disk are not touched, because Granum never
owned them.

There is no undo. If the project might matter later, copy its folder first — it is self-contained.

## Back up

```bash
cp -a ~/granum /backup/granum-$(date +%F)          # projects, versions, reviews, runs
cp -a ~/granum-training /backup/weights-$(date +%F) # model weights (large; optional)
```

`~/granum` is the one that matters: it holds every dataset version, review decision and metric. Weights
can be retrained; review decisions cannot be recovered.

Restoring is a copy back. Granum reads whatever is in the project root at startup.

!!! warning "Project folders refer to images by absolute path"
    A project records where its images are on this machine. Copying a project folder to a different
    machine works when the images are at the same paths there; otherwise the images will not resolve.
    Moving a whole `~/granum` to the same location on a new machine is the reliable route.

## Moving the project root

```bash
granum config project-root /data/granum   # then restart the service
```

The root can also be an fsspec URL (`s3://`, `gs://`, `az://`) with the matching extra installed, though
everything is faster on a local disk.

## Several projects at once

One service, one port, one project root: all your projects live side by side and the sidebar switches
between them. There is no per-project isolation and no permissions — anyone who can reach the service can
open any project on it. For separate work that must stay separate, use separate machines or separate user
accounts.

Plans count projects. Example projects created from the built-in dataset carry a marker and do not count
towards the limit; adding real data to one removes the marker.
