---
title: Import checks
summary: Every preflight check, what it means, and which option to choose.
---

Every finding carries a severity, the counts per set behind it, example images with the boxes in
question, and options with a default. Nothing is written until you accept them.

## Blocking

The import cannot proceed until these are resolved.

| Code | What it found | Usually |
|---|---|---|
| `coco.unreadable` | The annotation file cannot be parsed | Fix the export; this is not a Granum problem |
| `categories.conflict` | Category ids that disagree between sets | Remap to one id per class name |
| `annotations.orphan` | Boxes on images that are not listed | Drop the boxes |
| `annotations.unknown_category` | Boxes with a category that does not exist | Drop the boxes |
| `annotations.invalid_bbox` | Malformed boxes: negative sizes, non-numbers | Drop the boxes |
| `images.malformed` | Image records missing a file name or size | Drop the images |
| `images.duplicate_id` | The same image id used twice | Renumber |
| `media.missing` | The image file is not on disk | Drop the images, or fix the path and re-run |
| `media.unreadable` | The file exists but cannot be decoded | Drop the images |

## Warnings

Real problems with a sensible default. Read them.

| Code | What it found | Why it matters |
|---|---|---|
| `categories.ignore_region` | An "ignore region" category exported as a normal class | Treated as a class, every correct prediction inside one is punished. Convert to crowd, or drop |
| `categories.duplicate_name` | Different ids sharing a name | Two classes the model cannot tell apart |
| `annotations.zero_area` | Boxes with no width or height | They train nothing and distort metrics |
| `annotations.out_of_bounds` | Boxes outside the image | Usually a coordinate-system mistake |
| `annotations.duplicate_id` | Repeated annotation ids | Breaks any external join on those ids |
| `media.size_mismatch` | The file's size differs from the annotation's | Coordinates will be wrong by a scale factor |
| `media.identical_files` | Byte-identical images, including across sets | Leakage, if the copies straddle a split |
| `images.export_copies` | Augmented export copies of one source image | Leakage in the same way, harder to see |
| `split.shared_source` | One source image appearing in two splits | Validation scores will be optimistic |
| `split.shared_sequence` | One capture sequence appearing in two splits | The same, via near-duplicate frames |

## Information

Context to accept knowingly.

| Code | What it found |
|---|---|
| `categories.unused` | Classes with no boxes anywhere |
| `categories.catch_all` | A catch-all class such as "object" or "other" |
| `images.unannotated` | Images with no boxes — deliberate negatives, or unlabelled? |
| `annotations.tiny` | Boxes under 8 px, which most detectors cannot learn at normal resolution |
| `images.crowded` | Images with very many boxes |

## Grouping options

Several checks offer to add grouping columns — `source_image`, `sequence`, `content_hash` — rather than
changing anything. Related images can then be reviewed together and, more importantly, split together.

## Reading a report later

Every report is kept: `<project>/imports/<id>.json`, linked from **Overview → Attention** and from each
set. It holds what was found, what you chose and how many images or boxes each choice affected.

!!! tip "The two minutes that pay for themselves"
    `media.identical_files`, `images.export_copies`, `split.shared_source` and `split.shared_sequence`
    are the checks that most often change a project's conclusions. A validation score inflated by
    leakage looks exactly like a good model until it reaches production.
