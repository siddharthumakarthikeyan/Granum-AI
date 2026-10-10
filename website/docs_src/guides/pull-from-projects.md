---
title: Build from existing projects
summary: Pick classes out of projects you already have and make a new dataset from them.
---

Once you have a few projects, the next dataset is often already on the machine: every *person* you have
ever labelled, across three contracts, as one detector. **Create project → Import from existing
projects** builds that without exporting and re-importing by hand.

## Choosing what to pull

The dialog has two lists.

**Classes in all projects** (right) is the combined class list, matched by name regardless of case, with
the number of projects and images behind each. Ticking `person` takes that class from every project that
has one. A partly-ticked box means some projects contribute it and others do not.

**By project** (left) is the same data the other way round. Expand a project to tick classes from that
one project, or tick the project itself to take **everything in it** — every image, including images with
no labels at all.

You can mix: all `person` everywhere, plus everything from one small project.

## What you get

- Only the classes you picked, unless you tick **keep other labels**, which keeps the rest of each
  image's annotations as well.
- Images deduplicated by path, so an image that appears in two projects arrives once.
- The splits of each source project preserved, then re-cuttable on the review step like any other import.

The pull writes COCO files into a scratch folder inside your project root and then sends them through the
normal preflight, so the same checks apply — including the leakage checks, which matter more here than
usual: two projects that both contain a customer's photos will share images, and you want to know before
those land on both sides of a split.

!!! note "Class names are the join"
    Classes are matched by name, case-insensitively. `Person`, `person` and `PERSON` become one class;
    `pedestrian` does not join them. If your projects disagree about names, rename the class in the
    editor first — it is one edit per project — or pull them separately and merge the class list
    afterwards.
