/** Everyday-language wording for the parts of Granum that are technical underneath.
 *
 * The service describes findings precisely, for engineers and for the saved record. This
 * file says the same things for someone who labels or manages data but does not train
 * models: what happened, why it matters, and what we suggest. The service's own wording
 * stays available under "Technical details".
 */

export interface FindingCopy {
  headline: string;
  meaning: string;
  recommendation: string;
}

export const FINDINGS: Record<string, FindingCopy> = {
  "coco.unreadable": {
    headline: "We couldn't read one of the label files",
    meaning: "The file is damaged, empty, or isn't a COCO label file.",
    recommendation: "Check that you picked the right file, fix it, then run the check again.",
  },
  "images.malformed": {
    headline: "Some image entries are incomplete",
    meaning: "The label file lists images without a name or number, so we can't find them.",
    recommendation: "Leave them out.",
  },
  "images.duplicate_id": {
    headline: "Two images share the same number",
    meaning: "Labels point to images by number. When two images share one, we can't tell which image a label belongs to.",
    recommendation: "Keep the first image with each number.",
  },
  "categories.conflict": {
    headline: "The label files disagree about label names",
    meaning: "The same label number means one thing in the training file and something else in another file.",
    recommendation: "This has to be fixed in the files themselves. Ask whoever exported the data, then run the check again.",
  },
  "categories.duplicate_name": {
    headline: "The same label name appears twice",
    meaning: "Two different label numbers have the same name. A model would treat them as two separate kinds of object.",
    recommendation: "Merge them into one label.",
  },
  "categories.unused": {
    headline: "A label is never used",
    meaning: "It's in the list of labels, but no object has it. Export tools often leave these behind.",
    recommendation: "Remove it from the list.",
  },
  "categories.ignore_region": {
    headline: "Some boxes mark areas to skip, not objects",
    meaning:
      "Boxes labelled like \"ignored regions\" cover places the labellers deliberately skipped, such as crowds too dense to label. " +
      "If they're treated as a normal object, the model learns to find \"skipped areas\", which is meaningless, and its scores become unreliable.",
    recommendation: "Mark them as areas to skip.",
  },
  "categories.catch_all": {
    headline: "One label collects miscellaneous objects",
    meaning: "A label such as \"others\" holds objects that don't fit anywhere else. These are often labelled inconsistently.",
    recommendation: "Nothing to do now. Look at these objects when you review the data.",
  },
  "annotations.orphan": {
    headline: "Some labels belong to images that don't exist",
    meaning: "These boxes point to an image that isn't in the label file, so there's nothing to attach them to.",
    recommendation: "Remove them.",
  },
  "annotations.unknown_category": {
    headline: "Some boxes use a label that isn't defined",
    meaning: "The box has a label number that isn't in the list of labels.",
    recommendation: "Remove them.",
  },
  "annotations.invalid_bbox": {
    headline: "Some boxes have broken positions",
    meaning: "Their position or size is missing or negative, so they can't be drawn.",
    recommendation: "Remove them.",
  },
  "annotations.zero_area": {
    headline: "Some boxes have no size",
    meaning: "A box with no width or height doesn't outline anything. It's almost always a slip of the mouse while labelling.",
    recommendation: "Remove them.",
  },
  "annotations.out_of_bounds": {
    headline: "Some boxes stick out past the edge of the image",
    meaning: "This usually happens when images are resized after labelling.",
    recommendation: "Trim them to the image edge.",
  },
  "annotations.duplicate_id": {
    headline: "Some boxes share an ID",
    meaning: "Every box needs its own ID so that a later correction can be traced back to the original label.",
    recommendation: "Give the repeats new IDs.",
  },
  "images.unannotated": {
    headline: "Some images have no labels",
    meaning:
      "Either there's genuinely nothing to label in them, which is useful for teaching the model what \"nothing here\" looks like, " +
      "or nobody got round to labelling them. The file doesn't say which.",
    recommendation: "Keep them if they really show nothing. If you're not sure, ask whoever labelled the data.",
  },
  "annotations.tiny": {
    headline: "Many objects are very small",
    meaning: "Objects under 8 pixels across are hard for a model to learn and hard for a person to check. This is normal in drone and aerial photos.",
    recommendation: "Nothing to do now. Zoom in on these when reviewing.",
  },
  "images.crowded": {
    headline: "Some images are very crowded",
    meaning: "These images have 300 or more labelled objects. Many models stop looking after 100 or 300 objects, and checking them by eye takes a long time.",
    recommendation: "Nothing to do now. Allow extra time to review them.",
  },
  "media.missing": {
    headline: "Some images are missing",
    meaning: "The label file mentions images we can't find in the folder.",
    recommendation: "Leave them out, or find the missing images and run the check again.",
  },
  "media.unreadable": {
    headline: "Some images are damaged",
    meaning: "The files exist but can't be opened as pictures.",
    recommendation: "Leave them out.",
  },
  "media.size_mismatch": {
    headline: "Some images changed size after labelling",
    meaning: "The picture is a different size from the one that was labelled, so its boxes would be drawn in the wrong place.",
    recommendation: "Leave them out.",
  },
  "media.identical_files": {
    headline: "Some images are exact copies",
    meaning: "The same picture appears more than once. If a copy is in both the training and testing sets, test scores look better than they really are.",
    recommendation: "Link the copies so you can find and fix them later.",
  },
  "images.export_copies": {
    headline: "Some images are altered copies of the same photo",
    meaning: "The export tool made extra versions of photos, such as mirror images. A labelling mistake in the original is repeated in every copy.",
    recommendation: "Link the copies so they're reviewed together.",
  },
  "split.shared_source": {
    headline: "Copies of the same photo are used for both training and testing",
    meaning: "The model is tested on pictures it has effectively already seen, so its test score looks better than it really is.",
    recommendation: "Link the copies so the sets can be separated later.",
  },
  "split.shared_sequence": {
    headline: "The test set includes scenes the model trains on",
    meaning:
      "Photos taken moments apart in the same video are divided between training and testing. They look almost identical, " +
      "so the model is tested on scenes it has effectively already seen and its score looks better than it really is. " +
      "We worked this out from the file names, so please confirm it.",
    recommendation: "Record which scene each image comes from, so the sets can be separated later.",
  },
};

