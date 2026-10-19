---
title: Upgrade and migrate safely
summary: Keep a recoverable workspace while changing Granum builds, dependencies or storage locations.
status: partial
---

An upgrade changes the program reading and writing your project records. Record the old and new
build identities, retain the prior artifact and verify the candidate against a restored workspace
before replacing your working installation.

## Rehearse the upgrade

1. Finish or deliberately stop writers and model jobs. Confirm their final status.
2. Create a [portable backup](/docs/course/backup) and keep any external resources it does not contain.
3. Restore into a different project root using the candidate build.
4. Inspect images, labels, reviews, dataset versions, runs and weight references.
5. Exercise one edit/save/reopen and the intended approval/training path.
6. Keep the original workspace and application artifact until the new environment is accepted.

Do not point an older build at the only workspace already modified by a newer build and assume it
will understand every format. Unsupported future object formats are explicitly refused.

## Move a workspace

Changing `project-root-url` selects another root; it does not copy or rewrite project records.
Use the supported backup/restore path for portable local moves. URL aliases can relocate logical
media roots, but the actual bytes must still be present and accessible.

Compare integrity manifests after a move. Browser recovery drafts and saved workflow preferences
belong to the browser profile/origin and do not automatically move with the server's project directory.
Export the drafts and workflow JSON you need separately.

## Dependency changes

Pin the model environment as well as Granum. Framework versions, CUDA runtime, model weights and
preprocessing can affect outputs even when the dataset is unchanged. A package version of `0.1.0`
alone is not enough to identify a development build; retain the source revision/build manifest.

## Not yet included

A universal automatic schema migrator, migration tool for another product's native object format,
and a complete historical version-to-version compatibility matrix are not yet included. Exchange
supported datasets through [COCO, YOLO or other formats](/docs/data/formats), then recheck labels and
splits. Product-specific history and metrics require an explicit conversion contract.

Read [release information](/docs/reference/releases) and current [feature availability](/docs/reference/features)
when choosing a candidate build.
