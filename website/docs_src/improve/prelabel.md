---
title: Draft labels with a model
summary: Generate annotation suggestions, preserve their provenance and review them before approving a dataset.
status: available
---

Pre-labelling turns a model's predictions into draft annotations for human correction. Use it to
reduce repetitive drawing when the model understands the classes you need. A confident prediction
is still a suggestion.

## Prepare the request

Open **Images → Pre-label** and choose the sets to process. Select a compatible project model or a
supported pretrained model. Check the task and class mapping: a general pretrained model may know
only some of your dataset's classes.

Choose the confidence threshold based on the amount of correction you can review. A higher threshold
usually creates fewer suggestions but can omit real objects. A lower threshold creates more drafts
that may need deletion.

## Choose what may change

**Leave them alone** preserves already labelled images and drafts labels on empty ones. **Redraw them**
replaces existing annotations with the model's proposals in the new version. Read this choice before
starting a large job.

The job writes new set revisions. Source revisions remain available. Draft annotations carry their
source and confidence where supported; existing manual annotations retain their distinct provenance.
The dashboard marks draft geometry so it can be distinguished during review.

## Review and save

1. Wait for job completion and inspect any reported errors or unsupported classes.
2. Open a representative mix of easy, crowded, small-object and empty images.
3. Correct classes, geometry and missing objects in the editor.
4. Save each change and record the human review result.
5. Check draft counts and [Health](/docs/explore/health) before creating a dataset version.

If results are unsuitable, continue from the earlier revision rather than treating the draft as
verified data. [Findings](/docs/guides/findings) can help prioritise disagreements but do not replace
the review.

## Preconditions

The model environment and weights must be available to the service. Another model job may occupy
the worker; finish or cancel it before starting a conflicting request. Use [SAM](/docs/improve/sam)
for interactive mask proposals. Fully automatic dataset-wide segmentation and an active-labelling
scheduler are [Not yet included](/docs/planned/compute#automatic-labelling-pipelines).