/** Plain names for the options the service offers, by "code:option" or just option. */
const OPTIONS: Record<string, string> = {
  "categories.duplicate_name:merge": "Merge them into one label",
  "categories.duplicate_name:keep": "Keep them as two labels",
  "categories.unused:remove": "Remove the unused label",
  "categories.unused:keep": "Keep it in the list",
  "categories.ignore_region:mark_ignore": "Mark them as areas to skip",
  "categories.ignore_region:drop": "Delete these boxes",
  "categories.ignore_region:keep": "Treat them as a normal object",
  "annotations.out_of_bounds:clip": "Trim them to the image edge",
  "annotations.out_of_bounds:keep": "Leave them as they are",
  "annotations.out_of_bounds:drop": "Delete these boxes",
  "images.unannotated:negative": "Keep them: there's nothing to label in them",
  "images.unannotated:exclude": "Leave them out: they were never labelled",
  "media.size_mismatch:keep": "Keep them anyway",
  "annotations.duplicate_id:renumber": "Give the repeats new IDs",
  "images.duplicate_id:keep_first": "Keep the first image with each number",
  record: "Link related images",
  ignore: "Don't link them",
  drop: "Delete them",
  keep: "Keep them as they are",
  exclude: "Leave them out of the import",
};

const OPTION_EFFECTS: Record<string, string> = {
  "categories.duplicate_name:merge": "Objects with either number end up under one label.",
  "categories.duplicate_name:keep": "Both labels are imported with the same name.",
  "categories.ignore_region:mark_ignore": "The boxes stay, flagged so training and scoring can skip them.",
  "categories.ignore_region:keep": "Imported as if they were real objects.",
  "annotations.out_of_bounds:clip": "The part outside the picture is cut off. Boxes with nothing left are deleted.",
  "images.unannotated:negative": "Imported as images that contain none of the labelled objects.",
  "images.unannotated:exclude": "These images are not imported.",
  "annotations.duplicate_id:renumber": "The first box keeps its ID; later ones get new, unused IDs.",
  record: "Adds a note to each image saying which photo or scene it belongs to. Nothing is moved or deleted.",
  ignore: "Imported without that note.",
  drop: "They are not imported.",
  keep: "Imported unchanged.",
  exclude: "These images and their boxes are not imported.",
  remove: "Left out of the list of labels.",
  keep_first: "Later images with a repeated number are not imported.",
};

export function optionEffect(code: string, option: string, fallback: string): string {
  return OPTION_EFFECTS[`${code}:${option}`] ?? OPTION_EFFECTS[option] ?? fallback;
}

