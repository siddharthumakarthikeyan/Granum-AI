#!/usr/bin/env python3
"""Make a deterministic, attributed, unmodified-image subset for the Granum course.

The input is read-only. Existing output directories/archives are never overwritten.
No synthetic boxes, scores, reviews or training results are generated here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import zipfile
from collections import Counter
from pathlib import Path

SOURCE_URL = "https://universe.roboflow.com/val-data/aerial-person-detection-fhrsh"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
SEED = 20261002


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sequence(name: str) -> str:
    match = re.match(r"^([A-Za-z0-9]+)[_-]\d+", name)
    if not match:
        raise ValueError(f"cannot infer a capture-sequence prefix: {name}")
    return match.group(1)


def safe_image(root: Path, name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise ValueError(f"unsafe image reference: {name}")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"missing or unsafe image reference: {name}")
    return path


def prepare(source: Path, target: Path, archive: Path, *, train_count: int = 96, valid_count: int = 24) -> dict:
    if target.exists() or archive.exists():
        raise ValueError("choose new output paths; existing tutorials are never overwritten")
    if min(train_count, valid_count) < 1:
        raise ValueError("both split counts must be positive")
    if target.resolve().is_relative_to(source.resolve()) or archive.resolve().is_relative_to(source.resolve()):
        raise ValueError("write the tutorial outside the source dataset")
    if archive.resolve().is_relative_to(target.resolve()):
        raise ValueError("write the archive outside the extracted tutorial")
    data = {split: json.loads((source / split / "_annotations.coco.json").read_text()) for split in ("train", "valid", "test")}
    if digest(source / "valid" / "_annotations.coco.json") != digest(source / "test" / "_annotations.coco.json"):
        raise ValueError("this course expects the supplied byte-identical validation/test annotations")
    for image in data["valid"]["images"]:
        name = image["file_name"]
        if digest(safe_image(source / "valid", name)) != digest(safe_image(source / "test", name)):
            raise ValueError(f"test image does not duplicate validation as documented: {name}")
    valid_sequences = {sequence(i["file_name"]) for i in data["valid"]["images"]}
    counts = {"train": train_count, "valid": valid_count}
    selected = {}
    seen_hashes: set[str] = set()
    manifest = {
        "format_version": 1, "name": "aerial-mini", "seed": SEED,
        "source": SOURCE_URL, "source_exported_at": "2026-09-16T12:22:18+00:00",
        "license_declared_by_source": "CC BY 4.0", "license_url": LICENSE_URL,
        "changes": "Subset selection only. Image bytes and selected annotation objects are unchanged.",
        "test_policy": "The supplied test annotations duplicate validation. No independent test set is included.",
        "selection": "Seeded unique source frames; train prefixes exclude every source-validation prefix; selected byte-identical images excluded.",
        "limits": "Filename-prefix separation is a heuristic, not proof of scene independence. This small course subset is not a benchmark.",
        "source_splits": {s: {"images": len(d["images"]), "annotations": len(d["annotations"]),
                              "annotations_sha256": digest(source / s / "_annotations.coco.json")} for s, d in data.items()},
        "splits": {},
    }
    # Select validation first so byte-identical images cannot subsequently enter train.
    for split in ("valid", "train"):
        candidates = sorted(data[split]["images"], key=lambda image: image["file_name"])
        random.Random(SEED).shuffle(candidates)
        chosen, seen_frames = [], set()
        for image in candidates:
            name = image["file_name"]
            frame = name.split(".rf.")[0]
            if frame in seen_frames or (split == "train" and sequence(name) in valid_sequences):
                continue
            sha = digest(safe_image(source / split, name))
            if sha in seen_hashes:
                continue
            chosen.append(image)
            seen_frames.add(frame)
            seen_hashes.add(sha)
            if len(chosen) == counts[split]:
                break
        if len(chosen) != counts[split]:
            raise ValueError(f"only {len(chosen)} eligible {split} images; requested {counts[split]}")
        selected[split] = sorted(chosen, key=lambda image: image["file_name"])

    target.mkdir(parents=True)
    for split in ("train", "valid"):
        folder = target / split
        folder.mkdir()
        images = selected[split]
        ids = {i["id"] for i in images}
        annotations = [a for a in data[split]["annotations"] if a["image_id"] in ids]
        document = {**data[split], "images": images, "annotations": annotations}
        (folder / "_annotations.coco.json").write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
        files = []
        for image in images:
            original = safe_image(source / split, image["file_name"])
            output = folder / image["file_name"]
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, output)
            files.append({"file": image["file_name"], "sha256": digest(output), "bytes": output.stat().st_size})
        class_counts = Counter(a["category_id"] for a in annotations)
        manifest["splits"][split] = {
            "images": len(images), "annotations": len(annotations), "files": files,
            "classes": [{**c, "annotations": class_counts[c["id"]]} for c in document["categories"]],
        }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (target / "ATTRIBUTION.txt").write_text(
        "Aerial Person Detection — Granum learning subset\n\n"
        f"Source: val-data / Aerial Person Detection on Roboflow Universe\n{SOURCE_URL}\n"
        "Source export: v1, 16 September 2026 (12:22:18 UTC).\n"
        f"The supplied export declares CC BY 4.0: {LICENSE_URL}\n\n"
        "Adaptation by Granum: deterministic subset selection; no changes to the selected image bytes\n"
        "or annotation objects. Keep this attribution with redistributed copies. No endorsement\n"
        "by the source provider is implied. Check original/upstream rights for your intended use;\n"
        "the export's licence notice is not independent verification of ownership.\n\n"
        "This is training material, not a benchmark or a certified/approved dataset.\n"
        "The test folder supplied with the original export duplicates validation and is omitted.\n"
        "The unused/duplicate people category and ignored-region category are intentionally retained\n"
        "so the tutorial can explain the actual preflight decisions.\n", encoding="utf-8")
    (target / "START-HERE.txt").write_text(
        "Granum guided course: https://granum.app/docs/course/start\n\n"
        "Extract the whole aerial-mini folder to a permanent local data folder.\n"
        "Create a new object-detection project named aerial-walkthrough.\n"
        "Select the aerial-mini folder: train and valid should both be found.\n"
        "Keep the split sizes; choose All images for the image check.\n"
        "Read the preflight decisions before importing. Nothing here is a model-quality claim.\n",
        encoding="utf-8")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(p for p in target.rglob("*") if p.is_file()):
            entry = zipfile.ZipInfo("aerial-mini/" + path.relative_to(target).as_posix(), date_time=(2026, 10, 2, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            z.writestr(entry, path.read_bytes())
    return {"sha256": digest(archive), "bytes": archive.stat().st_size,
            "splits": {s: {k: manifest["splits"][s][k] for k in ("images", "annotations")} for s in counts}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.target, args.archive), indent=2))