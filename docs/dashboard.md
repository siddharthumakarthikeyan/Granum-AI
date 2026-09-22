# Dashboard workspace

Projects, datasets, runs, review and import reports each have their own page and address, so
reload, back and pasted links all work. Opening a dataset version or a run shows the **inspection
workspace**: three linked panels that share one selection and one set of filters.

## Pages

| Page | Address | What it shows |
|---|---|---|
| Projects | `#/` | Every project under the project root. Hover a row to rename (pencil) or delete (bin) a project |
| Overview | `#/p/<project>` | Images, boxes, best mAP50, preflight findings needing attention, datasets |
| Datasets | `#/p/<project>/datasets` | Each dataset's sets and their version history, with *Train* and *Export* on every version |
| Health | `#/p/<project>/health?dataset=<name>` | Whether a dataset is fit to train on: copies, leaks, outliers, class imbalance, findings and review, each judged against a stated threshold |
| Images | `#/p/<project>/images?dataset=<name>` | Every image with its annotations. Review, edit and duplicate hunting are modes of this page |
| Runs | `#/p/<project>/runs` | Training runs, the comparison with the previous run, training charts |
| Findings | `#/p/<project>/findings` | Labels a model suggests checking, from a training run or from one pass over the labels |
| Evaluation | `#/p/<project>/evaluation?url=<run>` | One run read for what it gets wrong: confusion matrix, per-class scores, threshold sweep |
| Compare | `#/p/<project>/compare?baseline=<run>&candidate=<run>` | Two runs image by image, with a downloadable report |
| Samples | `#/p/<project>/learning?url=<run>` | When each image was learned during a run |
| Removed | `#/p/<project>/removed?dataset=<name>` | Deleted images, with a way to put them back |
| Import | `#/import` | The import wizard |

## Renaming a project

Rename a project from the pencil icon on its row in **Projects**, or next to its name on the overview
(hover the title). Names may use letters, numbers, spaces, dots, dashes and underscores, and must not match
another project. Everything inside the project follows the new name: dataset versions and their history,
runs and their metrics, reviews, comments, isolated images and shipments. Image files are not touched.
A project cannot be renamed while it is training.

## Deleting a project

Delete a project from the bin icon on its row in **Projects**, or next to **Train model** on its
overview. Type the project name to confirm. This permanently removes its dataset versions, runs, reviews,
comments, shipments, import reports, and the model weights its training runs saved under
`~/granum-training`. Your original image and annotation files are never deleted. A project cannot be deleted
while it is training.

## Rows

Click to select, `Ctrl` to add, `Shift` for a range, `↑` `↓` to move, `A` for all, `Esc` to clear.
`Shift`-click a header to sort, `Ctrl+Shift`-click to add a sort key, right-click to hide a column,
drag to reorder. Switch between a list and a thumbnail grid.

## Filters

One widget per filterable column. Drag on a histogram to paint a range: blue is filtered in, grey
is filtered out. Invert, reset and lock (locked filters survive clear-all). Switch **live** off to
stop a row you are editing from disappearing when its new value no longer matches.

## Charts

Select headers in order and press **+ chart**:

- one numeric column plots row against value; two plot x against y; a third colours the points;
- an image column alone opens an image chart with the label and prediction in the corners.

Scatter tools: pan and zoom (wheel; `Shift` zooms x only, `Alt` y only), rectangle, lasso, polygon
and brush. A drawn region replaces the selection, `Ctrl` adds, `Shift` subtracts. Regions are ordinary
filters, so the rows narrow with them. Per chart: colour and radius by column, point size, filtered-out
points in grey, lock, clone and favourite.

Categorical colour uses three hues, the most that stay distinguishable in a scatter on this surface
(colour-vision deficiency included). Click a category in the legend to give it a hue.

## Editing

Nothing is written until you commit. Edits apply to the loaded rows immediately and are kept on an undo stack.

- **Edit a cell**: double-click. Editable columns are marked ✎; edited cells turn yellow. With a
  multi-row selection the value goes to every selected row.
