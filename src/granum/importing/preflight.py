"""Import preflight: what is wrong with a dataset before it becomes a Table.

A COCO file can be valid JSON, load without error, and still be the wrong data to train
on: a class that is really an "ignore this area" marker, the same frame in train and
validation, boxes of zero size, a placeholder category left behind by an export tool.
Each of those silently changes what a model learns or how it is scored. Preflight finds
them *before* import, when fixing them costs a decision rather than a retrain.

The report is a list of findings. Every finding has

* a **severity** -- ``block`` (the import would fail or be silently wrong), ``warn``
  (valid, but likely to mislead training or evaluation), ``info`` (worth knowing);
* the **evidence** -- counts per split and example images and boxes;
* the **options** for handling it, one of which is the default.

Nothing is changed by preflight itself. The import applies the chosen options and
records the report, the choices and their effect on the new Tables' lineage, so anyone
opening the data later can see what was done to it and why.

Findings name *candidates*, not verdicts: a category called "others" may be perfectly
intended, and frames from one sequence in two splits may be an accepted design.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import random
import re
import threading
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from granum.core.url import Url
from granum.errors import GranumError

PREFLIGHT_VERSION = 1
MAX_EXAMPLES = 12
MEDIA_MODES = ("full", "sample", "none")
SAMPLE_SIZE = 200
MEDIA_WORKERS = 8
CROWDED_BOXES = 300

SEVERITIES = ("block", "warn", "info")

#: Category names that, by convention, mark regions to ignore rather than objects.
IGNORE_NAME = re.compile(r"^(ignored?[ _-]*(regions?|areas?)?|dont[ _-]*care|don'?t[ _-]*care|void|crowd|ignore)$", re.I)
#: Category names that collect whatever did not fit another class.
CATCH_ALL_NAME = re.compile(r"^(others?|misc(ellaneous)?|unknown|background)$", re.I)
#: Roboflow and similar tools rename an exported image ``<original>_<ext>.rf.<hash>.<ext>``.
AUGMENTED_COPY = re.compile(r"^(?P<source>.+?)_(?:jpe?g|png|bmp|webp|tiff?)\.rf\.[0-9a-f]{16,}\.[A-Za-z]+$", re.I)
#: A leading token shared by frames of one capture: ``0000291_04201_d_0000889.jpg``.
SEQUENCE_PREFIX = re.compile(r"^(?P<sequence>[A-Za-z0-9]+)[_-]\d+")


class PreflightError(GranumError):
    """Preflight could not read its input at all."""


class Cancelled(GranumError):
    """Preflight was cancelled by its caller."""


Progress = Callable[[str, int, int], None]


@dataclass
class Source:
    """One split of a dataset: an annotation file and the folder its images live in."""

    split: str
    annotations: str
    images: str | None = None

    @property
    def image_folder(self) -> Url:
        return Url(self.images) if self.images else Url(self.annotations).parent

    def to_dict(self) -> dict[str, Any]:
        return {"split": self.split, "annotations": self.annotations, "images": str(self.image_folder)}


@dataclass
class Option:
    id: str
    label: str
    effect: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label, "effect": self.effect}


@dataclass
class Finding:
    code: str
    severity: str
    title: str
    detail: str
    count: int
    unit: str
    splits: dict[str, int] = field(default_factory=dict)
    examples: list[dict[str, Any]] = field(default_factory=list)
    options: list[Option] = field(default_factory=list)
    default: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "count": self.count,
            "unit": self.unit,
            "splits": self.splits,
            "examples": self.examples,
            "options": [o.to_dict() for o in self.options],
            "default": self.default,
        }


@dataclass
class ParsedSplit:
    """A split's annotation file, parsed once and kept for the import that follows."""

    source: Source
    coco: dict[str, Any]
    images: list[dict[str, Any]]
    image_by_id: dict[int, dict[str, Any]]
    annotations_by_image: dict[int, list[dict[str, Any]]]


@dataclass
class MediaResult:
    exists: bool
    readable: bool = False
    width: int | None = None
    height: int | None = None
    sha1: str | None = None
    bytes: int = 0
    error: str | None = None


