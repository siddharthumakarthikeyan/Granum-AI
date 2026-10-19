---
title: Numbers labels and text
summary: Represent tabular samples with explicit types and use them in filters, charts and model metrics.
status: available
---

A Granum table is a set of typed columns. Rows can describe images, model inputs, measurements or
ordinary tabular samples. Images are optional in the Python data model; the Images workflow expects
an image column.

## Create a typed table

```python
from granum import Table
from granum.schemas import Float32Schema, StringSchema, CategoricalLabelSchema

samples = Table.from_dict_data(
    {"record": ["a", "b", "c"], "signal": [0.2, 0.8, 0.5], "label": [0, 1, 0]},
    schema={
        "record": StringSchema(),
        "signal": Float32Schema(),
        "label": CategoricalLabelSchema(classes=["normal", "review"]),
    },
    project_name="tabular-demo", dataset_name="samples",
)
print(samples.summary("signal"))
```

The default weight column starts at 1. An explicit categorical schema associates stored integer IDs
with meaningful names, so labels can be displayed and edited consistently.

## Choose types deliberately

Boolean values support true/false filtering; numerical columns support ranges and scatter plots.
Categorical columns carry a value map. Strings hold identifiers or text, but free text is not a
ready-made semantic-search index. Fixed-size vectors belong in an `EmbeddingSchema`.

`Table.from_csv` reads CSV fields as strings. Convert numeric values before creating the table, or
use a typed pandas/Parquet input. A column that looks numeric in a text file can otherwise remain
unsuitable for a chart. Preserve missing measurements as missing rather than substituting zero.

## Inspect and update

Open the table workspace to sort columns, narrow ranges and inspect selected rows. Use
`table.summary(column)` for counts, missing values, common values and applicable numeric statistics.
To correct a value, call `set_values` or save an edit in the workspace; both create a new revision.

Read [schemas](/docs/python/schemas) for types and display metadata, and
[calculated columns](/docs/explore/calculations) for derived values. Tokenisation and text-model
prediction can be supplied through [Hugging Face](/docs/integrations/hugging-face). Dedicated retrieval
analysis and question-to-chunk relationships are [Not yet included](/docs/planned/advanced-analysis#retrieval-and-cross-table-analysis).