- **Assign to a selection**: the bar above the rows sets any editable column on all selected rows.
  `W` toggles weight between 0 and 1.
- **Classes**: add, rename and recolour. A class still in use cannot be removed.
- **New columns**: editable `bool`, `string`, `float32` or `int32`.
- **Session columns**: `Edited`, `Visited`, `Selected` are filterable but never saved.
- **Undo** `Ctrl+Z`, **redo** `Ctrl+Shift+Z`, **discard** from the top bar.
- **Commit** (`Ctrl+S`) lists edits by column; discard any group, name the version, and it is written
  as one new version naming its parent. In a run view, edits go to the run's input dataset.

Unsaved edits are also kept in the browser (IndexedDB) and offered for restoring after a reload or crash.

## Object detection

- **Drawing**: labels solid (amber when the model missed them), predictions dashed (cyan when they
  match a label, pink when they match none). Thumbnails show boxes; an image chart adds zoom, an
  instance list synced with the image, box-by-box navigation, and colour by match or class.
- **Per-box filters**: each box column gets filters for class, area, instance properties and
  `missed`. They combine on the same box: "matched = false and confidence ≥ 0.5" keeps images with
  at least one such box and draws only those boxes.
- **Accepting predictions**: select a prediction, `Enter` to accept it (replacing a label it
  overlaps, or adding it) or `Delete` to reject it. Works per box, image, selection or all visible rows.
- **Box editing**: **✎ edit**, then drag to draw, drag a selected box to move, drag an edge or corner
  to resize; `Delete` removes; `Ctrl+C` / `X` / `V` copy, cut and paste across images; relabel
  from the instance list; NMS at a chosen IoU removes duplicate labels.
- **Patches**: one tile per box across visible rows; select several and relabel them together.

All box edits use the same undo stack and commit as other edits.

## Review decisions in the workspace

Selected images can be marked *Correct*, *Corrected*, *Ambiguous*, *Deferred* or *Excluded*, with
an optional reason. These curation decisions are recorded immediately (no commit needed), appear as
a filterable *Review* column, and are separate from the annotation-review statuses of the
[Review tab](review-and-shipping.md).

## Patches: one tile per object

**Patches** in the Images ribbon unrolls the gallery into one tile per labelled object, cropped
to the box with a little of its surroundings around it. It is how a class is checked for
consistency: a "car" that is plainly a van stands out in a wall of cars in a way it never does
inside a busy street scene.

The ribbon still decides what is in front of you, and the class filter narrows the *objects* as
well as the images — asked for cars, the grid shows cars, not the pedestrians standing next to
them. Tiles are cut from the images whose geometry has been fetched, and *Show more objects*
brings in both more objects and more images, so a page is a run you can scan rather than a
scroll that never ends. Clicking a tile opens its image full screen with that object picked out
and the rest of the picture dimmed, which is where a wrong label gets fixed.

## Stats: what these images are made of

**Stats** opens a panel beside the gallery counting the selection: images per set, where they
stand in review, how many objects each image carries, how many images contain each class, and
how much of an image its boxes cover. The numbers are of whatever the ribbon has left, so
filtering to the validation set gives the validation set's distribution — which is how you find
out that the class you are missing is missing only there.

Each distribution leaves out its own filter, so every set and every class stays a bar you can
pick: clicking one narrows the gallery to it, clicking it again lets it go. The counts come from
the image rows and cover the whole selection; object *size* is the one exception and is counted
over the images whose boxes have been read so far, which the panel says under it.

## Copies, leaks and outliers

**Duplicates** in the Images ribbon answers three questions about a dataset before anything is
trained on it: is the same picture in here more than once, is anything in a set you measure with
also in the set you train on, and what is in here that nothing else is like?

Both are read off one neighbour graph. Granum reads every image once into a vector (MobileNetV3
or ResNet-18 when the training add-on is installed; otherwise a plain colour-and-edge descriptor,
which finds copies and resizes but does not judge content, and says so). The vectors are kept per
dataset and keyed by image, so they outlive every version of a set: moving an image between sets
or deleting one costs a neighbour graph, not another pass over the images.