@dataclass
class PreflightReport:
    sources: list[Source]
    created: str
    media_mode: str
    findings: list[Finding]
    summary: dict[str, Any]
    #: Kept for the import step; never serialized to clients.
    parsed: dict[str, ParsedSplit] = field(default_factory=dict, repr=False)
    media: dict[str, dict[int, MediaResult]] = field(default_factory=dict, repr=False)
    groups: dict[str, dict[int, dict[str, str | None]]] = field(default_factory=dict, repr=False)

    @property
    def verdict(self) -> str:
        severities = {f.severity for f in self.findings}
        if "block" in severities:
            return "block"
        return "warn" if "warn" in severities else "pass"

    def finding(self, code: str) -> Finding | None:
        return next((f for f in self.findings if f.code == code), None)

    def to_dict(self) -> dict[str, Any]:
        order = {s: i for i, s in enumerate(SEVERITIES)}
        return {
            "version": PREFLIGHT_VERSION,
            "format": "coco",
            "created": self.created,
            "verdict": self.verdict,
            "media_mode": self.media_mode,
            "sources": [s.to_dict() for s in self.sources],
            "summary": self.summary,
            "findings": [
                f.to_dict() for f in sorted(self.findings, key=lambda f: (order[f.severity], -f.count))
            ],
        }


# -- reading -------------------------------------------------------------------


def _parse(source: Source) -> tuple[ParsedSplit | None, list[Finding]]:
    url = Url(source.annotations)
    try:
        coco = json.loads(url.read_text())
    except FileNotFoundError:
        return None, [_fatal(source, f"{url} does not exist.")]
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, [_fatal(source, f"{url} could not be read as JSON: {exc}")]
    if not isinstance(coco, dict):
        return None, [_fatal(source, f"{url} holds a JSON {type(coco).__name__}, not a COCO object.")]
    missing = [k for k in ("images", "annotations", "categories") if not isinstance(coco.get(k), list)]
    if missing:
        return None, [_fatal(source, f"{url} has no {', '.join(repr(k) for k in missing)} list, so it is not COCO detection data.")]

    findings: list[Finding] = []
    images: list[dict[str, Any]] = []
    image_by_id: dict[int, dict[str, Any]] = {}
    duplicate_ids: list[dict[str, Any]] = []
    malformed = 0
    for image in coco["images"]:
        try:
            image_id = int(image["id"])
            str(image["file_name"])
        except (KeyError, TypeError, ValueError):
            malformed += 1
            continue
        if image_id in image_by_id:
            duplicate_ids.append(image)
            continue
        image_by_id[image_id] = image
        images.append(image)
    if malformed:
        findings.append(Finding(
            code="images.malformed", severity="block",
            title="Image entries without an id or file name",
            detail="These entries cannot be matched to a file or to their annotations. They are left out.",
            count=malformed, unit="images", splits={source.split: malformed},
            options=[Option("exclude", "Leave them out", "Skipped; their annotations become orphans.")],
            default="exclude",
        ))
    if duplicate_ids:
        findings.append(Finding(
            code="images.duplicate_id", severity="block",
            title="Image ids used more than once",
            detail="Annotations reference images by id, so a repeated id makes it ambiguous which image a box belongs to. "
                   "Only the first image with each id can be kept.",
            count=len(duplicate_ids), unit="images", splits={source.split: len(duplicate_ids)},
            examples=[{"split": source.split, "file_name": i.get("file_name"), "image_id": i.get("id")} for i in duplicate_ids[:MAX_EXAMPLES]],
            options=[Option("keep_first", "Keep the first", "Later images with a repeated id are left out.")],
            default="keep_first",
        ))

    by_image: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for annotation in coco["annotations"]:
        try:
            by_image[int(annotation["image_id"])].append(annotation)
        except (KeyError, TypeError, ValueError):
            by_image[-(2**62)].append(annotation)  # unaddressable; reported as orphans
    return ParsedSplit(source, coco, images, image_by_id, by_image), findings


def _fatal(source: Source, detail: str) -> Finding:
    return Finding(
        code="coco.unreadable", severity="block",
        title=f"The {source.split} annotation file cannot be used",
        detail=detail, count=1, unit="files", splits={source.split: 1},
    )


# -- media ---------------------------------------------------------------------


def _inspect_media(url: Url, want_hash: bool) -> MediaResult:
    try:
        data = url.read_bytes()
    except FileNotFoundError:
        return MediaResult(exists=False)
    except (OSError, ValueError) as exc:
        return MediaResult(exists=False, error=str(exc))
    result = MediaResult(exists=True, bytes=len(data))
    if want_hash:
        result.sha1 = hashlib.sha1(data).hexdigest()
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - optional extra
        result.readable = True
        return result
    try:
        with Image.open(io.BytesIO(data)) as image:
            result.width, result.height = image.size
            image.verify()
        result.readable = True
    except Exception as exc:  # noqa: BLE001 - any decoder failure means unreadable
        result.error = f"{type(exc).__name__}: {exc}"
    return result


