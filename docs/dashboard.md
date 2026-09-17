# Dashboard workspace

Projects, datasets, runs, review and import reports each have their own page and address, so
reload, back and pasted links all work. Opening a dataset version or a run shows the **inspection
workspace**: three linked panels that share one selection and one set of filters.

## Pages

| Page | Address | What it shows |
|---|---|---|
| Projects | `#/` | Every project under the project root |
| Overview | `#/p/<project>` | Images, boxes, best mAP50, preflight findings needing attention, datasets |
| Datasets | `#/p/<project>/datasets` | Each dataset's sets and their version history |
| Review | `#/p/<project>/review` | Review, rework, isolate, delete and ship. See [Review and shipping](review-and-shipping.md) |
| Runs | `#/p/<project>/runs` | Training runs, the comparison with the previous run, training charts |
| Samples | `#/p/<project>/learning?url=<run>` | When each image was learned during a run |
| Removed | `#/p/<project>/removed?dataset=<name>` | Deleted images, with a way to put them back |
| Import | `#/import` | The import wizard |

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

## Training runs and samples

- **Runs**: mAP50, precision, recall and losses per epoch for every run; the latest comparison
  against an earlier run, scored on the same current validation labels.
- **Samples**: per-image F1 every epoch groups images into *early*, *mid*, *late*, *forgotten*,
  *never learned* and *no objects*. Click an image for a full-screen viewer: zoom and pan, labels
  against model boxes round by round (`[` `]`, space to play), and Keep / Remove decisions.

## Performance

With the dev server running, `http://localhost:5173/?bench=1000000` loads a million synthetic rows
with no service needed. On an RTX PRO 4000 laptop GPU, pan, zoom and lasso hold 60 fps, and applying
a lasso to a million rows takes about 115 ms.