export function optionLabel(code: string, option: string, fallback: string): string {
  return OPTIONS[`${code}:${option}`] ?? OPTIONS[option] ?? fallback;
}

const EFFECTS: Record<string, string> = {
  categories_merged: "labels merged into another",
  categories_removed: "unused labels removed",
  boxes_marked_ignore: "boxes marked as areas to skip",
  boxes_dropped_zero_area: "boxes with no size deleted",
  boxes_dropped_ignore_region: "skip-area boxes deleted",
  boxes_dropped_out_of_bounds: "boxes past the image edge deleted",
  boxes_clipped: "boxes trimmed to the image edge",
  boxes_dropped_unknown_category: "boxes with an undefined label deleted",
  boxes_dropped_invalid: "boxes with broken positions deleted",
  boxes_dropped_removed_category: "boxes of a removed label deleted",
  boxes_remapped_category: "boxes moved to the merged label",
  images_excluded: "images left out",
  boxes_excluded_with_images: "boxes left out with those images",
  annotation_ids_renumbered: "box IDs renumbered",
};

export function effectLabel(effect: string): string {
  return EFFECTS[effect] ?? effect.replace(/_/g, " ");
}

/** What a split is for, in words that don't assume machine-learning vocabulary. */
export function splitPurpose(name: string): string | null {
  const n = name.toLowerCase();
  if (/^train/.test(n)) return "teaches the model";
  if (/^(valid|val)/.test(n)) return "checks the model while it learns";
  if (/^test/.test(n)) return "gives the final score";
  if (n === "removed") return "images taken out of the other sets; nothing is deleted";
  return null;
}

export const GLOSSARY: Record<string, string> = {
  dataset: "A collection of images and their labels, such as the training images.",
  version:
    "A saved state of a dataset. Changes never overwrite anything: each save creates a new version, and older versions stay available.",
  split:
    "A dataset is usually divided into sets: a training set that teaches the model, and a validation or test set that checks how well it learned. The two must not share images.",
  label: "The name given to an object, such as \"car\" or \"pedestrian\".",
  box: "A rectangle drawn around one object in an image, together with its label.",
  health_check:
    "Before importing, Granum reads every label and image and lists anything that could make a model learn the wrong thing or report a misleading score.",
  run: "One training session of a model. Granum records how the model did on each image, so poor results lead you to the images behind them.",
  label_file:
    "The file that lists every image and the boxes drawn on it. In COCO format it's a .json file, often called _annotations.coco.json.",
};

/** Progress messages from the service, reworded. */
export function phaseLabel(phase: string | undefined): string {
  if (!phase) return "Getting started";
  if (phase === "Reading annotations") return "Reading the label files";
  if (phase === "Checking annotations") return "Checking the labels";
  if (phase === "Reading images") return "Opening every image";
  if (phase.startsWith("Writing ")) return `Saving ${phase.slice(8)}`;
  if (phase === "Writing tables") return "Saving";
  if (phase === "Indexing") return "Making it available";
  if (phase === "Done") return "Finishing";
  return phase;
}

/** Readable names for well-known columns. Anything else is shown with underscores as spaces. */
const COLUMN_NAMES: Record<string, string> = {
  image: "Image",
  image_id: "Image ID",
  bbs: "Boxes",
  bbs_predicted: "Predicted boxes",
  boxes_per_image: "Boxes per image",
  label: "Label",
  weight: "Weight",
  coco_image: "COCO image",
  source_image: "Source frame",
  sequence: "Sequence",
  content_hash: "Content hash",
  example_id: "Example ID",
  epoch: "Epoch",
  loss: "Loss",
  predicted: "Predicted",
  confidence: "Confidence",
  accuracy: "Accuracy",
  margin: "Margin",
  true_probability: "P(true label)",
  split: "Split",
  tp: "TP",
  fp: "FP",
  fn: "FN",
  f1: "F1",
  precision: "Precision",
  recall: "Recall",
  missed: "Missed",
  ignored: "Ignored",
  gt_match: "GT match",
  Edited: "Edited",
  Visited: "Visited",
  Selected: "Selected",
  Review: "Review",
  // per-box properties
  vertices: "Box",
  iscrowd: "Ignore region",
  area: "Area (px²)",
  annotation_id: "Annotation ID",
  iou: "IoU",
  matched: "Matched",
};

export function columnLabel(name: string): string {
  if (name.endsWith("@collected")) return `${columnLabel(name.slice(0, -10))} (at collection)`;
  return COLUMN_NAMES[name] ?? name.replace(/_/g, " ");
}
