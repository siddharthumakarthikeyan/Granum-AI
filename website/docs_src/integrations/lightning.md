---
title: Connect Lightning
summary: Record validation and test outputs from Lightning while preserving source sample identities.
status: available
---

The Lightning callback collects per-sample outputs during validation and test. Install the `lightning`
extra from your source checkout and configure your usual Lightning model and Trainer.

## Prepare indexed inputs

```python
from granum.integration.lightning import IndexedDataset, Evaluation, GranumCallback

# load_sample_dict returns a dictionary suited to your model.
eval_dataset = IndexedDataset(valid_table.with_transform(load_sample_dict))
callback = GranumCallback(
    run,
    validation=[Evaluation(valid_table, collectors, "val")],
    test=[Evaluation(test_table, test_collectors, "test")],
)
```

Pass this dataset through an appropriate DataLoader and include the callback when constructing the
Lightning Trainer. The transform returns a dictionary, and the collator must retain the added identity
fields. Those fields allow collection to match outputs to source samples even when loader order changes.

## Return model observations

Validation and test steps can return a logits tensor, a dictionary containing `logits`, or a Granum
`Prediction`. Use `output_transform(outputs, batch)` when your module returns a different structure.
Preserve one output per identified sample. Model geometry must map back to source coordinates before
vision collectors evaluate it.

Sanity-validation passes are skipped. `collect_every` sets the interval, and `close_run=True` opts
into callback management of completion or failure. Otherwise, finish the Run in your own process.

## Check distributed behaviour

The callback gathers distributed measurements and removes sampler-padding duplicates only when
repeated metrics agree. Conflicting observations for one sample are an error rather than an arbitrary
choice of one value. This matters when stochastic transforms are accidentally left in evaluation.

Development checks include real CPU fit/test and two-process CPU/Gloo validation. GPU training and
other distributed strategies still require qualification for the intended environment. Run a small
known dataset and check counts and joins before scaling.

## Continue the workflow

Open the run, inspect the source images and confirm epoch labels. Use
[per-sample learning](/docs/guides/learning) for repeated observations and
[comparison](/docs/guides/compare) when evaluating a candidate.
A packaged Lightning semantic-model tutorial is **Not yet included**; the callback's generic output
contract is available for your own model pipeline.
