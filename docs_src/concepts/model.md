---
title: How Granum is organised
summary: Five ideas — project, dataset, set, version, run — and how they fit together.
---

Everything in the app is one of five things. Once these are clear, every screen reads as an obvious
consequence of them.

<figure class="doc-figure">
<svg viewBox="0 0 880 260" role="img" aria-label="A project contains a dataset of sets, each set has versions; dataset versions freeze a choice of versions; runs are trained on a dataset version">
  <g font-family="Instrument Sans, sans-serif" font-size="12.5">
    <rect x="12" y="14" width="856" height="232" rx="12" fill="#ffffff" stroke="#c9d1db"/>
    <text x="30" y="40" fill="#0e1420" font-weight="600" font-size="13">Project “aerial-people”</text>

    <rect x="30" y="56" width="380" height="120" rx="10" fill="#f3f6f9" stroke="#dde3ea"/>
    <text x="46" y="78" fill="#0e1420" font-weight="600">Dataset “human_aerial”</text>
    <g font-size="11.5" fill="#4b5566">
      <rect x="46" y="90" width="110" height="70" rx="8" fill="#ffffff" stroke="#dde3ea"/>
      <text x="101" y="110" text-anchor="middle" fill="#0e1420" font-weight="600">train</text>
      <text x="101" y="128" text-anchor="middle">v1 → v2 → v3</text>
      <text x="101" y="146" text-anchor="middle">11,335 images</text>

      <rect x="166" y="90" width="110" height="70" rx="8" fill="#ffffff" stroke="#dde3ea"/>
      <text x="221" y="110" text-anchor="middle" fill="#0e1420" font-weight="600">valid</text>
      <text x="221" y="128" text-anchor="middle">v1 → v2</text>
      <text x="221" y="146" text-anchor="middle">547 images</text>

      <rect x="286" y="90" width="110" height="70" rx="8" fill="#ffffff" stroke="#dde3ea"/>
      <text x="341" y="110" text-anchor="middle" fill="#0e1420" font-weight="600">test</text>
      <text x="341" y="128" text-anchor="middle">v1</text>
      <text x="341" y="146" text-anchor="middle">320 images</text>
    </g>

    <rect x="440" y="56" width="180" height="120" rx="10" fill="#f3f6f9" stroke="#dde3ea"/>
    <text x="456" y="78" fill="#0e1420" font-weight="600">Dataset versions</text>
    <g font-size="11.5" fill="#4b5566">
      <text x="456" y="100">v1 — first pass</text>
      <text x="456" y="120">v2 — after review</text>
      <text x="456" y="140">v3 — v2 + augmented</text>
      <text x="456" y="162" fill="#6b7585">frozen, never change</text>
    </g>

    <rect x="650" y="56" width="196" height="120" rx="10" fill="#f3f6f9" stroke="#dde3ea"/>
    <text x="666" y="78" fill="#0e1420" font-weight="600">Runs</text>
    <g font-size="11.5" fill="#4b5566">
      <text x="666" y="100">baseline — on v1</text>
      <text x="666" y="120">after-review — on v2</text>
      <text x="666" y="140">augmented — on v3</text>
      <text x="666" y="162" fill="#6b7585">scores + per-image results</text>
    </g>

    <g stroke="#9aa6b5" stroke-width="1.5" fill="none">
      <path d="M410 116h28"/><path d="M620 116h28"/>
    </g>
    <text x="440" y="212" fill="#6b7585" font-size="12">Reviews, comments and findings decisions live beside the dataset, keyed by image, so they survive every new version.</text>
  </g>
</svg>
</figure>

## Project

One body of work. It holds a dataset, everything ever done to it, and every run trained from it. Projects
are independent: renaming, deleting or copying one never touches another. A project also carries its
**type** — what its labels are for — which decides what the editor offers and what can be trained.
→ [Projects and project types](/docs/concepts/projects)

## Dataset and sets

A dataset is the body of images; the **sets** inside it are the usual `train`, `valid` and `test`, plus
two Granum creates when you need them: `isolated` for images set aside during review, and `removed` for
images taken out.

Importing train, valid and test together gives you one dataset with three sets — not three datasets. This
matters: review status, comments and class lists are shared across the whole dataset, so a class you add
while editing a training image is available on a validation image too.

## Version

Every change to a set writes a **new version** of that set and leaves the old one exactly as it was.
Correcting boxes on one image, removing ten images, returning an isolated image — each writes a version.
Nothing is edited in place, so any number that was ever computed can be traced back to the data it was
computed on. → [Versions and lineage](/docs/concepts/versions)

## Dataset version

A named, frozen choice of one version of each set: "v2 — after review", made of `train` v3 and `valid`
v2. This is the unit you train on, and the only thing the train dialog offers.

The distinction is the point of the product. The images in the Images tab are what you are *working on*;
a dataset version is what you *agreed on*. → [Dataset versions](/docs/concepts/dataset-versions)

## Run

One training job: its recipe, its score per round, and — when you ask for it — a per-image record of what
the model predicted in every round. Those per-image records are what turn a disappointing number into a
list of images to look at. → [Runs and metrics](/docs/concepts/runs)

---

Two more ideas sit underneath, and both are about trust:

- **Identity** — a metric must stay attached to the image it was measured on, even after rows are
  deleted and versions are made. → [Image identity](/docs/concepts/identity)
- **Evidence** — what the model's behaviour can and cannot tell you about your labels.
  → [What the evidence is worth](/docs/concepts/evidence)