def _check_media(
    parsed: dict[str, ParsedSplit],
    mode: str,
    progress: Progress,
    cancel: threading.Event | None,
) -> dict[str, dict[int, MediaResult]]:
    jobs: list[tuple[str, int, Url]] = []
    for split, data in parsed.items():
        images = data.images
        if mode == "sample" and len(images) > SAMPLE_SIZE:
            images = random.Random(0).sample(images, SAMPLE_SIZE)
        for image in images:
            jobs.append((split, int(image["id"]), data.source.image_folder / str(image["file_name"])))

    results: dict[str, dict[int, MediaResult]] = defaultdict(dict)
    total = len(jobs)
    progress("Reading images", 0, total)
    done = 0
    lock = threading.Lock()

    def work(job: tuple[str, int, Url]) -> None:
        nonlocal done
        if cancel is not None and cancel.is_set():
            return
        split, image_id, url = job
        result = _inspect_media(url, want_hash=mode == "full")
        with lock:
            results[split][image_id] = result
            done += 1
            if done % 64 == 0 or done == total:
                progress("Reading images", done, total)

    with ThreadPoolExecutor(max_workers=MEDIA_WORKERS) as pool:
        list(pool.map(work, jobs))
    if cancel is not None and cancel.is_set():
        raise Cancelled("preflight cancelled")
    return results


# -- analysis ------------------------------------------------------------------


def _example(split: str, folder: Url, image: dict[str, Any] | None, annotation: dict[str, Any] | None = None,
             categories: dict[int, str] | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"split": split}
    if image is not None:
        out["image"] = str(folder / str(image["file_name"]))
        out["file_name"] = image["file_name"]
        out["width"] = image.get("width")
        out["height"] = image.get("height")
    if annotation is not None:
        out["annotation_id"] = annotation.get("id")
        out["bbox"] = annotation.get("bbox")
        category = annotation.get("category_id")
        out["category"] = (categories or {}).get(category, category) if category is not None else None
    out.update(extra)
    return out


class _Collector:
    """Accumulates one finding's counts and examples across splits."""

    def __init__(self) -> None:
        self.splits: Counter[str] = Counter()
        self.examples: list[dict[str, Any]] = []

    def add(self, split: str, example: dict[str, Any] | None = None, n: int = 1) -> None:
        self.splits[split] += n
        if example is not None and len(self.examples) < MAX_EXAMPLES:
            self.examples.append(example)

    @property
    def count(self) -> int:
        return sum(self.splits.values())

    def __bool__(self) -> bool:
        return self.count > 0


def original_name(image: dict[str, Any]) -> str | None:
    """The file an exported image was derived from, when the export says so."""
    extra = image.get("extra")
    if isinstance(extra, dict) and isinstance(extra.get("name"), str):
        return extra["name"]
    match = AUGMENTED_COPY.match(str(image.get("file_name", "")))
    return f"{match.group('source')}" if match else None


def _sequence_of(name: str) -> str | None:
    match = SEQUENCE_PREFIX.match(name.rsplit("/", 1)[-1])
    return match.group("sequence") if match else None


def run_preflight(
    sources: Iterable[Source],
    *,
    media: str = "full",
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
) -> PreflightReport:
    """Inspect COCO detection splits and report what an import would get wrong."""
    sources = list(sources)
    if not sources:
        raise PreflightError("give at least one annotation file")
    if media not in MEDIA_MODES:
        raise PreflightError(f"media must be one of {MEDIA_MODES}, got {media!r}")
    splits = [s.split for s in sources]
    if len(set(splits)) != len(splits):
        raise PreflightError(f"split names must be unique, got {splits}")
    progress = progress or (lambda phase, done, total: None)

    findings: list[Finding] = []
    parsed: dict[str, ParsedSplit] = {}
    for position, source in enumerate(sources):
        progress("Reading annotations", position, len(sources))
        data, problems = _parse(source)
        findings.extend(problems)
        if data is not None:
            parsed[source.split] = data
        if cancel is not None and cancel.is_set():
            raise Cancelled("preflight cancelled")
    progress("Reading annotations", len(sources), len(sources))

    report = PreflightReport(
        sources=sources,
        created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        media_mode=media,
        findings=findings,
        summary={},
        parsed=parsed,
    )
    if not parsed:
        report.summary = {"images": 0, "boxes": 0, "splits": []}
        return report

    progress("Checking annotations", 0, 1)
    _check_categories(report)
    _check_annotations(report)
    progress("Checking annotations", 1, 1)

    if media != "none":
        report.media = _check_media(parsed, media, progress, cancel)
        _check_media_findings(report)
    _check_groups(report)
    report.summary = _summarize(report)
    progress("Done", 1, 1)
    return report


