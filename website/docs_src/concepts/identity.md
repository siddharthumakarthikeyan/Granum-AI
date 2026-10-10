---
title: Image identity
summary: Why a metric stays attached to the image it was measured on, and the one rule that keeps it true.
---

Every number Granum shows about an image — its F1 in round 7, the boxes the model predicted, the finding
that says a label is wrong — was computed at a moment when the set was in a particular state. Between
then and now, images may have been deleted, added, reordered or edited.

If that join breaks, the product does not degrade gracefully: it shows you a confident, wrong picture of
a different image. So it is worth knowing how it is kept.

## Two ways to name an image

**By position.** Metrics are recorded per row: row 4,172 of this table. Positions are compact and fast,
which is why per-image metrics use them, and they are correct *only* against the exact version the
metrics were collected on.

**By reference.** The image's path. Positions move when a row is deleted; the photograph does not. Review
statuses, comments, findings decisions and run comparisons are all keyed by reference.

## The rule

> A metric may be joined to a different version of a set only if every step between them preserved rows.

Granum knows which operations preserve rows (editing labels, changing a class list, setting weights) and
which do not (deleting rows, adding rows, re-splitting). When you look at a run against the newest
version of its data, Granum walks the lineage from the version the metrics were collected on: if every
step in between kept rows in place, it joins to the newer one, so you see the *corrected* labels beside
the metrics computed before the fix. If any step moved rows, it joins to the original version and says
so, rather than guessing.

Equal row counts are not enough, and Granum does not accept them as evidence: a deletion followed by an
addition leaves the count unchanged and every position after the deletion wrong.

<figure class="doc-figure">
<svg viewBox="0 0 880 152" role="img" aria-label="Metrics collected on v1 join to v2 because it only edited labels, but not to v3 which deleted rows">
  <g font-family="Instrument Sans, sans-serif" font-size="12.5">
    <g fill="#ffffff" stroke="#c9d1db">
      <rect x="20" y="52" width="120" height="44" rx="8"/>
      <rect x="230" y="52" width="120" height="44" rx="8"/>
      <rect x="440" y="52" width="120" height="44" rx="8"/>
      <rect x="660" y="20" width="196" height="44" rx="8"/>
    </g>
    <g fill="#0e1420" font-weight="600" text-anchor="middle">
      <text x="80" y="79">train v1</text><text x="290" y="79">train v2</text><text x="500" y="79">train v3</text>
      <text x="758" y="47">run: per-image metrics</text>
    </g>
    <g fill="#6b7585" font-size="11.5" text-anchor="middle">
      <text x="185" y="44">edited labels</text><text x="185" y="118">rows kept</text>
      <text x="395" y="44">deleted 12 images</text><text x="395" y="118">rows moved</text>
    </g>
    <g stroke="#9aa6b5" stroke-width="1.5" fill="none">
      <path d="M140 74h84"/><path d="M350 74h84"/>
    </g>
    <path d="M660 52 L352 70" stroke="#067647" stroke-width="1.5" fill="none"/>
    <text x="512" y="140" fill="#067647" font-size="11.5" text-anchor="middle">joins forward to v2: safe</text>
    <path d="M700 64 L560 70" stroke="#b42318" stroke-width="1.5" stroke-dasharray="4 3" fill="none"/>
    <text x="790" y="92" fill="#b42318" font-size="11.5" text-anchor="middle">not to v3: refused</text>
  </g>
</svg>
</figure>

## Why this shapes the product

Several decisions that look like UI choices follow from this rule:

- **Deleting images creates a new version** instead of removing rows in place, so old metrics keep a
  version they are valid against.
- **Review status is keyed by image reference**, so it survives deletions that would scramble positions.
- **Run comparison pairs images by reference**, not by row, and reports images one run has and the other
  does not rather than lining up two lists of different lengths.
- **Findings are computed against the exact version the run was collected on**, then shown with today's
  review decisions merged in.

A regression test for exactly this ships with Granum: a run is collected, an image is removed, and every
screen that shows per-image results must still show each number on the image it was measured on.
