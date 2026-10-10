---
title: Per-image learning
summary: Which images the model learned early, late, unstably or never — and what to do with each group.
---

**Samples**, on a run that recorded per-image metrics every round, groups every image by how it behaved
across the run. A single round says which images the model gets wrong now; the sequence says much more.

## The categories

| Category | What happened | What it usually means |
|---|---|---|
| **Early** | Learned quickly and stayed learned | Ordinary, well-labelled images |
| **Mid** | Learned somewhere in the middle | Ordinary |
| **Late** | Only learned near the end | Hard examples, or labels that fight the convention |
| **Unstable** | Learned, then lost again, perhaps repeatedly | Inconsistent labelling, or genuinely ambiguous content |
| **Not learned** | Never reached the threshold | Where wrong labels concentrate — check these first |
| **Too few observations** | Seen in under three rounds, or in less than half the rounds other images were | No verdict. Not a judgement about the image |
| **Empty** | No labels and no predictions | Negatives, or images nobody labelled |

Speed is judged relative to this run, not at fixed epoch numbers: an image learned at round 5 is late in
a run where most images are learned by round 2, and early in one where most take ten. Fixed cut-offs put
nearly everything in one bucket for the short schedules people actually run.

## How to use it

**Not learned** and **Unstable** are the two groups worth your attention. Sort by them, open a few, and
you will usually find one of four things: a label that is wrong, a label your convention does not
actually want, an object that is genuinely invisible at this resolution, or a hard case worth keeping.

The first two are fixes. The third is a reason to raise the image size. The fourth is a reason to leave
the label alone — and Granum expects that answer often enough that "keep" is a first-class decision
everywhere.

## The image viewer

Click any card to open it full screen. Beyond the usual zoom and pan:

| Key | Action |
|---|---|
| <kbd>[</kbd> <kbd>]</kbd> | Step back and forward through the rounds |
| <kbd>Space</kbd> | Play the rounds as an animation |
| <kbd>L</kbd> / <kbd>G</kbd> | Show labels / show the model's boxes |
| <kbd>M</kbd> | Show only the mistakes |
| <kbd>K</kbd> / <kbd>R</kbd> | Keep the image / mark it for removal |
| <kbd>U</kbd> | Undo that decision |
| <kbd>F</kbd>, <kbd>+</kbd> <kbd>−</kbd> | Fit, zoom |

Watching the boxes move round by round is the quickest way to tell a hard example from a bad label: a
hard example is found late and then held; a bad label is fought the whole way, or found confidently and
then abandoned as the model learns the labelled version.

The round strip marks the threshold and the rounds where the image dropped below it, so an unstable image
shows its own history at a glance.

## Applying removals

Images marked for removal are collected; applying them writes a new version of the set without them and
records them in the dataset's removed set, where they can be put back.
→ [Isolate, remove and restore](/docs/guides/isolate-remove)

!!! note "Per-image F1 alone will not find every label error"
    An image with one wrong box among thirty correct ones scores well all run and never appears in
    *Not learned*. That is exactly what [Findings](/docs/guides/findings) is for: it works at the level of
    the individual box rather than the image.