def categories_of(report: PreflightReport) -> tuple[dict[int, str], dict[str, Counter[int]]]:
    """Category id -> name across splits, and boxes per category per split."""
    names: dict[int, str] = {}
    usage: dict[str, Counter[int]] = {}
    for split, data in report.parsed.items():
        for category in data.coco["categories"]:
            try:
                names.setdefault(int(category["id"]), str(category["name"]))
            except (KeyError, TypeError, ValueError):
                continue
        counter: Counter[int] = Counter()
        for annotations in data.annotations_by_image.values():  # noqa: F402
            for annotation in annotations:
                try:
                    counter[int(annotation["category_id"])] += 1
                except (KeyError, TypeError, ValueError):
                    continue
        usage[split] = counter
    return names, usage


def _check_categories(report: PreflightReport) -> None:
    names, usage = categories_of(report)
    total: Counter[int] = Counter()
    for counter in usage.values():
        total.update(counter)

    # Splits that disagree about what an id means cannot share one class list.
    conflicts: list[dict[str, Any]] = []
    for split, data in report.parsed.items():
        for category in data.coco["categories"]:
            try:
                cid, name = int(category["id"]), str(category["name"])
            except (KeyError, TypeError, ValueError):
                continue
            if names.get(cid) != name:
                conflicts.append({"split": split, "category_id": cid, "name": name, "elsewhere": names.get(cid)})
    if conflicts:
        report.findings.append(Finding(
            code="categories.conflict", severity="block",
            title="Splits give the same category id different names",
            detail="One class list must hold for every split, or a box labelled 3 in train means something else in validation. "
                   "Fix the annotation files so the ids agree, then run preflight again.",
            count=len(conflicts), unit="categories",
            splits=dict(Counter(c["split"] for c in conflicts)), examples=conflicts[:MAX_EXAMPLES],
        ))

    by_name: dict[str, list[int]] = defaultdict(list)
    for cid, name in sorted(names.items()):
        by_name[name.strip().lower()].append(cid)
    duplicates = {name: ids for name, ids in by_name.items() if len(ids) > 1}
    if duplicates:
        report.findings.append(Finding(
            code="categories.duplicate_name", severity="warn",
            title="Different category ids share a name",
            detail="Two ids with one name usually means an export tool added a placeholder class or merged "
                   "two label sets. A model trained on both ids learns them as different classes.",
            count=sum(len(ids) for ids in duplicates.values()), unit="categories",
            examples=[
                {"name": names[ids[0]], "ids": ids, "boxes": {str(i): total[i] for i in ids}}
                for ids in duplicates.values()
            ],
            options=[
                Option("merge", "Merge into the most-used id", "Boxes on the other ids move to it; the other ids are removed."),
                Option("keep", "Keep them separate", "Imported as distinct classes with the same name."),
            ],
            default="merge",
        ))

    unused = [cid for cid in sorted(names) if total[cid] == 0]
    if unused:
        report.findings.append(Finding(
            code="categories.unused", severity="info",
            title="Categories with no boxes in any split",
            detail="An unused class still takes an output slot in most detectors and shows up in per-class metrics as empty.",
            count=len(unused), unit="categories",
            examples=[{"category_id": cid, "name": names[cid]} for cid in unused],
            options=[
                Option("remove", "Remove them", "Left out of the class list."),
                Option("keep", "Keep them", "Kept in the class list with no boxes."),
            ],
            default="remove",
        ))

    ignore = [cid for cid, name in names.items() if IGNORE_NAME.match(name.strip()) and total[cid] > 0]
    if ignore:
        collector = _Collector()
        for split, data in report.parsed.items():
            for image_id, annotations in data.annotations_by_image.items():  # noqa: F402
                for annotation in annotations:
                    if annotation.get("category_id") in ignore:
                        collector.add(split, _example(split, data.source.image_folder, data.image_by_id.get(image_id), annotation, names))
        report.findings.append(Finding(
            code="categories.ignore_region", severity="warn",
            title="A category looks like an ignore marker, not an object",
            detail=f"{', '.join(repr(names[c]) for c in ignore)} conventionally marks areas a model should be neither "
                   "rewarded nor penalised for. Every box here has iscrowd = 0, so imported as-is it trains and scores "
                   "as an ordinary class. Marking them keeps the boxes and sets their ignore flag: Granum's box "
                   "matching then skips them and YOLO export leaves them out. Other evaluators must honour iscrowd too.",
            count=collector.count, unit="boxes", splits=dict(collector.splits), examples=collector.examples,
            options=[
                Option("mark_ignore", "Mark as ignore regions", "Boxes kept with iscrowd = 1."),
                Option("drop", "Drop these boxes", "Removed from the imported annotations."),
                Option("keep", "Keep as an ordinary class", "Imported unchanged."),
            ],
            default="mark_ignore",
        ))

    catch_all = [cid for cid, name in names.items() if CATCH_ALL_NAME.match(name.strip()) and total[cid] > 0]
    if catch_all:
        report.findings.append(Finding(
            code="categories.catch_all", severity="info",
            title="A catch-all category",
            detail=f"{', '.join(repr(names[c]) for c in catch_all)} collects objects that fit no other class. "
                   "It is often small and inconsistently labelled; check it before relying on its metrics.",
            count=sum(total[c] for c in catch_all), unit="boxes",
            splits={split: sum(usage[split][c] for c in catch_all) for split in usage},
        ))