Distances are read as a share of *the median distance between two images of this dataset picked
at random*, which is what makes one threshold work on a set of street scenes and on a set of
microscope slides. Two images are grouped as near-identical below 12% of it, and counted as a
leak below 30% of it when they sit in different sets.

### Pictures, not files

An augmented copy *is* the same picture: a flip, a crop, a colour shift. No distance can separate
that from a second photograph of the same thing, and the two mean opposite things — one is
training data somebody asked for, the other is redundancy. So Granum separates them by provenance
instead: its own augmented sets carry `augmented_from`, and an export that augments keeps the
source name in every copy's filename (`<source>_jpg.rf.<hash>.jpg`, which is how most datasets
arrive). Images that share a source are one picture, and are never counted as repeats of each
other or offered for removal.

That is why the summary counts **distinct pictures**, not images: a set of 12,429 images can be
7,015 pictures, and knowing which is which changes what the numbers mean.

- **Repeats** lists each group of pictures that are the same shot, most pictures first, with the
  group's **spread**: how far apart its two least alike members are. Grouping carries along a
  chain — A near B and B near C puts all three together — so a spread near zero is one shot taken
  twice, while a larger one is a run of frames each close to the last. One picture is marked
  *Keep* (the training one where there is one) along with the export's copies of it, and
  *Select the other N* picks the remaining pictures and everything that came with them.
- **Exported copies** lists every picture the export wrote out more than once. Nothing here is
  offered for removal; it is where you check that Granum has understood your dataset, and where a
  picture whose copies were dealt into *different* sets is marked **Split through it** — a leak
  however alike the copies look.
- **Leaks** lists each pair side by side with the two sets it straddles, and offers *Select train*,
  *Select valid* and so on, to take one whole side out at once. A pair of copies of one picture is
  reported whatever the distance between them: a heavy colour shift is a long way off in the
  embedding and leaks exactly as badly.
- **Outliers** lists the images furthest from anything else in the set, furthest first, each
  marked with how far its nearest neighbour is as a share of the typical distance. Past 90% of it
  an image is tagged **Nothing like it**: nothing in the dataset is really similar. A set of one
  subject shot by one camera has no image that far out and still has a furthest one, so the tab
  ranks rather than filters — an empty answer would say the check had not run. Nothing is offered
  for removal in bulk here: a lone image is as likely to be the one rare case the set needs as it
  is to be a mistake.

Selected images go to the same decision tray as review, so removing a repeat moves it to the
removed set and can be undone from **Removed**. Nothing is deleted on Granum's own initiative.

A group larger than 40 images is not reported as duplicates at all: it is a continuum — a burst,
a pan, frames of a video — where each image is near the next and no two are the same picture.

Once the graph has been read, the gallery keeps the marks: a thumbnail shows how many images are
the same picture as it, how many times its own picture was exported, and whether it leaks.

### What else looks like this one

The same vectors answer a question about a single image. The magnifier on a thumbnail, *Find
images like this* in the full-screen viewer, and the same action on an outlier tile all put the
gallery in front of that image's neighbours, most alike first, with a bar above naming the image
they are being compared against. Each thumbnail carries how alike it is as a share of the typical
distance, so *the same* and *38%* are different claims rather than two numbers. The ribbon's
filters still narrow the answer — the valid images most like this training image, say — and
*Ask for 200* widens it from the 60 nearest. Review and Edit work on the result as on any other
gallery, so a run of near-copies can be selected and dealt with where it was found.

### Uniqueness as an order

**Order by → Uniqueness** sorts the gallery by how unlike the rest of the dataset each image is,
most unusual first, with the score on each thumbnail (0 is a copy of something here, 1 is nothing
like it). It weights the nearest neighbours most, so one exact copy is enough to make an image
unremarkable however unusual the rest of its neighbourhood is. Both this and *Find images like
this* need the dataset to have been read once; where it has not, the bar under the ribbon says so
and offers to read it.

