---
title: Glossary
summary: The words this product uses, and exactly what each one means.
---

**Class** — a label's category: *person*, *car*. The class list belongs to the dataset, so a class added
while editing one image is available on every set in it.

**Crowd / ignore region** — an object or area marked as not individually labelled. Never matched, never
counted as missed, and predictions mostly inside one are ignored rather than counted against the model.

**Dataset** — the body of images in a project, holding its sets.

**Dataset version** — a named, frozen choice of one version of each set. The only thing training uses.
Sometimes called a release in the file layout. → [Concept](/docs/concepts/dataset-versions)

**Finding** — a candidate label problem raised by a rule from a run's own predictions, with the evidence
attached. Not a verdict. → [Guide](/docs/guides/findings)

**Isolated** — images set aside during review, kept out of new dataset versions until returned.

**Observation** — one round in which per-image metrics were collected. A 60-round run with collection
every fifth round has 12 observations.

**Preflight** — the checks run over annotations and images before an import writes anything.
→ [Reference](/docs/reference/preflight)

**Project** — one body of work: a dataset, its history, its reviews and its runs.

**Removed** — images taken out of a set. Recorded with where they came from and why, and restorable.

**Round** — one epoch. Granum says *round* while a run is in progress and *epochs* where a number is
being chosen or reported; they are the same thing.

**Run** — one training job: its recipe, its scores per round, and its per-image results.

**Set** — a part of a dataset: `train`, `valid`, `test`, plus `isolated` and `removed` when needed. Also
called a split.

**Support** — how many labels a number rests on. A slice with 8 labels and one with 8,000 are not the
same kind of evidence, and Granum marks the first as too few to call.

**Tolerance** — the declared difference below which two scores are reported as too close to call. It is
declared, not measured: with one seed per run, nobody knows the true run-to-run spread.

**Unverified / verified / rework** — the three image statuses.
→ [Concept](/docs/concepts/verification)

**Version** — one immutable revision of one set. Every change writes a new one.
→ [Concept](/docs/concepts/versions)