def _check_annotations(report: PreflightReport) -> None:
    names, _ = categories_of(report)
    orphans, unknown, invalid, zero, out_of_bounds, duplicate_ids = (_Collector() for _ in range(6))
    tiny, crowded, unannotated = _Collector(), _Collector(), _Collector()

    for split, data in report.parsed.items():
        folder = data.source.image_folder
        seen_ids: set[Any] = set()
        for image_id, annotations in data.annotations_by_image.items():  # noqa: F402
            image = data.image_by_id.get(image_id)
            if image is None:
                for annotation in annotations:
                    orphans.add(split, _example(split, folder, None, annotation, names, image_id=annotation.get("image_id")))
                continue
            if len(annotations) >= CROWDED_BOXES:
                crowded.add(split, _example(split, folder, image, boxes=len(annotations)))
            width, height = _number(image.get("width")), _number(image.get("height"))
            for annotation in annotations:
                annotation_id = annotation.get("id")
                if annotation_id is not None:
                    if annotation_id in seen_ids:
                        duplicate_ids.add(split, _example(split, folder, image, annotation, names))
                    seen_ids.add(annotation_id)
                category = annotation.get("category_id")
                if not isinstance(category, int) or category not in names:
                    unknown.add(split, _example(split, folder, image, annotation, names))
                    continue
                box = annotation.get("bbox")
                if not (isinstance(box, list) and len(box) == 4 and all(_number(v) is not None for v in box)):
                    invalid.add(split, _example(split, folder, image, annotation, names, reason="bbox is not four numbers"))
                    continue
                x, y, w, h = (float(v) for v in box)
                if w < 0 or h < 0:
                    invalid.add(split, _example(split, folder, image, annotation, names, reason="negative width or height"))
                    continue
                if w == 0 or h == 0:
                    zero.add(split, _example(split, folder, image, annotation, names))
                    continue
                if width and height and (x < -1 or y < -1 or x + w > width + 1 or y + h > height + 1):
                    out_of_bounds.add(split, _example(split, folder, image, annotation, names))
                if min(w, h) < 8:
                    tiny.add(split, _example(split, folder, image, annotation, names))
        for image in data.images:
            if not data.annotations_by_image.get(int(image["id"])):
                unannotated.add(split, _example(split, folder, image))

    if orphans:
        report.findings.append(Finding(
            code="annotations.orphan", severity="block",
            title="Boxes that point at images not in the file",
            detail="Their image_id matches no image entry, so there is nothing to attach them to.",
            count=orphans.count, unit="boxes", splits=dict(orphans.splits), examples=orphans.examples,
            options=[Option("drop", "Drop them", "Left out of the import.")], default="drop",
        ))
    if unknown:
        report.findings.append(Finding(
            code="annotations.unknown_category", severity="block",
            title="Boxes with a category id that is not declared",
            detail="A box needs a class from the category list to be trained on or displayed.",
            count=unknown.count, unit="boxes", splits=dict(unknown.splits), examples=unknown.examples,
            options=[Option("drop", "Drop them", "Left out of the import.")], default="drop",
        ))
    if invalid:
        report.findings.append(Finding(
            code="annotations.invalid_bbox", severity="block",
            title="Boxes with malformed coordinates",
            detail="A COCO bbox is [x, y, width, height] with non-negative size. These cannot be stored as boxes.",
            count=invalid.count, unit="boxes", splits=dict(invalid.splits), examples=invalid.examples,
            options=[Option("drop", "Drop them", "Left out of the import.")], default="drop",
        ))
    if zero:
        report.findings.append(Finding(
            code="annotations.zero_area", severity="warn",
            title="Boxes with zero width or height",
            detail="A box with no area cannot match a prediction, so it counts as a guaranteed miss in evaluation "
                   "and a degenerate target in training.",
            count=zero.count, unit="boxes", splits=dict(zero.splits), examples=zero.examples,
            options=[
                Option("drop", "Drop them", "Left out of the import."),
                Option("keep", "Keep them", "Imported unchanged."),
            ],
            default="drop",
        ))
    if out_of_bounds:
        report.findings.append(Finding(
            code="annotations.out_of_bounds", severity="warn",
            title="Boxes that extend past the image edge",
            detail="More than a pixel outside the declared image size. Usually a coordinate or resize bug in the export.",
            count=out_of_bounds.count, unit="boxes", splits=dict(out_of_bounds.splits), examples=out_of_bounds.examples,
            options=[
                Option("clip", "Clip to the image", "Coordinates limited to the image; boxes left with no area are dropped."),
                Option("keep", "Keep as-is", "Imported unchanged."),
                Option("drop", "Drop them", "Left out of the import."),
            ],
            default="clip",
        ))
    if duplicate_ids:
        report.findings.append(Finding(
            code="annotations.duplicate_id", severity="warn",
            title="Annotation ids used more than once",
            detail="Box identity is how a correction is traced back to the original annotation. Repeated ids make that ambiguous.",
            count=duplicate_ids.count, unit="boxes", splits=dict(duplicate_ids.splits), examples=duplicate_ids.examples,
            options=[Option("renumber", "Give repeats new ids", "The first box keeps its id; later ones get unused ids.")],
            default="renumber",
        ))
    if unannotated:
        report.findings.append(Finding(
            code="images.unannotated", severity="info",
            title="Images with no boxes",
            detail="COCO cannot say whether an image with no boxes contains no objects or was never labelled. "
                   "Negatives teach a detector what background looks like; unlabelled images teach it to miss objects.",
            count=unannotated.count, unit="images", splits=dict(unannotated.splits), examples=unannotated.examples,
            options=[
                Option("negative", "They contain no objects", "Imported as negative examples."),
                Option("exclude", "They were never labelled", "Left out of the import."),
            ],
            default="negative",
        ))
    if tiny:
        report.findings.append(Finding(
            code="annotations.tiny", severity="info",
            title="Boxes narrower or shorter than 8 pixels",
            detail="Common in aerial and distant scenes. Most detectors downsample by 8 or more, so these are hard "
                   "to learn and easy to mislabel; review them in the patch view rather than full images.",
            count=tiny.count, unit="boxes", splits=dict(tiny.splits), examples=tiny.examples,
        ))
    if crowded:
        report.findings.append(Finding(
            code="images.crowded", severity="info",
            title=f"Images with {CROWDED_BOXES} or more boxes",
            detail="Dense scenes hit per-image detection limits (often 100 or 300 predictions) and are slow to review by eye.",
            count=crowded.count, unit="images", splits=dict(crowded.splits), examples=crowded.examples,
        ))


