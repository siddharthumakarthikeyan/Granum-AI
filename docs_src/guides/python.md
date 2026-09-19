---
title: Use Granum from Python
summary: The same objects the app uses, for scripted imports, custom metrics and your own training loop.
---

Everything the dashboard does sits on a small Python API, and the app is a client of it like any other.
Use it when your work is repetitive, when your training loop is your own, or when the metric you care
about is not one Granum computes.

```python
import granum
from granum import Table

granum.set_config(granum.Config.load(overrides={"project-root-url": "~/granum"}))

table = Table.from_coco("data/train/_annotations.coco.json", "data/train",
                        project_name="aerial", dataset_name="human_aerial", table_name="train")
print(len(table), table.columns)
```

## Tables

A `Table` is one version of one set: rows of samples, a schema that knows what each column means, and a
parent. Editing returns a new table rather than changing this one.

```python
fixed = table.apply_edits(values={"bbs": {4172: corrected_boxes}})   # a new version
subset = table.filter(lambda row: row["bbs"]["instances"])           # images with labels
latest = table.latest()                                             # newest safe revision
```

## Runs and metrics

```python
run = granum.init("aerial", "baseline", parameters={"framework": "yolo", "epochs": 12})

for epoch in range(12):
    ...  # your training loop
    granum.log({"epoch": epoch, "map50": score}, run=run)
    granum.collect_metrics(
        valid, [granum.DetectionMetricsCollector("bbs", value_map=valid.schema["bbs"].value_map)],
        predictor=my_predictor, constants={"epoch": epoch}, split="valid",
    )
```

`collect_metrics` writes one metrics table per call, joined to the input table by row position, with the
predicted boxes and per-image counts the dashboard reads. Anything you collect this way appears in the
app: the run views, per-image learning and — when the predictions are stored every round — Findings.

## Training and export

```python
from granum import export_yolo
export_yolo({"train": train, "val": valid}, "/tmp/export", image_strategy="symlink")
```

The bundled trainer is a module, so a scripted run is one command:

```bash
python -m granum.training.train --project-root ~/granum --project aerial \
    --train-table URL --valid-table URL --run-name nightly \
    --family yolo --version yolo26m.pt --epochs 30 --track-learning
```

## The service API

The dashboard talks to a local REST service, and so can you — `/api/projects`, `/api/images`,
`/api/run/findings`, `/api/runs/compare` and the rest. It listens on `127.0.0.1` only, checks the `Host`
header, and refuses cross-origin writes; it is for local tooling, not a shared backend.

!!! note "Where the full API reference lives"
    This page is an orientation, not a reference. The complete Python and service documentation ships
    with the source — `docs/python-sdk.md`, `docs/service.md` and `docs/architecture.md` — and every
    public function carries a docstring that explains why it behaves as it does.
