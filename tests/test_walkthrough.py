"""Reproducible source selection and the shipped course's actual evidence/media."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
COURSE = PUBLIC / "assets" / "course"
sys.path.insert(0, str(ROOT / "tools"))

import prepare_walkthrough as pack  # noqa: E402

import docs  # noqa: E402

LESSONS = ["start", "setup", "data", "import", "explore", "baseline", "review", "train",
           "results", "compare", "handoff", "backup", "next"]
CHAPTERS = ["01-import", "02-browse", "03-review", "04-versions", "05-train", "06-results",
            "07-experiment", "08-compare", "09-handoff", "10-restore"]


@pytest.fixture
def source(tmp_path):
    """Opaque image bytes are sufficient for packaging tests, not image-decoding tests."""
    root = tmp_path / "source"
    entries = {
        "train": [("trainA_00001.rf.a.jpg", b"train-a"), ("trainA_00001.rf.b.jpg", b"variant-a"),
                  ("validA_99999.rf.a.jpg", b"excluded-sequence"), ("trainB_00002.rf.a.jpg", b"train-b"),
                  ("trainC_00003.rf.a.jpg", b"valid-a"), ("trainD_00004.rf.a.jpg", b"train-d"),
                  ("trainE_00005.rf.a.jpg", b"train-e")],
        "valid": [("validA_00001.rf.a.jpg", b"valid-a"), ("validB_00002.rf.a.jpg", b"valid-b")],
    }
    entries["test"] = entries["valid"]
    for split, images in entries.items():
        folder = root / split
        folder.mkdir(parents=True)
        document = {
            "images": [{"id": i, "file_name": name, "width": 10, "height": 10}
                       for i, (name, _) in enumerate(images)],
            "annotations": [{"id": i, "image_id": i, "category_id": 9,
                             "bbox": [1, 2, 3, 4], "area": 12, "iscrowd": 0}
                            for i, _ in enumerate(images)],
            "categories": [{"id": 0, "name": "people"}, {"id": 9, "name": "people"},
                           {"id": 5, "name": "ignored regions"}],
        }
        (folder / "_annotations.coco.json").write_text(json.dumps(document))
        for name, content in images:
            (folder / name).write_bytes(content)
    return root


def tree_hashes(root):
    return {p.relative_to(root).as_posix(): pack.digest(p) for p in root.rglob("*") if p.is_file()}


def test_selection_is_deterministic_and_does_not_modify_source(source, tmp_path):
    before = tree_hashes(source)
    first = pack.prepare(source, tmp_path / "first", tmp_path / "first.zip", train_count=4, valid_count=2)
    second = pack.prepare(source, tmp_path / "second", tmp_path / "second.zip", train_count=4, valid_count=2)
    assert first == second
    assert tree_hashes(source) == before
    assert first["splits"] == {"train": {"images": 4, "annotations": 4}, "valid": {"images": 2, "annotations": 2}}
    manifest = json.loads((tmp_path / "first" / "manifest.json").read_text())
    train = manifest["splits"]["train"]["files"]
    valid = manifest["splits"]["valid"]["files"]
    assert not ({p["sha256"] for p in train} & {p["sha256"] for p in valid})
    assert not ({pack.sequence(p["file"]) for p in train} & {pack.sequence(p["file"]) for p in valid})
    assert len({p["file"].split(".rf.")[0] for p in train}) == 4
    with zipfile.ZipFile(tmp_path / "first.zip") as archive:
        assert all(p.startswith("aerial-mini/") for p in archive.namelist())
        assert not any(p.startswith("aerial-mini/test/") for p in archive.namelist())
        assert b"CC BY 4.0" in archive.read("aerial-mini/ATTRIBUTION.txt")
        assert b"/docs/course/start" in archive.read("aerial-mini/START-HERE.txt")
        assert all(info.date_time == (2026, 10, 2, 0, 0, 0) for info in archive.infolist())
        original = json.loads((source / "train" / "_annotations.coco.json").read_text())
        selected = json.loads(archive.read("aerial-mini/train/_annotations.coco.json"))
        assert selected["categories"] == original["categories"]
        assert all(annotation in original["annotations"] for annotation in selected["annotations"])


def test_refuses_existing_outputs_and_unsafe_destinations(source, tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    archive = tmp_path / "existing.zip"
    archive.write_bytes(b"keep me")
    for target, output in [(existing, tmp_path / "new.zip"), (tmp_path / "new", archive),
                           (source / "new", tmp_path / "new.zip"), (tmp_path / "new", source / "new.zip"),
                           (tmp_path / "new", tmp_path / "new" / "self.zip")]:
        with pytest.raises(ValueError):
            pack.prepare(source, target, output, train_count=1, valid_count=1)
    assert archive.read_bytes() == b"keep me"


@pytest.mark.parametrize("name", ["../escape.jpg", "/absolute.jpg", r"..\escape.jpg"])
def test_rejects_unsafe_image_names(tmp_path, name):
    with pytest.raises(ValueError, match="unsafe"):
        pack.safe_image(tmp_path, name)


def test_rejects_symlink_escape_and_unknown_sequence(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"private")
    (root / "link.jpg").symlink_to(outside)
    with pytest.raises(ValueError, match="unsafe"):
        pack.safe_image(root, "link.jpg")
    with pytest.raises(ValueError, match="capture-sequence"):
        pack.sequence("unrecognised.jpg")


def test_refuses_untrue_source_duplication_claim(source, tmp_path):
    (source / "test" / "validA_00001.rf.a.jpg").write_bytes(b"different test image")
    with pytest.raises(ValueError, match="does not duplicate"):
        pack.prepare(source, tmp_path / "new", tmp_path / "new.zip", train_count=1, valid_count=1)
    assert not (tmp_path / "new").exists()


def test_refuses_changed_test_annotations_and_insufficient_selection(source, tmp_path):
    with pytest.raises(ValueError, match="eligible"):
        pack.prepare(source, tmp_path / "new", tmp_path / "new.zip", train_count=20, valid_count=2)
    (source / "test" / "_annotations.coco.json").write_text('{}')
    with pytest.raises(ValueError, match="byte-identical"):
        pack.prepare(source, tmp_path / "new", tmp_path / "new.zip", train_count=1, valid_count=1)
    assert not (tmp_path / "new").exists()


def test_shipped_sample_hash_manifest_counts_and_attribution():
    expected = "2641dcdfbd88fea0bea27b59689f68b3b9a1d1fbd4b3d8c4da1a2c62789efa5d"
    archive_path = COURSE / "aerial-mini.zip"
    assert pack.digest(archive_path) == expected
    assert (COURSE / "aerial-mini.sha256").read_text().split()[0] == expected
    assert archive_path.stat().st_size == 27693885
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("aerial-mini/manifest.json"))
        hashes = set()
        for split, images, objects, ignored in [("train", 96, 5720, 158), ("valid", 24, 1780, 70)]:
            entry = manifest["splits"][split]
            coco = json.loads(archive.read(f"aerial-mini/{split}/_annotations.coco.json"))
            assert entry["images"] == len(coco["images"]) == images
            assert entry["annotations"] == len(coco["annotations"]) == objects
            assert len(coco["categories"]) == 13
            assert sum(a["category_id"] == 5 for a in coco["annotations"]) == ignored
            assert {i["file_name"] for i in coco["images"]} == {f["file"] for f in entry["files"]}
            for item in entry["files"]:
                content = archive.read(f"aerial-mini/{split}/{item['file']}")
                assert len(content) == item["bytes"]
                assert hashlib.sha256(content).hexdigest() == item["sha256"]
                assert item["sha256"] not in hashes
                hashes.add(item["sha256"])
        assert len(hashes) == 120
        assert not any(p.startswith("aerial-mini/test/") for p in archive.namelist())
        assert manifest["source_splits"]["valid"]["annotations_sha256"] == manifest["source_splits"]["test"]["annotations_sha256"]
        attribution = archive.read("aerial-mini/ATTRIBUTION.txt").decode()
        assert pack.SOURCE_URL in attribution and pack.LICENSE_URL in attribution
        assert "not independent verification" in attribution


class Media(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.videos = []
        self.assets = []
        self.transcripts = 0
        self.active_video = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "img":
            self.images.append(attrs)
        if tag == "video":
            self.active_video = {"attributes": attrs, "sources": [], "tracks": []}
            self.videos.append(self.active_video)
        if tag in ("source", "track") and self.active_video is not None:
            self.active_video["sources" if tag == "source" else "tracks"].append(attrs)
        if tag == "details" and "doc-transcript" in attrs.get("class", ""):
            self.transcripts += 1
        for key in ("src", "poster"):
            if attrs.get(key, "").startswith("/assets/course/"):
                self.assets.append(attrs[key])

    def handle_endtag(self, tag):
        if tag == "video":
            self.active_video = None


def test_course_order_structure_media_and_search_coverage():
    docs.build()
    course = next(section for section in docs.NAV if section.key == "course")
    assert course.slugs == [f"course/{name}" for name in LESSONS]
    referenced = set()
    video_names = set()
    for slug in course.slugs:
        page = docs.PAGES[slug]
        assert "Checkpoint" in page.body
        assert "What we learn" in page.body
        assert "If " in page.body
        media = Media()
        media.feed(page.body)
        assert media.transcripts >= len(media.videos), slug
        for asset in media.assets:
            assert (PUBLIC / asset.lstrip("/")).is_file(), (slug, asset)
            referenced.add(asset)
        for image in media.images:
            assert image.get("alt"), slug
            assert image.get("loading") == "lazy", slug
        for video in media.videos:
            attrs = video["attributes"]
            assert "controls" in attrs and "autoplay" not in attrs
            assert attrs.get("preload") == "none" and attrs.get("aria-label")
            assert attrs.get("poster") and attrs.get("aria-describedby")
            assert len(video["sources"]) == 1 and video["sources"][0]["type"] == "video/mp4"
            assert len(video["tracks"]) == 1
            track = video["tracks"][0]
            assert track["kind"] == "captions" and track["srclang"] == "en" and "default" in track
            chapter = Path(video["sources"][0]["src"]).stem
            video_names.add(chapter)
            metadata = json.loads((COURSE / f"{chapter}.json").read_text())
            caption = re.search(rf'<figcaption id="{attrs["aria-describedby"]}">(.*?)</figcaption>', page.body, re.S)
            assert caption and f'{math.ceil(metadata["duration"])} seconds' in caption.group(1)
    assert video_names == set(CHAPTERS)
    assert len(list(COURSE.glob("*.webp"))) == 35
    assert all(f"/assets/course/{p.name}" in referenced for p in COURSE.glob("*.webp"))
    backup = next(row for row in docs.search_index() if row["url"] == "/docs/course/backup")
    assert "relocated references and byte hashes" in backup["text"]  # Near the lesson's end, beyond 1800 characters.


def seconds(value):
    hour, minute, second = value.split(":")
    return int(hour) * 3600 + int(minute) * 60 + float(second)


@pytest.mark.parametrize("chapter", CHAPTERS)
def test_recordings_have_real_capture_metadata_and_ordered_captions(chapter):
    metadata = json.loads((COURSE / f"{chapter}.json").read_text())
    assert metadata["chapter"] == chapter
    assert "no mocked" in metadata["source"]
    assert metadata["viewport"] == {"width": 1440, "height": 960}
    assert 5 < metadata["duration"] < 120
    assert (COURSE / f"{chapter}.mp4").stat().st_size > 10000
    assert all((COURSE / f"{name}.webp").is_file() for name in metadata["shots"])
    captions = (COURSE / f"{chapter}.vtt").read_text()
    assert captions.startswith("WEBVTT\n\n")
    timings = re.findall(r"(\d\d:\d\d:\d\d\.\d{3}) --> (\d\d:\d\d:\d\d\.\d{3})", captions)
    assert len(timings) == len(metadata["cues"])
    previous = 0
    for (start, end), cue in zip(timings, metadata["cues"]):
        assert previous <= seconds(start) < seconds(end) <= metadata["duration"] + .002
        assert abs(seconds(start) - cue["at"]) < .002
        assert cue["text"] in captions
        previous = seconds(end)


def test_published_numbers_match_the_measured_course_evidence():
    evidence = json.loads((COURSE / "evidence.json").read_text())
    assert evidence["actual_training"] is True
    assert evidence["sample_sha256"] == (COURSE / "aerial-mini.sha256").read_text().split()[0]
    baseline, candidate = evidence["runs"]["baseline"], evidence["runs"]["candidate"]
    assert baseline["status"] == candidate["status"] == "finished"
    assert [baseline["parameters"]["epochs"], candidate["parameters"]["epochs"]] == [3, 12]
    assert baseline["parameters"]["evaluator"] == candidate["parameters"]["evaluator"]
    assert baseline["parameters"]["valid_version"] == candidate["parameters"]["valid_version"]
    assert evidence["comparison"]["headline"]["verdict"] == "too close to call"
    assert evidence["comparison"]["counts"]["unchanged"] == 24
    for evaluation in evidence["evaluations"].values():
        assert evaluation["images"] == 24
        assert evaluation["headline"]["fn"] == evaluation["headline"]["labels"] == 1710
        assert evaluation["headline"]["tp"] == evaluation["headline"]["fp"] == 0
    operations = json.loads((COURSE / "operations-evidence.json").read_text())
    assert operations["original_restored_hashes_and_sizes_match"]
    assert operations["all_restored_image_references_inside_rehearsal_root"]
    assert operations["original_integrity"] == operations["restored_integrity"]
    assert operations["restored_integrity"]["checked"] == 120
    assert operations["coco_export_check"]["independent_copies"]
    assert operations["coco_export_check"]["source_image_hashes_match"]