def _check_media_findings(report: PreflightReport) -> None:
    missing, unreadable, mismatch = _Collector(), _Collector(), _Collector()
    for split, results in report.media.items():
        data = report.parsed[split]
        folder = data.source.image_folder
        for image_id, result in results.items():
            image = data.image_by_id[image_id]
            if not result.exists:
                missing.add(split, _example(split, folder, image))
            elif not result.readable:
                unreadable.add(split, _example(split, folder, image, reason=result.error))
            elif result.width is not None and (
                _number(image.get("width")) not in (None, result.width)
                or _number(image.get("height")) not in (None, result.height)
            ):
                mismatch.add(split, _example(split, folder, image, file_width=result.width, file_height=result.height))

    sampled = " (in the sampled images)" if report.media_mode == "sample" else ""
    if missing:
        report.findings.append(Finding(
            code="media.missing", severity="block",
            title=f"Image files that do not exist{sampled}",
            detail="The annotation file lists them but there is no file at the path. Check the image folder for each split.",
            count=missing.count, unit="images", splits=dict(missing.splits), examples=missing.examples,
            options=[Option("exclude", "Leave them out", "The images and their boxes are not imported.")], default="exclude",
        ))
    if unreadable:
        report.findings.append(Finding(
            code="media.unreadable", severity="block",
            title=f"Image files that cannot be decoded{sampled}",
            detail="The file exists but is truncated, corrupt or not an image.",
            count=unreadable.count, unit="images", splits=dict(unreadable.splits), examples=unreadable.examples,
            options=[Option("exclude", "Leave them out", "The images and their boxes are not imported.")], default="exclude",
        ))
    if mismatch:
        report.findings.append(Finding(
            code="media.size_mismatch", severity="warn",
            title=f"Image files whose size differs from the annotation file{sampled}",
            detail="Box coordinates are in the declared size. If the file was resized after labelling, boxes are drawn in the wrong place.",
            count=mismatch.count, unit="images", splits=dict(mismatch.splits), examples=mismatch.examples,
            options=[
                Option("exclude", "Leave them out", "The images and their boxes are not imported."),
                Option("keep", "Keep the declared size", "Imported unchanged."),
            ],
            default="exclude",
        ))


