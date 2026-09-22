"""Taking images out of a set, and putting them back.

Removing images from ``train`` or ``valid`` writes a new version of that set without
them, so nothing is lost: earlier versions still hold the images. The removed rows are
also collected in the dataset's ``removed`` set, one version per change, each row
recording which set and version it came from and why it was removed. From there an
image can be put back into the newest version of the set it came from.

Images are identified by their image reference, as review decisions are: row positions
change between versions, the image does not. Every removal and restore is also recorded
in the dataset's review log, so who decided what stays auditable.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from granum.core.config import Config, get_config
from granum.core.layout import ROW_CACHE_FILENAME, ProjectLayout, sanitize
from granum.core.objects.base import write_object_payload
from granum.core.objects.table import Table, _unique_url
from granum.core.reviews import ReviewLog
from granum.core.schemas import StringSchema, TableSchema
from granum.core.url import sample_key
from granum.errors import TableError

REMOVED_SET = "removed"
#: Images set aside for now, e.g. so the rest of a dataset can ship; they go back later.
ISOLATED_SET = "isolated"
#: Sets that hold images taken out of the others, rather than data to train or check on.
HOLDING_SETS = (REMOVED_SET, ISOLATED_SET)
#: Columns the removed set adds to the rows it holds.
REMOVED_COLUMNS = ("removed_from", "removed_from_version", "removed_reason", "removed_at")
#: Producer op of the frozen copy of a set a dataset version was created from. These live
#: outside the dataset's version history: they are never the newest version of a set.
RELEASE_OP = "release"


class CurationError(TableError):
    """Images could not be removed or put back."""


def image_column(table: Table) -> str:
    from granum.core.schemas import ImageSchema

    for name in table.columns:
        if isinstance(table.schema[name], ImageSchema):
            return name
    if "image" in table.columns:
        return "image"
    raise CurationError(f"{table.name} has no image column to identify images by")


def write_version(
    *,
    project_name: str,
    dataset_name: str,
    base_name: str,
    name: str,
    arrow: pa.Table,
    schema: TableSchema,
    parents: tuple[Any, ...],
    op: str,
    args: dict[str, Any],
    description: str,
) -> Table:
    """A table version with an explicit set name and parents (``Table._derive`` always
    inherits both from the table it is called on)."""
    layout = ProjectLayout(get_config().project_root)
    target = _unique_url(layout.tables_dir(project_name, dataset_name), name)
    table = Table(
        url=target,
        name=target.name,
        base_name=base_name,
        project_name=project_name,
        dataset_name=dataset_name,
        schema=schema,
        row_count=arrow.num_rows,
        parents=parents,
        producer={"op": op, "args": args},
        description=description,
        arrow=arrow,
    )
    target.mkdir()
    pq.write_table(arrow, (target / ROW_CACHE_FILENAME).path, filesystem=target.fs)
    write_object_payload(target, table.to_dict())
    return table


def is_release(table: Table) -> bool:
    return table.producer.get("op") == RELEASE_OP


def write_release_set(source: Table, keep: Iterable[str], *, release_id: str, release_name: str) -> Table:
    """A frozen copy of ``source`` holding only the images in ``keep``, for one dataset version.

    Written under the project's ``releases`` folder, not the dataset's tables, and marked
    with :data:`RELEASE_OP`, so it never becomes the working version of its set.
    """
    wanted = set(keep)
    images = source.to_arrow().column(image_column(source)).to_pylist()
    rows = [i for i, image in enumerate(images) if image in wanted]
    layout = ProjectLayout(get_config().project_root)
    folder = layout.project(source.project_name) / "releases" / sanitize(source.dataset_name) / release_id
    target = _unique_url(folder, source.base_name)
    arrow = source.to_arrow().take(pa.array(rows, type=pa.int64()))
    table = Table(
        url=target,
        name=target.name,
        base_name=source.base_name,
        project_name=source.project_name,
        dataset_name=source.dataset_name,
        schema=source.schema,
        row_count=arrow.num_rows,
        parents=(source.url,),
        producer={"op": RELEASE_OP, "args": {"release": release_id, "count": len(rows)}},
        description=f"{release_name}: {_plain(len(rows), 'verified image')} of {source.name}",
        arrow=arrow,
    )
    target.mkdir()
    pq.write_table(arrow, (target / ROW_CACHE_FILENAME).path, filesystem=target.fs)
    write_object_payload(target, table.to_dict())
    return table


def _removed_schema(source: Table) -> TableSchema:
    schema = source.schema
    for column in REMOVED_COLUMNS:
        if column not in schema:
            schema = schema.with_column(column, StringSchema(writable=False))
    return schema


def _plain(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def remove_images(
    source: Table,
    samples: Iterable[str],
    *,
    removed_set: Table | None,
    reason: str = "",
    reasons: dict[str, str] | None = None,
    config: Config | None = None,
    holding: str = REMOVED_SET,
) -> dict[str, Any]:
    """Take images out of ``source`` (the newest version of a set).

    ``reasons`` gives a reason per image; images without one get ``reason``.

    ``holding`` is the set the images move to: ``removed``, or ``isolated`` for images set
    aside for a while; ``removed_set`` is that set's newest version, if it exists.

    Returns the new version of the set, the new version of the holding set, and the
    images that were not in ``source`` (already removed, or never there).
    """
    config = config or get_config()
    if holding not in HOLDING_SETS:
        raise CurationError(f"images can only be moved to {list(HOLDING_SETS)}")
    if source.base_name in HOLDING_SETS:
        raise CurationError(f"images in the {source.base_name} set are put back, not moved again")
    wanted = list(dict.fromkeys(sample_key(s) for s in samples if s))
    if not wanted:
        raise CurationError("choose at least one image to remove")
    column = image_column(source)
    images = source.to_arrow().column(column).to_pylist()
    position = {}
    for i, image in enumerate(images):
        position.setdefault(image, i)
    rows = [position[s] for s in wanted if s in position]
    missing = [s for s in wanted if s not in position]
    if not rows:
        raise CurationError(f"none of these images are in {source.name}; they may have been removed already")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    set_name = source.base_name
    dropped = set(rows)
    kept = [i for i in range(len(images)) if i not in dropped]
    new_version = write_version(
        project_name=source.project_name, dataset_name=source.dataset_name, base_name=set_name,
        name=f"{set_name}_{holding}", arrow=source.to_arrow().take(pa.array(kept, type=pa.int64())),
        schema=source.schema, parents=(source.url,), op="delete_rows",
        args={"count": len(rows), "reason": reason},
        description=f"Removed {_plain(len(rows), 'image')}" + (f": {reason}" if reason else ""),
    )

    taken = source.to_arrow().take(pa.array(rows, type=pa.int64()))
    reasons = {sample_key(k): v for k, v in (reasons or {}).items()}
    why = [reasons.get(images[r]) or reason for r in rows]
    schema = _removed_schema(source)
    extra = {
        "removed_from": [set_name] * len(rows),
        "removed_from_version": [str(source.url)] * len(rows),
        "removed_reason": why,
        "removed_at": [now] * len(rows),
    }
    for name, values in extra.items():
        if name in taken.column_names:
            taken = taken.drop_columns([name])
        taken = taken.append_column(name, pa.array(values, type=pa.string()))
    taken = taken.select(schema.names).cast(schema.arrow_schema())

    if removed_set is not None:
        existing = removed_set.to_arrow()
        if existing.schema.remove_metadata() != taken.schema.remove_metadata():
            raise CurationError(
                f"images from {set_name} have different columns from the {holding} set; "
                "they cannot be kept together"
            )
        arrow = pa.concat_tables([existing, taken])
        parents: tuple[Any, ...] = (removed_set.url,)
    else:
        arrow = taken
        parents = ()
    removed = write_version(
        project_name=source.project_name, dataset_name=source.dataset_name, base_name=holding,
        name=holding, arrow=arrow, schema=schema, parents=parents, op="remove_images" if holding == REMOVED_SET else "isolate_images",
        args={"from": set_name, "from_version": str(source.url), "count": len(rows), "reason": reason},
        description=f"{_plain(len(rows), 'image')} taken out of {set_name}" + (f": {reason}" if reason else ""),
    )

    log = ReviewLog(source.project_name, source.dataset_name, config=config)
    by_reason: dict[str, list[str]] = {}
    for r, text in zip(rows, why):
        by_reason.setdefault(text or f"{'Removed' if holding == REMOVED_SET else 'Isolated'} from {set_name}", []).append(images[r])
    for text, group in by_reason.items():
        log.record(group, "excluded" if holding == REMOVED_SET else "deferred", reason=text, table_url=str(new_version.url))
    return {"version": new_version, "removed": removed, "count": len(rows), "missing": missing}


def restore_images(
    removed_set: Table,
    samples: Iterable[str],
    *,
    newest_of: dict[str, Table],
    config: Config | None = None,
) -> dict[str, Any]:
    """Put images from a holding set (removed or isolated) back into the newest version of
    the set each came from.

    ``newest_of`` maps set names (``train``, ``valid``) to their newest versions.
    """
    config = config or get_config()
    holding = removed_set.base_name
    if holding not in HOLDING_SETS:
        raise CurationError(f"{removed_set.name} is not a set of removed or isolated images")
    wanted = set(sample_key(s) for s in samples if s)
    column = image_column(removed_set)
    arrow = removed_set.to_arrow()
    images = arrow.column(column).to_pylist()
    origins = arrow.column("removed_from").to_pylist()
    chosen = [i for i, image in enumerate(images) if image in wanted]
    if not chosen:
        raise CurationError(f"none of these images are in the {holding} set")

    by_set: dict[str, list[int]] = {}
    for i in chosen:
        by_set.setdefault(origins[i], []).append(i)
    unknown = [name for name in by_set if name not in newest_of]
    if unknown:
        raise CurationError(f"the set these images came from no longer exists: {', '.join(unknown)}")

    versions = []
    for set_name, rows in by_set.items():
        target = newest_of[set_name]
        back = arrow.take(pa.array(rows, type=pa.int64())).drop_columns(
            [c for c in REMOVED_COLUMNS if c in arrow.column_names and c not in target.columns]
        )
        present = set(target.to_arrow().column(image_column(target)).to_pylist())
        keep = [j for j, image in enumerate(back.column(column).to_pylist()) if image not in present]
        if not keep:
            continue
        back = back.take(pa.array(keep, type=pa.int64()))
        try:
            back = back.select(target.schema.names).cast(target.schema.arrow_schema())
        except (KeyError, pa.ArrowInvalid, ValueError) as exc:
            raise CurationError(f"these images no longer fit {set_name}: its columns have changed ({exc})") from exc
        merged = pa.concat_tables([target.to_arrow(), back])
        versions.append(write_version(
            project_name=target.project_name, dataset_name=target.dataset_name, base_name=target.base_name,
            name=f"{target.base_name}_restored", arrow=merged, schema=target.schema, parents=(target.url,),
            op="restore_images", args={"count": len(keep), "from": str(removed_set.url)},
            description=f"Put back {_plain(len(keep), 'image')}",
        ))

    chosen_set = set(chosen)
    remaining = [i for i in range(len(images)) if i not in chosen_set]
    removed = write_version(
        project_name=removed_set.project_name, dataset_name=removed_set.dataset_name, base_name=holding,
        name=holding, arrow=arrow.take(pa.array(remaining, type=pa.int64())) if remaining else arrow.schema.empty_table(),
        schema=removed_set.schema, parents=(removed_set.url,), op="restore_images",
        args={"count": len(chosen)}, description=f"{_plain(len(chosen), 'image')} put back",
    )
    ReviewLog(removed_set.project_name, removed_set.dataset_name, config=config).record(
        [images[i] for i in chosen], "unreviewed", reason="Put back", table_url=str(removed.url),
    )
    return {"versions": versions, "removed": removed, "count": len(chosen)}

