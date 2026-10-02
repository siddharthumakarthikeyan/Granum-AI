---
title: Granum documentation
summary: Learn Granum end to end with a real dataset, actual screenshots and videos, then use the task guides and reference for daily work.
---

Granum connects images, annotations, human review and model measurements. The documentation starts
with a real small dataset and explains not only **what to click**, but **why**, **what to look for**,
**what the result means** and **when not to trust a conclusion**.

<div class="course-intro">
<p class="course-eyebrow">New to Granum? Start here.</p>
<p><strong>One real dataset. The complete workflow.</strong></p>
<p>12 guided steps · 120 aerial images · 35 actual screenshots · 10 captioned videos · no fabricated model results</p>
<div class="course-actions"><a class="btn primary" href="/docs/course/start">Start the guided course</a><a class="btn" href="/assets/course/aerial-mini.zip" download>Download sample · 26.4 MiB</a></div>
</div>

The default workflow is local-first. Optional shared services, cloud roots and configured training
integrations have separate access/network boundaries; see [Privacy](/docs/help/privacy).

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
<a class="doc-card" href="/docs/course/start"><strong>Learn by doing</strong><span>A real sample from setup and import to review, training, approval, export and restore.</span></a>
<a class="doc-card" href="/docs/start/install"><strong>Check your installation</strong><span>Build provenance, platform artifacts, the service and optional training support.</span></a>
<a class="doc-card" href="/docs/concepts/model"><strong>How Granum thinks</strong><span>Projects, sets, versions and runs — the five ideas everything else rests on.</span></a>
<a class="doc-card" href="/docs/guides/operations"><strong>Operate a pilot</strong><span>Approval, draft recovery, HTTPS roles, integrity and tested backup/restore procedures.</span></a>
</div>

## How this documentation is organised

**Guided aerial-data course** is the beginner path. It introduces the concepts, follows exact actions
and gives checkpoints. It records two genuinely weak GPU runs and approves only two inspected images;
it does not pretend that a successful workflow creates a production model or a fully reviewed sample.

**Getting started** is the short installation and orientation reference. The complete hands-on lessons
live in the course so there is one coherent first-use path rather than competing quick starts.

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

!!! note "Read, watch, then check"
  The course assumes no previous Granum experience. It explains boxes, splits and common metrics
  before using them. Videos are silent, captioned and accompanied by transcripts; screenshots open
  at full size. Every lesson separates an observed result from what it does not prove.
