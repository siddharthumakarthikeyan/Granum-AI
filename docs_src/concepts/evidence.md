---
title: What the evidence is worth
summary: How Granum turns a model's behaviour into candidates for review — and where it refuses to draw conclusions.
---

Three features read the same underlying record — what the model predicted on each image in each round —
and answer three different questions.

| Feature | Question | Unit |
|---|---|---|
| [Per-image learning](/docs/guides/learning) | Which images did the model struggle with? | one image |
| [Findings](/docs/guides/findings) | Which *labels* did the model disagree with? | one box |
| [Compare runs](/docs/guides/compare) | What changed between two runs? | one image, one class, one dataset |

## The reasoning, and its limit

A model trained on mostly-correct data will fit the correct labels sooner and more stably than the
incorrect ones. So labels the model keeps fighting — a confident prediction where nothing is labelled, a
confident prediction of a different class, a label it never finds — are enriched for label errors.

Enriched, not equal to. The same signal is produced by rare-but-valid examples, genuinely hard cases,
occlusion, unusual lighting, and objects your convention deliberately does not label. This is why
Granum's language is *candidate*, *worth checking*, *possible*, and why every finding carries the
evidence behind it instead of a verdict. A tool that told you "these 340 labels are wrong" would be
easier to sell and would be lying.

## Three guards Granum applies

**Wait until the model is competent.** Early in training a model misses everything, which says nothing
about the labels. Findings ignore rounds before the model has reached 90% of its best recall on that set.

**Require recurrence.** One odd round is noise. A finding must appear in at least two rounds and in a
fifth of the rounds judged — half, when the only evidence is that the model fails to find a label, which
is weaker evidence than a confident prediction.

**Discount the training set.** A model learns the labels it is trained on, including the wrong ones, so
a genuine error on the training set often stops showing up in later rounds. Evidence from validation and
test sets is stronger, and Granum says so on the page and ranks held-out sets first.

## What Granum will not claim

- **That a finding is an error.** It is a place to look, with the reason attached.
- **That your edits caused a score to improve.** When the data changed between two runs, the comparison
  is observational: it reports what moved alongside the change, and says that plainly.
- **That a small difference is real.** With one seed per run, a difference inside the declared tolerance
  is reported as too close to call, because nobody has measured the run-to-run spread.
- **That a slice moved** when it holds a handful of labels. Small slices are shown with their support and
  marked as too few to call.

!!! note "Where this comes from"
    The per-image learning categories follow the training-dynamics literature — *Dataset Cartography*
    (Swayamdipta et al., 2020) and *An Empirical Study of Example Forgetting* (Toneva et al., 2019) —
    with learning speed judged relative to the run rather than at fixed epoch numbers, because fixed
    cut-offs put nearly everything in one bucket for the short runs people actually do.