## Pre-labelling: a model drafts the labels

Labelling from nothing is the expensive part of a dataset. **Pre-label** in the Images header
runs a model over the sets you choose and writes its boxes in as labels, turning labelling into
correcting. The model is the same choice as a check: one trained in this project, or one that has
never seen this data (which draws only the classes it knows and leaves the rest).

Every box it draws is marked as a **draft** — the set's box column gains `source` and
`confidence`, and the labels that were already there are marked `manual` on the way through. A
drafted box is drawn dashed wherever boxes are drawn, and each thumbnail says how many of its
boxes are drafts, so nothing can mistake a machine's guess for a label somebody checked.

Two choices decide what can be lost, and the default loses nothing:

- **Leave them alone** (default) — only images with no labels at all get boxes.
- **Redraw them** — every image gets the model's boxes instead of the ones it has.

Either way a **new version of each set** is written, so the labels that were there stay in the
version before it. The confidence slider trades boxes to delete against objects to add by hand.

## Health: is this dataset fit to train on?

Granum already knows most of this — the import found broken files, the neighbour graph found
copies and leaks, a check found labels worth looking at, the review log knows what has been
verified. Each of those lives on the page where it was produced, which is the right place to
*work* and the wrong place to answer "is it ready?". The Health page is those answers in one
list, each judged against a threshold that is written down beside it:

- **block** — a reason not to train yet: an image in two sets at once makes the score partly a
  memory test, and a dataset with nothing held back has nothing to measure with.
- **warn** — a reason to look: too many copies, too many images with nothing like them, a class
  too rare for the loss to care about, labels a check flagged, or boxes a model drew that nobody
  has confirmed.
- **ok** — nothing to do, said out loud, because a check that only speaks up when it is unhappy
  is a check nobody trusts.

Every row links to the page that can act on it.

## Evaluation: what one run gets wrong

A single mAP number says a run is better or worse; it never says *what* it gets wrong. The
Evaluation page reads one run's stored predictions three ways:

- **Confusion**, matched class-agnostically: a box is paired with the nearest label it overlaps
  whatever class it claims, so "van called car" lands in a cell instead of vanishing into one miss
  and one false positive, which is how class-aware matching — the right rule for *scoring* — hides
  it. Every cell is a button: it opens the objects behind it, cut to the box, label solid and the
  model's box dashed over it.
- **Per class**: precision, recall, F1, support and average precision, so a class the set barely
  holds reads as that rather than as noise in the mean.
- **Threshold**: precision and recall as the operating confidence is swept, with the point that
  scores best named — the confidence a team ships at is a choice, and it is usually a guess.

## Findings: labels worth checking

**Findings** ranks the labels a model disagrees with, under four rules — a confident prediction
with nothing labelled there (*missing label*), a confident prediction of another class on a label
(*wrong class*), a box that overlaps its label too little to match (*loose box*), and a label the
model does not find at all (*not found*). Each one is shown as a crop around the box with the
evidence behind it, and a decision is recorded per image.

The evidence comes from one of two places, and the page says which.

### A training run

A run started with *Record per-sample metrics and predictions every epoch* keeps the model's boxes
for every image in every epoch. A finding then has to **recur**: it is judged only on the epochs
after the model became competent on the set, must appear in at least a fifth of them, and a label
the model merely fails to find must be missed in half. That is the strongest evidence Granum has,
because a label that is wrong stays wrong round after round while noise does not.

### A check: one pass, no training

**Check labels** runs one model over a dataset version and asks the same four questions. It needs
no training run, takes minutes, and changes nothing. Two models are offered:

- **a model trained in this project** — it knows these classes exactly, and pointing it at labels
  edited since it was trained is the strongest use of it;
- **a model that has never seen this data** — it knows the classes it was trained on. Whichever of
  yours it cannot name are left alone rather than reported as wrong, and the report says which.

With no rounds to recur in, a finding is worth what the model's confidence is worth, and a label
the model simply does not find weighs half of a just-confident prediction. Each image also gets a
**trustworthiness** number, decided by its worst box rather than by the average of its boxes: forty
right boxes do not make one badly wrong box acceptable.

