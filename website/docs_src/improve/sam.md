---
title: Propose masks with SAM
summary: Guide segmentation with points or an object box, then inspect and apply the proposed mask.
status: partial
---

SAM assistance creates a mask proposal for the image you are editing. It needs training support with
PyTorch and Ultralytics, plus the selected model's weights. A proposal does not become a saved
annotation until you apply it and save the edit.

## Make a proposal

1. Open a segmentation image in Edit mode and select the object or class you intend to change.
2. Choose a model in the SAM panel. The catalogue includes MobileSAM and SAM 2.1 variants.
3. Provide a bounding box or foreground point. Add background points where you need to exclude pixels.
4. Choose **Propose mask** and wait for the job to complete.
5. Inspect the overlay, especially holes, touching objects and fine boundaries.
6. Apply a satisfactory proposal, refine it with Paint or Erase if needed, then save the image.

Prompt coordinates must lie within the original image. The interactive service accepts up to 128
points and images with known dimensions up to 25 million pixels. It checks that the selected image
belongs to the requested table and dataset.

## Change a proposal

If the mask is wrong, adjust prompts and generate another proposal. Do not apply an old result to a
different object or changed prompt set. Keep the model job's error or status visible until you know
whether it completed; inspect the job log if weights, dependencies or resources are unavailable.

For semantic labels, check class exclusivity after applying a mask. A pixel must not end up assigned
to conflicting classes. The editor's task behaviour matters when replacing or merging a proposal.

## Save and review

A confirmed editor save creates a new revision and invalidates review evidence for changed contents.
Reopen the image and confirm the stored mask before marking it reviewed. Browser recovery helps with
unfinished edits, but the saved revision is the durable result; follow any recovery warning shown by
the editor.

MobileSAM and SAM 2.1 tiny have development CPU inference evidence. Larger variants, GPUs and your
image sizes need their own qualification. Dataset-wide automatic SAM labelling and a dedicated SAM
embedding recipe are **Not yet included**; see [planned compute](/docs/planned/compute).
