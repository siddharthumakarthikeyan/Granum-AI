---
title: Granum documentation
summary: How to get your computer-vision data into shape, and what every screen is for.
---

Granum is a data workbench for computer-vision teams. It checks a dataset as you import it, gives
everyone one place to look at, correct and verify every label, freezes what you agreed on into a
dataset version, trains a detector on exactly that version, and then uses the model's own behaviour
to point at the labels worth checking next.

It runs on your computer. Your images are never uploaded.

<figure class="doc-figure">
<svg viewBox="0 0 880 150" role="img" aria-label="The loop: import, review, dataset version, train, findings, back to review">
  <defs>
    <marker id="a" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0 0 10 5 0 10z" fill="#9aa6b5"/>
    </marker>
  </defs>
  <g font-family="Instrument Sans, sans-serif" font-size="13" text-anchor="middle">
    <g fill="#ffffff" stroke="#c9d1db">
      <rect x="8" y="42" width="130" height="46" rx="8"/>
      <rect x="178" y="42" width="130" height="46" rx="8"/>
      <rect x="348" y="42" width="150" height="46" rx="8"/>
      <rect x="538" y="42" width="130" height="46" rx="8"/>
      <rect x="708" y="42" width="160" height="46" rx="8"/>
    </g>
    <g fill="#0e1420" font-weight="600">
      <text x="73" y="70">Import</text>
      <text x="243" y="70">Review and fix</text>
      <text x="423" y="70">Dataset version</text>
      <text x="603" y="70">Train</text>
      <text x="788" y="70">Findings</text>
    </g>
    <g stroke="#9aa6b5" stroke-width="1.5" fill="none" marker-end="url(#a)">
      <path d="M140 65h32"/><path d="M310 65h32"/><path d="M500 65h32"/><path d="M670 65h32"/>
      <path d="M788 92v22H243V92"/>
    </g>
    <text x="515" y="131" fill="#6b7585" font-size="12">what the model says is worth checking, back into review</text>
  </g>
</svg>
</figure>

## Start with one of these

<div class="doc-cards">
<a class="doc-card" href="/docs/start/install"><strong>Install Granum</strong><span>Windows and Linux, the training add-on, and where your work is kept.</span></a>
<a class="doc-card" href="/docs/start/the-loop"><strong>Run the loop once</strong><span>An hour end to end on a small dataset, so the whole product makes sense.</span></a>
<a class="doc-card" href="/docs/concepts/model"><strong>How Granum thinks</strong><span>Projects, sets, versions and runs — the five ideas everything else rests on.</span></a>
<a class="doc-card" href="/docs/reference/screens"><strong>Map of the app</strong><span>Every screen, what it is for, and where its buttons lead.</span></a>
</div>

## How this documentation is organised

**Getting started** is a path: install, sign in, make a project, then run the full loop once. Follow it
in order the first time and you will have trained a model on data you verified yourself.

**Concepts** explains the model behind the product — what a set is, what a version is, what makes a
dataset version different from the images you are looking at, and how Granum keeps a metric attached to
the image it was measured on. These pages are short and worth reading once; they save you from guessing
later.

**Guides** are task pages: one job each, in the order the work usually happens. Each says what the screen
does, what to do, what gets written, and where the honest limits are.

**Reference** is for looking things up: every screen, every keyboard shortcut, every import check, the
models you can train, where files live on disk, what scales and what does not.

**Help** covers what to do when something is wrong, the questions people ask most, and exactly what
leaves your machine.

!!! note "A note on tone"
    These pages assume you know your own field: that you have trained a detector, that you know what
    precision and recall are, and that you can tell a hard example from a wrong label. They explain
    Granum, not computer vision.
