---
title: Verification and decisions
summary: The two kinds of judgement Granum records — is this image checked, and is this label right — and who made them.
---

Granum keeps two separate logs of human judgement. They answer different questions and are used in
different places.

## Image status: has someone checked this?

Every image is **unverified**, **verified**, or in **rework**.

| Status | Meaning | Set by |
|---|---|---|
| Unverified | Nobody has confirmed the labels. Every imported image starts here | Import; any edit; *Unverify* |
| Verified | A person looked at this image and its labels are right | *Verify* (<kbd>A</kbd> in the inspector) |
| Rework | Something is wrong; the comment says what | *Rework…*, which asks for a note |

Editing an image's labels sets it back to unverified — a verification is a statement about the labels as
they were when someone looked, so changing them retires it.

A typical loop: the reviewer sends an image to rework with "two pedestrians at the crossing are
unlabelled"; the annotator fixes it, replies "added both", and the image returns to unverified; the
reviewer checks it and verifies.

Status changes and comments are appended with the author's name and time and are never overwritten, so an
image's whole history stays readable in its thread. The reviewer name is whatever you type in the review
bar; it is kept in that browser.

## Findings decisions: is this label right?

Findings are about a specific label, not a whole image, and carry their own verdicts:

| Decision | Meaning |
|---|---|
| **Label is right** | Checked, and it stays: a valid hard case |
| **Fixing** | The label is wrong; recorded when you open the editor from a finding |
| **Ambiguous** | Nobody can say what the right label is |
| **Later** | Needs another look |
| **Exclude image** | This image should not be used for training |

Each decision records which finding it answered, which rule raised it, how strong the evidence was, and
the version of the rules that produced it. When the rules change, old decisions still say what they were
answering. → [Findings](/docs/guides/findings)

## Where it is kept

```
<project>/reviews/<dataset>.qa.jsonl   image statuses and comments
<project>/reviews/<dataset>.jsonl      findings and review decisions
<project>/reviews/<dataset>.ships.jsonl dataset versions
```

All three are append-only JSON Lines, keyed by **image reference** rather than row number. That is what
makes a verification survive: delete ten images, create four versions, and the judgement someone made
about a given photograph is still attached to that photograph.

!!! warning "There is no authentication"
    Reviewer names are self-reported and anyone who can reach the service can verify, edit or create a
    dataset version. Granum is a single-user desktop application today; treat the names as a record of
    who did what among people you trust, not as an access control system.
