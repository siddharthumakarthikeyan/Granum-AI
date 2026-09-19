---
title: Work the Findings queue
summary: A ranked list of labels worth checking, the evidence for each, and a decision you record.
---

**Findings** takes a finished run and produces a ranked queue of *individual labels* the model
persistently disagreed with, each with the evidence behind it and a decision you record. It is the
screen that turns "the model is worse than I expected" into an afternoon of specific, finite work.

## The four rules

| Rule | What was seen | What to do |
|---|---|---|
| **Missing label** | A confident prediction where nothing is labelled, round after round | Add a box if the object should be labelled |
| **Wrong class** | A confident prediction of another class sitting on your label | Change the class if your label is wrong |
| **Loose box** | A confident prediction of the right class overlapping your box, but not enough to match | Tighten the box if it does not fit |
| **Not found** | A label the model never finds, with none of the above explaining why | Check it; keep it if it is a valid hard case |

Rules are versioned. Every decision records which version of the rules raised the finding it answered, so
when the rules change, old decisions still say what they were about.

## What is judged, and what is not

**Only rounds where the model was competent.** The window starts at the first round where the set's
recall reached 90% of its best. Before that the model misses everything, which says nothing about your
labels.

**Only what recurs.** A finding needs at least two rounds and at least a fifth of the judged window —
half, for *Not found*, because a miss is weaker evidence than a confident prediction.

**Ranked by strength.** The score is how often it was seen multiplied by how confident the model was.
A confident wrong class seen in every round outranks a label missed in half of them.

## Held-out sets first

The page opens on a held-out set — validation or test — because the evidence there is stronger. On the
training set the model learns your labels as they are, including the wrong ones, so a genuine error often
stops appearing in later rounds. The training tab shows a notice saying exactly that, and findings
carry a note when the model stopped raising them ("last seen in round 7").

## Working the queue

Cards show a close-up crop around the finding with the label and the model's box drawn on it. Filter by
rule and by whether you have decided. The progress bar estimates the work left at twenty seconds a
finding — an estimate, and labelled as one.

Click a card for the full-screen reviewer:

| Key | Action |
|---|---|
| <kbd>←</kbd> <kbd>→</kbd> | Previous / next image |
| <kbd>↑</kbd> <kbd>↓</kbd> | Move between the findings on this image |
| <kbd>Z</kbd> | Close-up or whole image |
| <kbd>C</kbd> | **Label is right** — checked, a valid hard case |
| <kbd>F</kbd> | **Fix** — records "fixing" and opens this image in the editor |
| <kbd>A</kbd> | **Ambiguous** — nobody can say what is right |
| <kbd>L</kbd> | **Later** — needs another look |
| <kbd>X</kbd> | **Exclude image** — should not be used for training |
| <kbd>U</kbd> | Undo the decision |

Decisions are appended to the dataset's review log with the rule, the strength of the evidence and the
rules version.

## Reading the evidence honestly

Each finding states what was seen in plain terms: *"The model predicts person here in 9 of 11 rounds
(confidence 0.62–0.88), and nothing is labelled here."* That sentence is the whole claim. It is not a
verdict that your label is wrong, and about a fifth of the time — more in unusual datasets — the right
answer is **Label is right**.

That is a feature. A queue that was always right would be a labelling model, and you would not need to
look. → [What the evidence is worth](/docs/concepts/evidence)

!!! note "If the page is empty"
    Three reasons, and the page says which: the run did not record predictions per round; the run was
    cancelled before it produced any; or the model never became competent on that set, so no round was
    judged. The third is common with short schedules on small datasets — train longer, then come back.
