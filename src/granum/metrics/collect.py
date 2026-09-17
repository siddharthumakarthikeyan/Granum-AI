"""``collect_metrics`` -- the canonical way to record per-sample model behaviour.

The loop here is deliberately an *evaluation* loop: canonical row order, no shuffling,
no augmentation. Per-sample metrics only mean something if row *i* of the metrics table
describes row *i* of the input Table, and a shuffled loader silently destroys that.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any

from granum.core.objects.run import EXAMPLE_ID_COLUMN, Run, get_active_run
from granum.core.objects.table import WEIGHT_COLUMN, Table, TableView
from granum.core.schemas import EpochSchema, Schema, StringSchema
from granum.errors import GranumError
from granum.metrics.collectors import MetricsCollector
from granum.metrics.predictor import Predictor


class CollectionError(GranumError):
    """Metrics collection could not proceed."""


def _resolve_table(source: Table | TableView) -> Table:
    return source.table if isinstance(source, TableView) else source


def iter_batches(
    source: Table | TableView,
    batch_size: int = 32,
    *,
    exclude_zero_weights: bool = False,
) -> Iterator[tuple[list[int], dict[str, list[Any]]]]:
    """Yield ``(example_ids, batch)`` in canonical order.

    ``example_ids`` are indices into the underlying Table, so they stay correct even
    when zero-weight rows are skipped.
    """
    table = _resolve_table(source)
    if batch_size < 1:
        raise CollectionError("batch_size must be at least 1")

    include: list[int] = []
    for index in range(len(table)):
        if exclude_zero_weights and WEIGHT_COLUMN in table.schema:
            if float(table[index][WEIGHT_COLUMN]) == 0.0:
                continue
        include.append(index)

    for start in range(0, len(include), batch_size):
        chunk = include[start : start + batch_size]
        samples = [source[i] for i in chunk]
        if samples and not isinstance(samples[0], dict):
            raise CollectionError(
                "a transform used for metrics collection must return a dict per sample "
                "so columns stay addressable"
            )
        keys: list[str] = []
        for sample in samples:
            for key in sample:
                if key not in keys:
                    keys.append(key)
        batch = {key: [sample.get(key) for sample in samples] for key in keys}
        yield chunk, batch


def collect_metrics(
    table: Table | TableView,
    metrics_collectors: Iterable[MetricsCollector | Callable[..., dict[str, list[Any]]]],
    *,
    predictor: Predictor | Callable[[Any], Any] | None = None,
    model: Any = None,
    run: Run | None = None,
    split: str | None = None,
    constants: dict[str, Any] | None = None,
    batch_size: int = 32,
    exclude_zero_weights: bool = False,
    column_schemas: dict[str, Schema] | None = None,
    description: str = "",
):
    """Run an inference pass, collect per-sample metrics, and attach them to a Run.

    Returns the written ``MetricsTable``.
    """
    target_run = run or get_active_run()
    if target_run is None:
        raise CollectionError("no active Run -- call granum.init() first, or pass run=")

    source_table = _resolve_table(table)
    collectors = list(metrics_collectors)
    if not collectors:
        raise CollectionError("pass at least one metrics collector")

    if predictor is None and model is not None:
        predictor = model if isinstance(model, Predictor) else Predictor(model)

    schemas: dict[str, Schema] = {}
    for collector in collectors:
        if isinstance(collector, MetricsCollector):
            schemas.update(collector.column_schemas())
    schemas.update(column_schemas or {})

    collected: dict[str, list[Any]] = {EXAMPLE_ID_COLUMN: []}

    for example_ids, batch in iter_batches(
        table, batch_size=batch_size, exclude_zero_weights=exclude_zero_weights
    ):
        prediction = predictor(batch) if predictor is not None else None

        produced: dict[str, list[Any]] = {}
        for collector in collectors:
            result = collector(batch, prediction)
            if not isinstance(result, dict):
                raise CollectionError(
                    f"{type(collector).__name__} returned {type(result).__name__}, "
                    f"expected a dict of column name to list of values"
                )
            for name, values in result.items():
                if len(values) != len(example_ids):
                    raise CollectionError(
                        f"{type(collector).__name__} returned {len(values)} values for "
                        f"{name!r} but the batch has {len(example_ids)} samples -- "
                        f"metrics would not line up with their samples"
                    )
                produced[name] = list(values)

        collected[EXAMPLE_ID_COLUMN].extend(example_ids)
        for name, values in produced.items():
            collected.setdefault(name, []).extend(values)

        expected = len(collected[EXAMPLE_ID_COLUMN])
        ragged = [name for name, values in collected.items() if len(values) != expected]
        if ragged:
            raise CollectionError(
                f"collectors disagreed about which columns they produce: {ragged} "
                f"are missing values for some batches"
            )

    if len(collected[EXAMPLE_ID_COLUMN]) == 0:
        raise CollectionError(
            "nothing was collected -- the table is empty, or every row was excluded "
            "by exclude_zero_weights"
        )

    run_constants = dict(constants or {})
    if split is not None:
        run_constants["split"] = split

    # ``summary_only`` describes the whole table (per-image scores without boxes), so it
    # is recorded as a table constant rather than repeated as a column.
    summary_only = bool(run_constants.pop("summary_only", False))
    for name, value in run_constants.items():
        if name not in collected:
            is_epoch = name in {"epoch", "iteration"}
            collected[name] = [value if is_epoch else str(value)] * len(collected[EXAMPLE_ID_COLUMN])
            schemas.setdefault(name, EpochSchema() if is_epoch else StringSchema())

    table_constants: dict[str, Any] = {"split": split} if split else {}
    if summary_only:
        table_constants["summary_only"] = 1
    return target_run.add_metrics(
        collected,
        foreign_table_url=source_table.url,
        schema=schemas,
        constants=table_constants or None,
        description=description,
    )
