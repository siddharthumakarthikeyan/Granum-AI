---
title: Run the loop once
summary: Import, verify, freeze, train, read the evidence, fix, retrain — the whole product in about an hour.
---

This is the shortest path through everything Granum does. Use the example dataset or a small dataset of
your own — a few hundred images is plenty. Each step links to the guide that covers it properly.

<figure class="doc-figure">
<svg viewBox="0 0 880 210" role="img" aria-label="The seven steps of the loop and what each one writes">
  <g font-family="Instrument Sans, sans-serif" font-size="12.5">
    <g fill="#ffffff" stroke="#c9d1db">
      <rect x="10" y="30" width="118" height="44" rx="8"/>
      <rect x="148" y="30" width="118" height="44" rx="8"/>
      <rect x="286" y="30" width="118" height="44" rx="8"/>
      <rect x="424" y="30" width="118" height="44" rx="8"/>
      <rect x="562" y="30" width="118" height="44" rx="8"/>
      <rect x="700" y="30" width="170" height="44" rx="8"/>
    </g>
    <g fill="#0e1420" font-weight="600" text-anchor="middle">
      <text x="69" y="57">1 Import</text>
      <text x="207" y="57">2 Look</text>
      <text x="345" y="57">3 Verify</text>
      <text x="483" y="57">4 Freeze</text>
      <text x="621" y="57">5 Train</text>
      <text x="785" y="57">6 Read the evidence</text>
    </g>
    <g fill="#6b7585" font-size="11.5" text-anchor="middle">
      <text x="69" y="96">preflight report</text>
      <text x="207" y="96">no writes</text>
      <text x="345" y="96">decisions, versions</text>
      <text x="483" y="96">dataset version</text>
      <text x="621" y="96">run + metrics</text>
      <text x="785" y="96">findings, comparison</text>
    </g>
    <g stroke="#9aa6b5" stroke-width="1.5" fill="none">
      <path d="M128 52h18M266 52h18M404 52h18M542 52h18M680 52h18"/>
      <path d="M785 120v34H345v-34" stroke-dasharray="4 4"/>
    </g>
    <text x="565" y="172" fill="#6b7585" font-size="12" text-anchor="middle">7 fix what the evidence points at, and go round again</text>
  </g>
</svg>
</figure>

## 1. Import, and read the preflight

Create the project and point Granum at your folder. The preflight opens every annotation file, and as
many images as you allow, and reports what it finds before anything is written: boxes on images that do
not exist, categories that disagree between sets, zero-area boxes, images byte-identical across train and
valid, and about twenty more.

Do not skip past this. Two minutes here will explain results you would otherwise spend a week chasing.
Change any option you disagree with, then import. → [Import data](/docs/guides/import)

## 2. Look at what arrived

Open **Images**. Turn **Annotations** on and scroll. Filter by class, by split, by status. Click an image
to open it full screen; click a class chip to darken everything except that class.

You are looking for the shape of the data: which classes are rare, how big the objects are, whether the
labelling convention held. Nothing you do here writes anything. → [Browse images](/docs/guides/browse)

## 3. Verify, and fix what is clearly wrong

Turn on **Review** in the ribbon. Type your name in the reviewer box. Work through the images: select
several and **Verify** them together, or open one, check it, and press <kbd>A</kbd> to verify and move on.

When labels are wrong, fix them. In review the inspector lets you draw, select and delete boxes; the
**Edit** mode gives the full editor with moving, resizing, masks and keypoints. Every save writes a new
version of that set — nothing is overwritten.
→ [Review](/docs/guides/review) · [Edit annotations](/docs/guides/edit)

## 4. Freeze a dataset version

Click **Create dataset** in the Images header. Name it — "v1, first pass" — and choose whether it holds
the whole dataset or only the images you verified.

This is the line between "data we are working on" and "data we trained on". Training offers dataset
versions only, and a version never changes afterwards. → [Create a dataset version](/docs/guides/dataset-versions)

## 5. Train

Open **Runs → Train model**. Pick the dataset version, which set to train on and which to validate on,
a model (YOLO nano is the right first choice), and how many rounds.

Leave **Record per-sample metrics and predictions every epoch** on. It costs some disk and makes the
next two steps possible. → [Train a model](/docs/guides/train)

## 6. Read the evidence

When the run finishes you have three things:

- **Runs** — the scores per round, and the final score computed the same way for every model family, so
  runs actually compare. → [Read a run](/docs/guides/runs)
- **Samples** — how each image was learned: early, mid, late, unstable, never. Images that are never
  learned are where wrong labels concentrate. → [Per-image learning](/docs/guides/learning)
- **Findings** — a ranked queue of individual labels the model disagreed with, round after round, once it
  was competent on the set: missing labels, wrong classes, loose boxes. → [Findings](/docs/guides/findings)

Findings is the one to start with. It takes you to a specific box in a specific image with the evidence
for why it is there, and records what you decided.

## 7. Fix, freeze, train again — then compare

Work the queue, fix what is wrong, create a second dataset version, and train again on it.

Now open **Compare runs** and put the two side by side. Granum checks first that the comparison means
anything — same evaluation set, same scoring rules — and then shows which images improved, which
regressed, and which the two runs do not share. It will not tell you the gain was caused by your edits,
because with the data changed underneath that is not something anyone can honestly claim; it shows you
what moved and says plainly what the comparison is worth. → [Compare two runs](/docs/guides/compare)

!!! tip "What a good first loop looks like"
    An hour on the example dataset, or an afternoon on a real one. You should finish with two dataset
    versions, two runs, a handful of recorded review decisions, and a comparison report you could show
    someone. If you got a number that went up but cannot say what changed in the data, go back to step 4:
    freezing a version is what makes the rest legible.
