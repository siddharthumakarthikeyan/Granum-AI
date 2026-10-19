---
title: Manage runs in Python
summary: Record parameters, aggregate metrics and sample observations with explicit experiment lifecycle.
status: available
---

A Run groups one experiment's recipe, status and measurements. Create a new run when changing data,
model settings or evaluation rules that need to remain distinguishable in a comparison.

## Start and finish

```python
import granum

run = granum.init(
    "run-demo", "baseline", parameters={"seed": 7, "learning_rate": 0.001},
    constants={"purpose": "smoke-check"}, if_exists="raise",
)
run.log({"epoch": 0, "train_loss": 0.72})
run.set_status("finished")
print(run.url)
```

The example numbers are illustrative API inputs, not measured model results. In a real process,
record actual scalars and set failure/cancellation status when appropriate. Creating a Run does not
start a training worker.

## Handle names deliberately

`init` defaults to `if_exists="rename"`, which chooses an unused name. `raise` refuses a collision;
`reuse` opens an existing run. `overwrite` removes the existing run at that location and should only
be used when replacing that history is intended.

`init` also sets the active Run. `granum.log` and `collect_metrics` can use it implicitly, but explicit
`run=...` is clearer when managing multiple experiments. `get_active_run` and `set_active_run` control
that context. Reload a recorded run with `Run.from_url`.

## Add measurements

Use `run.log` or `granum.log` for aggregate scalars. Use `collect_metrics`, `Run.add_metrics` or
`MetricsTableWriter` for sample-level data. Manual metrics need the correct input table reference and
sample IDs; the writer cannot infer how an arbitrary external loader reordered outputs.

`metrics_tables()` returns the stored sample tables. `join_input()` on one metrics table combines
its measurements with the corresponding input rows. `aggregate_metrics()` reads the scalar history,
and `joined()` provides run-level joined data subject to its options.

## Record the recipe

Save the source table URLs, preprocessing, class order, seed, thresholds, model weights and hyperparameters
needed to repeat the result. `set_parameters` updates the parameter record but is not an independent
hyperparameter-search scheduler. Managed sweeps and compute queues are
[Not yet included](/docs/planned/compute).

Open the run in the dashboard and confirm joins before using [learning dynamics](/docs/guides/learning)
or [comparison](/docs/guides/compare).
