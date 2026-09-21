# Dashboard workspace

Projects, datasets, runs, review and import reports each have their own page and address, so
reload, back and pasted links all work. Opening a dataset version or a run shows the **inspection
workspace**: three linked panels that share one selection and one set of filters.

## Pages

| Page | Address | What it shows |
|---|---|---|
| Projects | `#/` | Every project under the project root. Hover a row to rename (pencil) or delete (bin) a project |
| Overview | `#/p/<project>` | Images, boxes, best mAP50, preflight findings needing attention, datasets |
| Datasets | `#/p/<project>/datasets` | Each dataset's sets and their version history |
| Images | `#/p/<project>/images?dataset=<name>` | Every image with its annotations. Review, edit and duplicate hunting are modes of this page |
| Runs | `#/p/<project>/runs` | Training runs, the comparison with the previous run, training charts |
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

## Copies and leaks

**Duplicates** in the Images ribbon answers two questions about a dataset before anything is
trained on it: is the same picture in here more than once, and is anything in a set you measure
with also in the set you train on?

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

Selected images go to the same decision tray as review, so removing a repeat moves it to the
removed set and can be undone from **Removed**. Nothing is deleted on Granum's own initiative.

A group larger than 40 images is not reported as duplicates at all: it is a continuum — a burst,
a pan, frames of a video — where each image is near the next and no two are the same picture.

Once the graph has been read, the gallery keeps the marks: a thumbnail shows how many images are
the same picture as it, how many times its own picture was exported, and whether it leaks.

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