def _check_groups(report: PreflightReport) -> None:
    """Near-identical images: byte duplicates, export copies of one frame, frames of one sequence."""
    names_by_split = {split: {int(i["id"]): original_name(i) for i in data.images} for split, data in report.parsed.items()}

    # Export copies (flips, crops) of one source image.
    copies, cross_copies = _Collector(), _Collector()
    source_splits: dict[str, set[str]] = defaultdict(set)
    source_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for split, names in names_by_split.items():
        for name in names.values():
            if name:
                source_splits[name].add(split)
                source_counts[split][name] += 1
    for split, data in report.parsed.items():
        for image in data.images:
            name = names_by_split[split][int(image["id"])]
            if name is None:
                continue
            if source_counts[split][name] > 1:
                copies.add(split, _example(split, data.source.image_folder, image, source=name))
            if len(source_splits[name]) > 1:
                cross_copies.add(split, _example(split, data.source.image_folder, image, source=name, shared_with=sorted(source_splits[name] - {split})))

    # Frames of one capture sequence.
    sequence_splits: dict[str, set[str]] = defaultdict(set)
    sequences_by_split: dict[str, set[str]] = defaultdict(set)
    total_images = with_sequence = 0
    for split, data in report.parsed.items():
        for image in data.images:
            total_images += 1
            sequence = _sequence_of(names_by_split[split][int(image["id"])] or str(image["file_name"]))
            if sequence:
                with_sequence += 1
                sequence_splits[sequence].add(split)
                sequences_by_split[split].add(sequence)
    # A prefix nearly every image has, shared by several images on average, is a grouping
    # rather than a per-image counter.
    distinct = len(sequence_splits)
    is_sequenced = distinct >= 2 and with_sequence >= 0.8 * total_images and with_sequence >= 2 * distinct

    # Byte-identical files.
    by_hash: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for split, results in report.media.items():
        for image_id, result in results.items():
            if result.sha1:
                by_hash[result.sha1].append((split, image_id))
    identical, cross_identical = _Collector(), _Collector()
    for members in by_hash.values():
        if len(members) < 2:
            continue
        member_splits = {s for s, _ in members}
        for split, image_id in members:
            data = report.parsed[split]
            example = _example(split, data.source.image_folder, data.image_by_id[image_id], copies=len(members))
            identical.add(split, example)
            if len(member_splits) > 1:
                cross_identical.add(split, example)

    groups: dict[str, dict[int, dict[str, str | None]]] = {}
    for split, data in report.parsed.items():
        groups[split] = {}
        for image in data.images:
            image_id = int(image["id"])
            name = names_by_split[split][image_id]
            media = report.media.get(split, {}).get(image_id)
            groups[split][image_id] = {
                "source_image": name,
                "sequence": _sequence_of(name or str(image["file_name"])) if is_sequenced else None,
                "content_hash": media.sha1 if media else None,
            }
    report.groups = groups

    group_options = [
        Option("record", "Record groups", "Adds group columns so review, sampling and splits can treat related images together."),
        Option("ignore", "Do not record", "Imported without group columns."),
    ]
    if identical:
        report.findings.append(Finding(
            code="media.identical_files", severity="warn" if cross_identical else "info",
            title="Byte-identical image files" + (" across splits" if cross_identical else ""),
            detail=("The same file appears in more than one split, so validation scores include images the model trained on. "
                    if cross_identical else "The same file is listed more than once. ")
                   + "Nothing is moved or deleted; recording groups lets you find and fix them.",
            count=identical.count, unit="images", splits=dict(identical.splits), examples=(cross_identical or identical).examples,
            options=group_options, default="record",
        ))
    if copies:
        report.findings.append(Finding(
            code="images.export_copies", severity="info",
            title="Several images derived from one source frame",
            detail="The export created augmented copies (such as flips) of the same photo. Reviewing each copy separately "
                   "repeats work, and a label error in the source appears in every copy.",
            count=copies.count, unit="images", splits=dict(copies.splits), examples=copies.examples,
            options=group_options, default="record",
        ))
    if cross_copies:
        report.findings.append(Finding(
            code="split.shared_source", severity="warn",
            title="Copies of one source frame in different splits",
            detail="Validation contains versions of images the model trains on, so validation scores overstate performance.",
            count=cross_copies.count, unit="images", splits=dict(cross_copies.splits), examples=cross_copies.examples,
            options=group_options, default="record",
        ))
    if is_sequenced and len(report.parsed) > 1:
        shared = {s for s, splits in sequence_splits.items() if len(splits) > 1}
        if shared:
            affected = _Collector()
            per_split_share = {}
            for split, data in report.parsed.items():
                per_split_share[split] = f"{len(sequences_by_split[split] & shared)} of {len(sequences_by_split[split])}"
                for image in data.images:
                    name = names_by_split[split][int(image["id"])] or str(image["file_name"])
                    sequence = _sequence_of(name)
                    if sequence in shared:
                        affected.add(split, _example(split, data.source.image_folder, image, sequence=sequence))
            report.findings.append(Finding(
                code="split.shared_sequence", severity="warn",
                title="Capture sequences that appear in more than one split",
                detail="File names share a leading sequence number, and some sequences have frames in several splits "
                       f"({', '.join(f'{s}: {v} sequences shared' for s, v in per_split_share.items())}). Neighbouring frames of one "
                       "video are near-duplicates, so a sequence-level split gives an honest validation score. "
                       "This is inferred from file names; confirm it matches how the data was captured.",
                count=affected.count, unit="images", splits=dict(affected.splits), examples=affected.examples,
                options=group_options, default="record",
            ))


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return value
    return None


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[position]


