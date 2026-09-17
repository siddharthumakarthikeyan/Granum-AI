"""Turn a preflight report and the chosen options into Tables.

The import never guesses. Each finding with options resolves to exactly one of them --
the caller's choice, or the finding's default -- and every change that choice makes is
counted and written into the new Tables' producer, next to the report itself. A Table
imported this way can always answer "what was done to the source file, and why".
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from granum.core.config import Config, get_config
from granum.core.layout import ProjectLayout, sanitize
from granum.formats.coco import table_from_coco_data
from granum.importing.preflight import (
    PREFLIGHT_VERSION,
    PreflightError,
    PreflightReport,
    categories_of,
)

GROUP_COLUMNS = {
    "images.export_copies": "source_image",
    "split.shared_source": "source_image",
    "split.shared_sequence": "sequence",
    "media.identical_files": "content_hash",
}

Progress = Callable[[str, int, int], None]


@dataclass
class ImportResult:
    id: str
    project_name: str
    tables: list[dict[str, Any]]
    resolutions: dict[str, str]
    effects: dict[str, Any]
    report_url: str
    verdict: str
    warnings_accepted: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_name": self.project_name,
            "tables": self.tables,
            "resolutions": self.resolutions,
            "effects": self.effects,
            "report_url": self.report_url,
            "verdict": self.verdict,
            "warnings_accepted": self.warnings_accepted,
        }


def resolve_options(report: PreflightReport, chosen: dict[str, str] | None) -> dict[str, str]:
    """Every finding with options, mapped to the option that will be applied.

    Raises when a finding cannot be resolved -- a block with no way forward, or a choice
    that is not one of the finding's options.
    """
    chosen = dict(chosen or {})
    unknown = set(chosen) - {f.code for f in report.findings}
    if unknown:
        raise PreflightError(f"no finding named {sorted(unknown)} in this report")
    resolved: dict[str, str] = {}
    for finding in report.findings:
        if not finding.options:
            if finding.severity == "block":
                raise PreflightError(f"cannot import: {finding.title}. {finding.detail}")
            continue
        choice = chosen.get(finding.code, finding.default)
        valid = [o.id for o in finding.options]
        if choice not in valid:
            raise PreflightError(f"{finding.code}: choose one of {valid}, got {choice!r}")
        resolved[finding.code] = choice
    return resolved


def import_coco(
    report: PreflightReport,
    *,
    project_name: str,
    resolutions: dict[str, str] | None = None,
    dataset_name: str | None = None,
    description: str = "",
    splits: list[str] | None = None,
    progress: Progress | None = None,
    config: Config | None = None,
) -> ImportResult:
    """Import the splits of a preflighted COCO dataset into ``project_name``.

    All splits become Tables of one dataset, ``dataset_name`` (by default the folder the
    split folders sit in), each named after its split: ``human_aerial/train``,
    ``human_aerial/valid``. Later revisions of a split keep its name as their base name.

    ``splits`` limits which splits are written -- preflight all of them together, so
    leakage between splits is found, even when only one is new.
    """
    if not report.parsed:
        raise PreflightError("this report has no readable annotation files to import")
    sanitize(project_name)  # fail early on an unusable name
    dataset_name = dataset_name or suggest_dataset_name(report, project_name)
    sanitize(dataset_name)
    progress = progress or (lambda phase, done, total: None)
    config = config or get_config()
    chosen = resolve_options(report, resolutions)
    import_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:6]
    effects: Counter[str] = Counter()

    names, usage = categories_of(report)
    total: Counter[int] = Counter()
    for counter in usage.values():
        total.update(counter)

    remap: dict[int, int] = {}
    if chosen.get("categories.duplicate_name") == "merge":
        by_name: dict[str, list[int]] = {}
        for cid, name in sorted(names.items()):
            by_name.setdefault(name.strip().lower(), []).append(cid)
        for ids in by_name.values():
            if len(ids) > 1:
                keep = max(ids, key=lambda i: (total[i], -i))
                for other in ids:
                    if other != keep:
                        remap[other] = keep
                        effects["categories_merged"] += 1
    ignore_ids = set()
    ignore = report.finding("categories.ignore_region")
    if ignore is not None:
        from granum.importing.preflight import IGNORE_NAME

        ignore_ids = {cid for cid, name in names.items() if IGNORE_NAME.match(name.strip())}
    removed = set(remap)
    if chosen.get("categories.unused") == "remove":
        removed |= {cid for cid in names if total[cid] == 0 and cid not in remap.values()}
    if chosen.get("categories.ignore_region") == "drop":
        removed |= ignore_ids
    effects["categories_removed"] = len(removed - set(remap))

    excluded_images: dict[str, set[int]] = {split: set() for split in report.parsed}
    for code in ("media.missing", "media.unreadable", "media.size_mismatch"):
        if chosen.get(code) != "exclude":
            continue
        for split, results in report.media.items():
            data = report.parsed[split]
            for image_id, result in results.items():
                image = data.image_by_id[image_id]
                bad = (
                    (code == "media.missing" and not result.exists)
                    or (code == "media.unreadable" and result.exists and not result.readable)
                    or (code == "media.size_mismatch" and result.readable and result.width is not None
                        and (image.get("width") not in (None, result.width) or image.get("height") not in (None, result.height)))
                )
                if bad:
                    excluded_images[split].add(image_id)
    if chosen.get("images.unannotated") == "exclude":
        for split, data in report.parsed.items():
            for image in data.images:
                if not data.annotations_by_image.get(int(image["id"])):
                    excluded_images[split].add(int(image["id"]))

    group_columns = sorted({GROUP_COLUMNS[code] for code, choice in chosen.items() if code in GROUP_COLUMNS and choice == "record"})
    categories = [
        {**category, "id": int(category["id"])}
        for category in _merged_categories(report)
        if int(category["id"]) not in removed
    ]

    tables: list[dict[str, Any]] = []
    wanted = None if splits is None else set(splits)
    if wanted is not None and wanted - set(report.parsed):
        raise PreflightError(f"no split named {sorted(wanted - set(report.parsed))} in this report")
    writing = [(name, data) for name, data in report.parsed.items() if wanted is None or name in wanted]
    report_dir = ProjectLayout(config.project_root).project(project_name) / "imports"
    report_url = report_dir / f"{import_id}.json"
    provenance = {
        "preflight": {
            "import_id": import_id,
            "version": PREFLIGHT_VERSION,
            "created": report.created,
            "verdict": report.verdict,
            "media_mode": report.media_mode,
            "findings": [{"code": f.code, "severity": f.severity, "count": f.count} for f in report.findings],
            "resolutions": chosen,
            "report": str(report_url.aliased()),
        }
    }

    for position, (split, data) in enumerate(writing):
        progress(f"Writing {split}", position, len(writing))
        images, annotations = [], []
        columns: dict[str, list[Any]] = {name: [] for name in group_columns}
        used_ids = {a.get("id") for anns in data.annotations_by_image.values() for a in anns if isinstance(a.get("id"), int)}
        next_id = max(used_ids, default=0) + 1
        seen_ids: set[int] = set()
        for image in data.images:
            image_id = int(image["id"])
            if image_id in excluded_images[split]:
                effects["images_excluded"] += 1
                effects["boxes_excluded_with_images"] += len(data.annotations_by_image.get(image_id, []))
                continue
            images.append(image)
            groups = report.groups.get(split, {}).get(image_id, {})
            for name in group_columns:
                columns[name].append(groups.get(name))
            width, height = _num(image.get("width")), _num(image.get("height"))
            for annotation in data.annotations_by_image.get(image_id, []):
                kept = _clean_annotation(annotation, names, chosen, remap, ignore_ids, removed, width, height, effects)
                if kept is None:
                    continue
                if chosen.get("annotations.duplicate_id") == "renumber" and kept.get("id") in seen_ids:
                    kept["id"] = next_id
                    next_id += 1
                    effects["annotation_ids_renumbered"] += 1
                if isinstance(kept.get("id"), int):
                    seen_ids.add(kept["id"])
                annotations.append(kept)

        document = {k: v for k, v in data.coco.items() if k not in {"images", "annotations", "categories"}}
        document.update({"images": images, "annotations": annotations, "categories": categories})
        table = table_from_coco_data(
            document,
            source=data.source.annotations,
            image_folder=data.source.image_folder,
            project_name=project_name,
            dataset_name=dataset_name,
            table_name=split,
            description=description or f"Imported from {data.source.annotations} after preflight",
            extra_columns=columns or None,
            producer_args={**provenance, "split": split},
            config=config,
        )
        tables.append({
            "split": split, "url": str(table.url), "name": table.name,
            "dataset_name": table.dataset_name, "rows": len(table), "boxes": len(annotations),
        })
    progress("Writing tables", len(writing), len(writing))

    result = ImportResult(
        id=import_id,
        project_name=project_name,
        tables=tables,
        resolutions=chosen,
        effects=dict(effects),
        report_url=str(report_url),
        verdict=report.verdict,
        warnings_accepted=[f.code for f in report.findings if f.severity == "warn"],
    )
    report_dir.mkdir()
    report_url.write_text(json.dumps({"report": report.to_dict(), "import": result.to_dict()}, indent=1))
    return result


def suggest_dataset_name(report: PreflightReport, fallback: str = "dataset") -> str:
    """The folder holding the split folders: ``.../human_aerial/train/x.json`` -> ``human_aerial``."""
    import re

    names = set()
    for source in report.sources:
        folder = source.image_folder
        parent = folder.parent if folder.name == source.split else folder
        names.add(parent.name)
    name = names.pop() if len(names) == 1 else fallback
    return re.sub(r"[^A-Za-z0-9._ -]+", "-", name).strip(" .-") or fallback


def _merged_categories(report: PreflightReport) -> list[dict[str, Any]]:
    """The category list shared by all splits, in id order, keeping each entry's extras."""
    out: dict[int, dict[str, Any]] = {}
    for data in report.parsed.values():
        for category in data.coco["categories"]:
            try:
                out.setdefault(int(category["id"]), dict(category))
            except (KeyError, TypeError, ValueError):
                continue
    return [out[i] for i in sorted(out)]


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _clean_annotation(
    annotation: dict[str, Any],
    names: dict[int, str],
    chosen: dict[str, str],
    remap: dict[int, int],
    ignore_ids: set[int],
    removed: set[int],
    width: float | None,
    height: float | None,
    effects: Counter[str],
) -> dict[str, Any] | None:
    """One annotation after the chosen options, or None when it is left out."""
    category = annotation.get("category_id")
    if not isinstance(category, int) or category not in names:
        effects["boxes_dropped_unknown_category"] += 1
        return None
    box = annotation.get("bbox")
    if not (isinstance(box, list) and len(box) == 4 and all(_num(v) is not None for v in box)):
        effects["boxes_dropped_invalid"] += 1
        return None
    x, y, w, h = (float(v) for v in box)
    if w < 0 or h < 0:
        effects["boxes_dropped_invalid"] += 1
        return None
    if (w == 0 or h == 0) and chosen.get("annotations.zero_area") == "drop":
        effects["boxes_dropped_zero_area"] += 1
        return None

    out = dict(annotation)
    if width and height and (x < -1 or y < -1 or x + w > width + 1 or y + h > height + 1):
        choice = chosen.get("annotations.out_of_bounds")
        if choice == "drop":
            effects["boxes_dropped_out_of_bounds"] += 1
            return None
        if choice == "clip":
            x0, y0 = max(0.0, x), max(0.0, y)
            x1, y1 = min(width, x + w), min(height, y + h)
            if x1 <= x0 or y1 <= y0:
                effects["boxes_dropped_out_of_bounds"] += 1
                return None
            out["bbox"] = [x0, y0, x1 - x0, y1 - y0]
            effects["boxes_clipped"] += 1

    if category in ignore_ids:
        choice = chosen.get("categories.ignore_region")
        if choice == "drop":
            effects["boxes_dropped_ignore_region"] += 1
            return None
        if choice == "mark_ignore":
            out["iscrowd"] = 1
            effects["boxes_marked_ignore"] += 1
    if category in remap:
        out["category_id"] = remap[category]
        effects["boxes_remapped_category"] += 1
    elif category in removed:
        effects["boxes_dropped_removed_category"] += 1
        return None
    return out
