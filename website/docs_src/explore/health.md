---
title: Check dataset health
summary: Combine import, duplication, annotation and review evidence before creating a training version.
status: available
---

Health gathers the checks that already exist around a dataset into a readiness view. It helps you
choose the next action before training, while the linked screens provide the evidence and editing
tools needed to resolve it.

## Read the status

A blocking result means a basic condition needs correction, such as an unusable split. A warning
asks for investigation, such as excessive copies, rare classes, unreviewed model drafts or labels
flagged by a model. An OK result means that particular check passed under its stated rule.

Read the threshold and evidence behind each row. A result based on an import is different from one
that requires embeddings or a completed model check. A check that has not run cannot establish the
quality of the dataset.

## Work through a dataset

1. Finish import and read its [preflight report](/docs/reference/preflight).
2. Run the [duplicate and leakage inspection](/docs/explore/duplicates) when appropriate.
3. Check class and object distributions in Images, including validation and test separately.
4. Review model-drafted annotations and investigate [Findings](/docs/guides/findings).
5. Return to Health, follow unresolved checks and confirm the intended split membership.
6. Create a named dataset version and record the reason for the selection.

## Health and approval

Health is an operational summary. [Approval](/docs/concepts/verification) is a separate gate over
exact contents and matching review evidence. Passing a health threshold does not approve a version,
and approving a version does not prove that every label is objectively correct.

Use the project's intended criteria when deciding which warnings are acceptable. A deliberately
rare class may need more representative data rather than removal; a model's weak recall can explain
many findings without proving that the labels are wrong.

## When results change

New imports, label edits, moved images and new model measurements can change the conclusion. Recheck
the evidence before approving a newly created version or comparing it with an earlier baseline.
Keep the earlier version and run so the change remains traceable through
[comparison](/docs/guides/compare).