def _summarize(report: PreflightReport) -> dict[str, Any]:
    names, usage = categories_of(report)
    splits = []
    side_bins = [0, 8, 16, 32, 64, 128, 256, math.inf]
    for split, data in report.parsed.items():
        per_image = [len(data.annotations_by_image.get(int(i["id"]), [])) for i in data.images]
        sides: list[float] = []
        for annotations in data.annotations_by_image.values():  # noqa: F402
            for annotation in annotations:
                box = annotation.get("bbox")
                if isinstance(box, list) and len(box) == 4 and all(_number(v) is not None for v in box):
                    w, h = float(box[2]), float(box[3])
                    if w > 0 and h > 0:
                        sides.append(math.sqrt(w * h))
        histogram = [
            {"from": side_bins[i], "to": None if side_bins[i + 1] == math.inf else side_bins[i + 1],
             "boxes": sum(1 for s in sides if side_bins[i] <= s < side_bins[i + 1])}
            for i in range(len(side_bins) - 1)
        ]
        sizes = Counter((i.get("width"), i.get("height")) for i in data.images)
        media = report.media.get(split, {})
        splits.append({
            "split": split,
            "images": len(data.images),
            "boxes": sum(per_image),
            "boxes_per_image": {
                "mean": round(sum(per_image) / len(per_image), 2) if per_image else 0,
                "median": _percentile(per_image, 0.5),
                "p90": _percentile(per_image, 0.9),
                "max": max(per_image, default=0),
            },
            "box_side_histogram": histogram,
            "median_box_side": round(_percentile(sides, 0.5), 1),
            "image_sizes": [{"width": w, "height": h, "images": n} for (w, h), n in sizes.most_common(6)],
            "distinct_image_sizes": len(sizes),
            "media_checked": len(media),
            "media_bytes": sum(r.bytes for r in media.values()),
        })
    classes = [
        {"id": cid, "name": name, "boxes": {split: usage[split][cid] for split in usage}}
        for cid, name in sorted(names.items())
    ]
    from granum.importing.tasks import detect_task

    return {
        "images": sum(s["images"] for s in splits),
        "boxes": sum(s["boxes"] for s in splits),
        "splits": splits,
        "classes": classes,
        "task": detect_task(report.parsed.values()),
    }
