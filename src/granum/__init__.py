"""Granum -- inspect and improve ML training data sample by sample."""

from __future__ import annotations

from granum import metrics, schemas
from granum.core.config import Config, get_config, set_config
from granum.core.datatypes import BoundingBoxes2D, box_iou, match_boxes, nms
from granum.core.index import Index, get_index, set_index
from granum.core.layout import ProjectLayout
from granum.core.objects.base import load_object
from granum.core.objects.run import (
    MetricsTable,
    Run,
    RunError,
    get_active_run,
    init,
    log,
    set_active_run,
)
from granum.core.objects.table import Table, TableView
from granum.core.url import (
    Url,
    get_registered_url_aliases,
    register_url_alias,
    unregister_url_alias,
)
from granum.errors import (
    AliasConflictError,
    ConfigError,
    GranumError,
    ImmutableError,
    ObjectNotFoundError,
    SchemaError,
    TableError,
)
from granum.formats.coco import export_coco
from granum.formats.yolo import export_yolo
from granum.metrics.collect import collect_metrics
from granum.samplers import (
    create_random_sampler,
    create_repeat_by_weight_sampler,
    create_sequential_sampler,
    create_weighted_sampler,
)
from granum.writers import MetricsTableWriter, TableWriter

__version__ = "0.1.0"

__all__ = [
    "Config",
    "Index",
    "MetricsTable",
    "MetricsTableWriter",
    "ProjectLayout",
    "Run",
    "Table",
    "TableView",
    "TableWriter",
    "Url",
    "__version__",
    "BoundingBoxes2D",
    "box_iou",
    "collect_metrics",
    "export_coco",
    "export_yolo",
    "match_boxes",
    "nms",
    "create_random_sampler",
    "create_repeat_by_weight_sampler",
    "create_sequential_sampler",
    "create_weighted_sampler",
    "get_active_run",
    "get_config",
    "get_index",
    "init",
    "load_object",
    "log",
    "metrics",
    "set_active_run",
    "set_index",
    "get_registered_url_aliases",
    "register_url_alias",
    "schemas",
    "set_config",
    "unregister_url_alias",
    # errors
    "AliasConflictError",
    "ConfigError",
    "GranumError",
    "ImmutableError",
    "ObjectNotFoundError",
    "RunError",
    "SchemaError",
    "TableError",
]
