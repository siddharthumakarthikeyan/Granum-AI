---
title: Run the loop once
summary: A concise map of the workflow, with links to the complete real-data course and the evidence each stage should preserve.
---

This is a workflow map, not a timed performance promise. For exact actions, a real downloadable sample,
screenshots and captioned recordings, follow [the guided course](/docs/course/start). Human review,
downloads and training take different amounts of time on different projects.

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

Read the coverage, counts, recommended choices and limitations. Record why you accept or change each
decision, then import. → [Recorded sample import](/docs/course/import) · [Import reference](/docs/guides/import)

## 2. Look at what arrived

Open **Images**. Turn **Annotations** on and scroll. Filter by class, by split, by status. Click an image
to open it full screen; click a class chip to darken everything except that class.

You are looking for the shape of the data: which classes are rare, how big the objects are, whether the
labelling convention held. Nothing you do here writes anything. → [Browse images](/docs/guides/browse)

## 3. Verify, and fix what is clearly wrong

Turn on **Review** in the ribbon. In local mode the reviewer name is self-reported; shared mode uses the
authenticated account. Inspect the full image before verifying it. Use bulk verification only for a
selection you actually inspected, not to bypass approval warnings.

When labels are wrong, fix them. In review the inspector lets you draw, select and delete boxes; the
**Edit** mode gives the full editor with moving, resizing, masks and keypoints. Every save writes a new
version of that set — nothing is overwritten.
→ [Review](/docs/guides/review) · [Edit annotations](/docs/guides/edit)

## 4. Freeze a dataset version

Click **Create dataset** in Images. Choose whole-dataset or verified-only selection and inspect the
included counts. Both create an **exploratory** version. Explicit approval is a separate gate requiring
matching review evidence for every included row, schema and media item.

This separates working data from recorded experiment inputs. Protect externally referenced image bytes
too; a frozen table does not stop another program overwriting media. When measuring an intervention,
freeze the baseline before changing labels. → [Course baseline](/docs/course/baseline)

## 5. Train

Choose **Train** on the intended dataset version. Confirm train, validation and genuine test roles,
model, image size and schedule. Exploratory training requires acknowledgement; approved-only training
rechecks approval and release membership. The course uses a small YOLO recipe as an exercise, not a
universal best model. → [Recorded training](/docs/course/train)

Leave **Record per-sample metrics and predictions every epoch** on. It costs some disk and makes the
next two steps possible. → [Train a model](/docs/guides/train)

## 6. Read the evidence

When the run finishes you have three things:

- **Runs** — framework history and separately recorded final scores. Comparability still requires
  matching inputs and evaluator policy. → [Read a run](/docs/guides/runs)
- **Samples** — per-image behaviour across recorded observations. Not learned is not proof of a wrong
  label or permission to delete a hard example. → [Per-image learning](/docs/guides/learning)
- **Findings** — a ranked queue of individual labels the model disagreed with, round after round, once it
  was competent on the set: missing labels, wrong classes, loose boxes. → [Findings](/docs/guides/findings)

Start with evidence coverage and model competence. Findings may be empty because the model is too weak
to support useful accusations. Inspect objects and images before changing labels. The course's
[actual weak baseline](/docs/course/results) demonstrates this case rather than inventing a populated queue.

## 7. Fix, freeze, train again — then compare

Make a justified, recorded change. If labels change, create a new version; if the experiment changes
only the recipe, retain the same frozen input. The course compares three vs twelve epochs without
claiming a label improvement.

Now open **Compare runs** and put the two side by side. Granum checks first that the comparison means
anything — same evaluation set, same scoring rules — and then shows which images improved, which
regressed, and which the two runs do not share. It will not tell you the gain was caused by your edits,
because with the data changed underneath that is not something anyone can honestly claim; it shows you
what moved and says plainly what the comparison is worth. → [Compare two runs](/docs/guides/compare)

!!! tip "What a good first loop looks like"
  You can explain the inputs, planned change, measured result and limits—even when the model is bad.
  Approve only genuinely reviewed contents, export in the recipient's required format, and verify
  a separate restore. The course ends with an approved two-image excerpt, not a false claim that the
  whole sample or either model is production ready.

## 8. Approve, deliver and verify recovery

Use [the scoped handoff](/docs/course/handoff) to separate selection, approval and export. Use
[the backup rehearsal](/docs/course/backup) to preserve project history and prove media can be restored.
A copied COCO export and a project backup serve different purposes.
