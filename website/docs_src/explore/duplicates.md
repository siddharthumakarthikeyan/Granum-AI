---
title: Find duplicates leakage and outliers
summary: Review near-identical pictures, split leakage and unusual samples before trusting an evaluation.
status: available
---

Open **Images → Duplicates** to examine redundancy and related images across splits. Granum builds
image descriptors and a neighbour graph. With training support it can use a learned descriptor;
otherwise a colour-and-edge descriptor is a more limited signal. Read the descriptor shown by the
result before interpreting similarity.

## Run the inspection

1. Choose the dataset and ask Granum to read the images if descriptors are not present.
2. Inspect Repeats for groups that may represent the same picture.
3. Inspect Exported copies for known augmentation families and copies split across sets.
4. Inspect Leaks for related pictures in training and evaluation.
5. Inspect Outliers for samples with few close neighbours.

Granum uses available provenance to distinguish an exported or augmented copy from a separately
captured picture. Keep source names and augmentation metadata during conversion so this evidence
survives. Similarity alone cannot always make that distinction.

## Make a decision

Open representative images in a group. A sequence of similar frames can be a useful continuum, and a
rare outlier can be exactly the case your model must learn. Select the specific images to move or
remove only after checking their role in the task.

Removal uses the same recoverable curation path as the rest of Images. Review the selection, confirm
the action, then check **Removed** if you need to restore it. Create a new dataset version before
training so the selection is recorded.

## Find neighbours of one image

Use **Find images like this** from an image to order neighbours around that example. Existing split
and metadata filters can narrow the result. **Order by → Uniqueness** ranks unusual images for
inspection; a high score is a prompt to look, not a quality verdict.

## Check the consequence

Revisit [Health](/docs/explore/health) and split counts after curation. Hold related captures together
when redesigning splits. Once training has seen an evaluation image or a close copy, simply removing
that evaluation row cannot erase the information already learned by the model; design the next
baseline on the corrected split.
