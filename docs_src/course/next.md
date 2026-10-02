---
title: 12. Move to your own project
summary: Turn the course into a repeatable team practice with a labelling policy, independent evaluation data, review criteria and rollout evidence.
---

**Goal:** replace the course's artificial small scope with a justified real-project plan.
You should have completed [approval/export](/docs/course/handoff) and [restore rehearsal](/docs/course/backup),
or deliberately recorded which optional steps you skipped.

## What you have actually demonstrated

| Course outcome | Evidence | Boundary |
|---|---|---|
| Reproducible input | Attributed 120-image archive, checksum and import report | A subset, not a representative benchmark |
| Traceable experimentation | Frozen 96/24 baseline and recorded recipes | No independent test; one seed |
| Editor recovery | Real recovered draft; original label restored before save | Same browser profile/origin; not a server backup |
| Human review | Two inspected images and explicit comments | Not all 120 images reviewed |
| Weak-model interpretation | Real run histories, evaluation and comparison | Neither model accepted for deployment |
| Scoped handoff | Approved two-image excerpt and copied COCO export | Too small for useful training/evaluation |
| Recovery rehearsal | Separate restore, matching 120 image hashes/sizes and inspected UI | Local Linux rehearsal, not all-platform certification |

This is a useful product workflow even when the model result is bad: it preserves enough context to
explain what happened and decide the next action instead of treating a chart as truth.

## Step 1: write the task and labelling policy

Start a **new project** for your own data. State what the detector should find, where it will run and
what an unacceptable miss or false alarm means. Define classes, minimum visible extent, occlusion,
truncation, crowds, ambiguous objects and when a reviewer must escalate.

Include representative positive, negative and difficult examples. Have two domain reviewers resolve
disagreements on an initial sample before large-scale annotation. Do not assume an imported category
name expresses your organisation's policy.

## Step 2: establish provenance and split boundaries

1. Record data origin, collection dates, permitted uses and required attribution.
2. Identify group units—such as subject, location, flight, recording or day—that must not leak across
   train, validation and test.
3. Preserve an independent test set for a defined final evaluation procedure. Do not repeatedly tune
   on it or copy validation and rename the copy test.
4. Check exact duplicates and plausible near-duplicate/group leakage. Treat unknown grouping as a
   documented risk, not an automatic pass.
5. Record data coverage and underrepresented conditions. Aggregate metrics can hide a critical slice.

## Step 3: define review and release criteria

Decide who may edit, review, approve and manage the workspace. Specify what reviewers must inspect
before verification and which unresolved examples may be isolated with a reason. For a released
selection, all included contents must satisfy the approval gate and your human policy.

Keep an exploratory path for experiments. Do not redefine “approved” to mean “we needed to start a
training job.” Protect external media from writers and retain a recoverable copy.

## Step 4: plan the modelling experiment

- Freeze a baseline before changing the data or recipe.
- Specify the hypothesis and one planned intervention, or explicitly list multiple changed factors.
- Record model/checkpoint, image size, optimizer/schedule, augmentation, seed and library/runtime versions.
- Use the same evaluation images, labels, class mapping and scoring policy for a controlled comparison.
- Report precision/recall at the relevant operating point, AP under a named evaluator, class/slice
  support, changed image outcomes and operational costs.
- Use repeated runs and appropriate statistical analysis where a reliable gain matters. A fixed
  dashboard tolerance is not a substitute for uncertainty estimation.

Do not remove hard examples to improve a headline metric. If a label is truly wrong, correct it with
review evidence and explain the changed evaluation version when comparing models.

## Step 5: qualify the actual rollout

Documentation and passing source tests do not prove an installer works on a customer's clean machine.
Before distributing a pilot artifact, retain evidence for:

1. Exact source revision, dirty/clean state, dependencies and generated dashboard stamp.
2. Artifact checksum, manifest and intended platform.
3. Install, launch, update/uninstall and restore on the target platform.
4. A representative import/review/approval/export flow and, if promised, the intended GPU/model recipe.
5. Documented support boundaries, measured scale limits and a recovery owner.
6. TLS/accounts/roles and audit handling for any shared service.
7. Correct customer-facing access and pricing terms. Current unrestricted-alpha enforcement is not a
   timed paid trial or an open-source licence.

The course's Linux source recording and small GPU jobs do not check every item above. Consult
[Limits](/docs/reference/limits) and [Operate a pilot workspace](/docs/guides/operations).

## A decision note to keep with each experiment

Use a short structured note in your project records:

| Field | Write down |
|---|---|
| Question | What decision will this experiment support? |
| Inputs | Frozen dataset version, split identities and media-integrity baseline |
| Change | Which data/recipe factor changed, and which remained fixed? |
| Results | Named evaluator, thresholds, metrics, support, image/slice outcomes and uncertainty |
| Review | Who inspected which contents, unresolved policy questions and exclusions |
| Decision | Keep investigating, accept under defined conditions, or reject—with a reason |
| Delivery | Approved release scope, export format, attribution and backup/restore receipt |

For this course the honest decision is **continue investigation; do not deploy either model**.

## Where to go next

<div class="doc-cards">
<a class="doc-card" href="/docs/guides/python"><strong>Use your own training loop</strong><span>Record versioned inputs and per-sample evidence through the Python SDK.</span></a>
<a class="doc-card" href="/docs/guides/findings"><strong>Investigate label findings</strong><span>Understand evidence, competence and manual review decisions.</span></a>
<a class="doc-card" href="/docs/guides/operations"><strong>Operate the pilot</strong><span>Recovery, access roles, integrity, backups and upgrade rehearsal.</span></a>
<a class="doc-card" href="/docs/reference/screens"><strong>Use the reference</strong><span>Look up screens, controls and related task guides.</span></a>
</div>

## What we learn

The repeatable practice is not “import, press train, believe the score.” It is: preserve provenance,
inspect evidence, state the comparison boundary, review the intended contents, make a scoped decision
and verify the recovery path.

## Checkpoint

Before replacing the sample with your own data, write the task, labelling policy, grouping/split rule,
review criteria and recovery plan. If any is unknown, name an owner and keep the project exploratory.

## If you cannot complete the checklist

Reduce the rollout scope rather than overclaiming. A supervised local pilot with documented limits is
more defensible than describing untested installers, shared security or weak-model results as production
ready. Preserve the open questions so the next iteration can address them.