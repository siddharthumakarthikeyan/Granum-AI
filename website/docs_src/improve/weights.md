---
title: Control sample weights
summary: Exclude or emphasise training samples while preserving the underlying dataset and evaluation rules.
status: available
---

A sample weight records how strongly an input should participate in sampling. Granum normally adds a
weight column initialised to 1. A zero weight excludes the sample from Granum samplers that honour
weights; the source row can still exist in the table.

## Change weights as a revision

```python
from granum import Table

table = Table.from_names("inspection", "train", "initial")
weighted = table.set_weights({0: 0.0, 2: 2.0})
print(weighted.url)
```

This example excludes row 0 and emphasises row 2 in a new version. Replace the names and indices
with the dataset you inspected. Pin the resulting URL when you want training to use that exact choice.

Use the workspace's editable weight column when reviewing samples visually. Save changes and inspect
the resulting revision. Exclusion by weight, recoverable removal and permanent deletion have different
consequences; choose the operation that matches your intent.

## Choose a sampler

| Sampler | Meaning |
|---|---|
| `create_weighted_sampler` | Draw proportional to positive weight |
| `create_random_sampler` | Shuffle nonzero-weight samples once |
| `create_sequential_sampler` | Visit nonzero-weight samples in order |
| `create_repeat_by_weight_sampler` | Repeat according to the integer weight convention |

Pass the sampler to a PyTorch DataLoader and do not also request DataLoader shuffling. Merely storing
a weight column does not force an arbitrary external training framework to use it. Verify the actual
sampler or exporter used by your recipe.

## Keep evaluation interpretable

Metrics collection includes zero-weight rows by default. Pass `exclude_zero_weights=True` only when
that is the evaluation population you intend, and record the choice. Changing validation weights or
membership can make two run scores incomparable.

A large loss or long embedding trajectory can justify review, but it is not automatically a reason to
increase weight. Label errors can receive more training emphasis too. Inspect the sample, change one
factor deliberately, and use [comparison](/docs/guides/compare) to evaluate the result. Automatic
optimised coreset selection is [Not yet included](/docs/planned/advanced-analysis#sampling-and-selection).
