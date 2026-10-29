---
title: Connect a PyTorch loop
summary: Use table views, weighted samplers and explicit metric passes with an existing PyTorch model.
status: partial
---

Granum can sit around an ordinary PyTorch training loop. A table view loads or transforms a sample;
a sampler chooses training examples; a separate collection pass records model behaviour against the
canonical inputs.

## Prepare data

Create a [table](/docs/python/tables), then define a module-level transform for the format your model
expects. A training transform may augment inputs. A metric transform should return a dictionary and
keep the source labels and identity meaningful.

```python
from torch.utils.data import DataLoader
import granum

# load_training_sample is your module-level transform.
view = train_table.with_transform(load_training_sample)
loader = DataLoader(view, batch_size=32,
                    sampler=granum.create_weighted_sampler(train_table))
```

Do not combine a sampler with `shuffle=True`. For multiple worker processes, the transform must be
picklable. Keep a separate clean evaluation view instead of measuring randomly augmented training
samples as though they were canonical observations.

## Record training and evaluation

Start a run with `granum.init`, store your recipe in `parameters`, and log aggregate scalars with
`granum.log`. At the intended intervals, use `collect_metrics` with a task-appropriate collector and
`Predictor(model, preprocess=...)`. Include the split and epoch.

`Predictor` supports model device placement, evaluation mode and optional layer hooks. Resolve layer
indices against `model.named_modules()` when collecting activations; they are not permanent layer
names across different architectures. Remove hooks when the predictor is no longer needed.

## Inspect and iterate

Open the run to confirm input joins, labels and predictions before a long training session. Freeze
the input table URLs in the run parameters. After editing labels, create a new dataset version and
start a new experiment so the comparison retains both inputs.

The repository's CIFAR-10 and detection examples provide concrete loops. The
[recipe catalogue](/docs/measure/recipes) lists what is included. Automatic conversion of an arbitrary
PyTorch Dataset object is **Not yet included**; use explicit rows or a `TableWriter` to preserve the
fields and identity you intend to analyse.