A single pass over a dense set would otherwise report everything, so a check is gated by what the
pass was worth on that set. A class the model finds less than 60% of here is a class it cannot find
here, and its silence about those labels is not evidence; the page names those classes and their
recall. In an image where it found less than 60% of the labels it could be asked about, it is out
of its depth and its misses are dropped — its own confident predictions are still reported. On one
aerial set, that gate took a check from 17,686 "not found" to 1,949.

The queue can be ordered by the strongest single finding or by **least trustworthy image**,
which is the softmin above: twenty middling disagreements make a worse picture than one loud one.

The check also summarises the **class pairs** it disagrees with most — `van → car 354`,
`people → pedestrian 79` — which is a fact about the labelling rather than about any one box: a
distinction the dataset is not drawing consistently.

## Exporting a dataset version

*Export* on a dataset version writes it out for another tool, under the project's `exports`
folder in a folder named for the version, the format and the time. The version is read as it
was frozen, so what leaves is what was trained on, whatever has been edited since.

Eight layouts: **COCO**, **YOLO**, **Pascal VOC**, **KITTI**, **CSV** (one row per box),
**CVAT for images**, **Label Studio** tasks, and **folder per class**. A box a model drafted
carries its source and its confidence wherever the format has room for them, so nothing
downstream can mistake a draft for a label somebody checked.

The second question is what to do with the image files, and it is the one people get wrong:

- **Link to them** — no extra disk, and broken the moment the folder moves to another machine.
- **Copy them** — portable, and as large again as the images.
- **Hard link them** — no extra disk, and survives moving within the same drive.
- **Labels only** — annotations alone, naming the images where they already are. Not offered for
  YOLO or folder-per-class, because in those two layouts the images *are* the annotation.

The same formats can be read back in, converted to COCO first so that a VOC folder and a COCO
file go through exactly the same preflight, media checks and findings rather than two code paths.
The import wizard marks a folder it recognises with the layout it found.

## Training runs and samples

- **Runs**: mAP50, precision, recall and losses per epoch for every run; the latest comparison
  against an earlier run, scored on the same current validation labels.
- **Samples**: per-image F1 every epoch groups images into *early*, *mid*, *late*, *forgotten*,
  *never learned* and *no objects*. Click an image for a full-screen viewer: zoom and pan, labels
  against model boxes round by round (`[` `]`, space to play), and Keep / Remove decisions.

## Comparing two runs

**Compare runs** (the button on Runs, or a row's *Compare*) puts a baseline and a candidate side by
side on the set they share. Whether they may be compared comes first: Granum refuses rather than
averages when the two were scored on different sets, under different scoring rules, or against
different class lists, and it says what it could not check. A new version of the evaluation set, a
changed training recipe or two runs on one seed each are warnings, not refusals.

What it then shows, in order:

- the score each run recorded, with a declared tolerance — a difference inside it is *too close to
  call*, because one seed per run says nothing about run-to-run spread;
- how the difference may be read: a *controlled* comparison changes one thing, an *observational*
  one is what you get after editing the data, and nothing here attributes a gain to one edit;
- every image as **improved**, **regressed**, **unchanged** or unmatched — in one run's set and not
  the other's. Images are paired by their image reference, so a removed row cannot shift the join;
- slices by class and by object size, each with the number of labels behind it; a slice with fewer
  than 30 is shown and marked *too few to call*;
- what changed in the training and evaluation data (images added, removed or edited; boxes drawn,
  deleted, relabelled or moved), and what the two runs cost in rounds, time and review decisions.

**Download report** saves the whole thing as JSON — versions, checks, every image, slices and costs —
for a pilot write-up or a regression record.

## Performance

With the dev server running, `http://localhost:5173/?bench=1000000` loads a million synthetic rows
with no service needed. On an RTX PRO 4000 laptop GPU, pan, zoom and lasso hold 60 fps, and applying
a lasso to a million rows takes about 115 ms.
