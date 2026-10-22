"""Reproducible, license-filtered COCO people qualification; no data is redistributed.

    .venv/bin/python tools/qualify_coco_people.py prepare

Images come from COCO's official S3 bucket. Only the original annotation metadata's
CC BY image entries are downloaded. The frozen manifest retains Flickr attribution
links, license URLs, image hashes, sampling rules and original image/annotation IDs.
This is a declared COCO subset, not a full COCO benchmark or a legal certification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PIL import Image

BUCKET = "https://s3.amazonaws.com/images.cocodataset.org"
ARCHIVE = "annotations_trainval2017.zip"


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def download(url: str, target: Path) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    output.write(chunk)
            temporary.replace(target)
            return
        except OSError:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def slices(image: dict, annotations: list[dict]) -> list[str]:
    boxes = [a for a in annotations if not a.get("iscrowd")]
    result = ["all", "person_present" if boxes else "no_individual_person"]
    if len(boxes) >= 5:
        result.append("dense_5plus_people")
    if any(a.get("iscrowd") for a in annotations):
        result.append("crowd_regions")
    if any(a["area"] < 32 ** 2 for a in boxes):
        result.append("small_person")
    if any(x <= 1 or y <= 1 or x + w >= image["width"] - 1 or y + h >= image["height"] - 1
           for x, y, w, h in (a["bbox"] for a in boxes)):
        result.append("border_touching_proxy")
    for i, a in enumerate(boxes):
        x, y, w, h = a["bbox"]
        for b in boxes[i + 1:]:
            bx, by, bw, bh = b["bbox"]
            intersection = max(0, min(x + w, bx + bw) - max(x, bx)) * max(0, min(y + h, by + bh) - max(y, by))
            if intersection / max(w * h + bw * bh - intersection, 1e-9) >= .25:
                return [*result, "overlapping_boxes_proxy"]
    return result


def select(images: list[dict], annotations: dict[int, list[dict]], count: int, salt: str) -> list[dict]:
    """Predeclared image sampling: 20% negatives, 20% dense, remainder other people."""
    order = sorted(images, key=lambda image: hashlib.sha256(f"{salt}:{image['id']}".encode()).hexdigest())
    groups: dict[str, list[dict]] = defaultdict(list)
    for image in order:
        n = sum(not a.get("iscrowd") for a in annotations[image["id"]])
        groups["negative" if n == 0 else "dense" if n >= 5 else "person"].append(image)
    chosen = groups["negative"][:count // 5] + groups["dense"][:count // 5] + groups["person"][:count - 2 * (count // 5)]
    selected = {image["id"] for image in chosen}
    chosen += [image for image in order if image["id"] not in selected][:count - len(chosen)]
    if len(chosen) != count:
        raise ValueError(f"Only {len(chosen)} eligible images for the requested {count}")
    return sorted(chosen, key=lambda image: image["id"])


def prepare(root: Path, train_count: int, valid_count: int, test_count: int) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        if old["requested_counts"] != [train_count, valid_count, test_count]:
            raise ValueError("A frozen manifest exists with different counts; choose a new output directory")
        for entry in old["images"]:
            path = root / entry["path"]
            if not path.exists() or digest(path) != entry["sha256"]:
                raise ValueError(f"Frozen media changed or disappeared: {path}")
        return old
    archive = root / ARCHIVE
    download(f"{BUCKET}/annotations/{ARCHIVE}", archive)
    result: dict[str, Any] = {
        "dataset": "COCO 2017 person, CC BY image subset", "version": 1,
        "source": "https://cocodataset.org/#download", "archive_url": f"{BUCKET}/annotations/{ARCHIVE}",
        "archive_sha256": digest(archive), "requested_counts": [train_count, valid_count, test_count],
        "annotations_license": "https://creativecommons.org/licenses/by/4.0/",
        "image_license_policy": "Only entries whose COCO license URL contains /licenses/by/. Original Flickr URLs retained; recorded metadata is not independent rights verification.",
        "sampling": "SHA256 order, seed string granum-coco-people-v1; target 20% no individual person, 20% at least 5 people, 60% other person images; deterministic fill if a stratum is short.",
        "split_policy": "train and valid are disjoint subsets of official train2017; test is from official val2017 and is never used for selection or checkpoint choice.",
        "slice_policy": "Small uses official mask area <1024 pixels. Overlap IoU>=0.25 and border contact<=1px are proxies, not annotated occlusion/truncation.",
        "images": [], "splits": {},
    }
    for official in ["train2017", "val2017"]:
        with zipfile.ZipFile(archive) as zipped:
            data = json.loads(zipped.read(f"annotations/instances_{official}.json"))
            pose = json.loads(zipped.read(f"annotations/person_keypoints_{official}.json"))
        allowed = {entry["id"]: entry for entry in data["licenses"] if "/licenses/by/" in entry["url"]}
        people: dict[int, list[dict]] = defaultdict(list)
        for annotation in data["annotations"]:
            if annotation["category_id"] == 1:
                people[annotation["image_id"]].append(annotation)
        eligible = [image for image in data["images"] if image["license"] in allowed]
        if official == "train2017":
            valid = select(eligible, people, valid_count, "granum-coco-people-v1-valid")
            valid_ids = {image["id"] for image in valid}
            train = select([image for image in eligible if image["id"] not in valid_ids], people, train_count, "granum-coco-people-v1-train")
            partitions = {"train": train, "valid": valid}
        else:
            partitions = {"test": select(eligible, people, test_count, "granum-coco-people-v1-test")}
        for split, chosen in partitions.items():
            ids = {image["id"] for image in chosen}
            annotations = [annotation for image in chosen for annotation in people[image["id"]]]
            subset = {"images": chosen, "annotations": annotations, "categories": [c for c in data["categories"] if c["id"] == 1],
                      "licenses": list(allowed.values()), "info": data.get("info", {})}
            write_json(root / f"{split}.json", subset)
            write_json(root / f"{split}-pose.json", {**subset, "categories": pose["categories"], "annotations": [a for a in pose["annotations"] if a["image_id"] in ids]})

            def fetch(image: dict, official: str = official, split: str = split,
                      allowed: dict = allowed, people: dict = people) -> dict:
                local = Path("images") / official / image["file_name"]
                source = f"{BUCKET}/{official}/{image['file_name']}"
                path = root / local
                download(source, path)
                with Image.open(path) as picture:
                    if picture.size != (image["width"], image["height"]):
                        raise ValueError(f"Wrong image dimensions: {path}")
                    picture.verify()
                return {"id": image["id"], "split": split, "official_split": official, "path": str(local),
                        "sha256": digest(path), "source": source, "flickr_url": image.get("flickr_url"),
                        "license": allowed[image["license"]], "slices": slices(image, people[image["id"]])}

            with ThreadPoolExecutor(max_workers=8) as pool:
                entries = []
                for entry in pool.map(fetch, chosen):
                    entries.append(entry)
                    if len(entries) % 100 == 0:
                        print(f"Downloaded {split}: {len(entries)}/{len(chosen)}", flush=True)
            result["images"].extend(entries)
            result["splits"][split] = {"images": len(chosen), "annotations": len(annotations),
                "individual_people": sum(not a.get("iscrowd") for a in annotations),
                "slices": {name: sum(name in entry["slices"] for entry in entries) for name in sorted({name for entry in entries for name in entry["slices"]})},
                "annotation_sha256": digest(root / f"{split}.json")}
            print(json.dumps({split: result["splits"][split]}), flush=True)
    hashes: dict[str, str] = {}
    for entry in result["images"]:
        previous = hashes.setdefault(entry["sha256"], entry["split"])
        if previous != entry["split"]:
            raise ValueError("Byte-identical images crossed split boundaries")
    result["split_hash_overlap"] = False
    write_json(manifest_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare"])
    parser.add_argument("--root", type=Path, default=Path("data/qualification/coco-person"))
    parser.add_argument("--train", type=int, default=1000)
    parser.add_argument("--valid", type=int, default=200)
    parser.add_argument("--test", type=int, default=500)
    args = parser.parse_args()
    report = prepare(args.root.resolve(), args.train, args.valid, args.test)
    print(json.dumps(report["splits"], indent=2))


if __name__ == "__main__":
    main()
