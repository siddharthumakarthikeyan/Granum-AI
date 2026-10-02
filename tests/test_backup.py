import json
import zipfile
from pathlib import Path

import pytest

from granum import Table
from granum.core.backup import BackupError, backup_project, restore_project
from granum.core.integrity import IntegrityError, media_manifest, verify_media
from granum.core.layout import ProjectLayout
from granum.core.qa import QaError, QaLog, review_fingerprints
from granum.core.schemas import ImageSchema
from granum.core.url import Url, sample_key


def source(tmp_path):
    image = tmp_path / "external.png"
    image.write_bytes(b"original media")
    table = Table.from_dict_data({"image": [str(image)]}, schema={"image": ImageSchema(sample_type="url")}, project_name="p", dataset_name="d", table_name="train")
    return table, image


@pytest.mark.parametrize("manifest", [{}, [], {"format_version": 1, "algorithm": "sha256", "files": []},
    {"format_version": 1, "algorithm": "sha256", "files": {"x": {"bytes": -1, "sha256": "0" * 64}}}])
def test_malformed_media_manifest_is_rejected(manifest):
    with pytest.raises(IntegrityError):
        verify_media(manifest)


def test_portable_snapshot_roundtrip_with_approval_and_missing_original_media(isolated_project, tmp_path):
    table, image = source(tmp_path)
    log = QaLog("p", "d")
    fingerprints = review_fingerprints(table)
    log.set_status(fingerprints, "reviewed", fingerprints=fingerprints)
    release = log.release("v1", {"train": {"url": str(table.url), "name": table.name, "images": 1, "verified": 1}})
    log.approve(release["id"])
    archive = tmp_path / "backup.zip"
    result = backup_project("p", archive, root=Url(isolated_project))
    assert result["media"] == 1
    image.unlink()
    restored = restore_project(archive, root=Url(isolated_project), name="restored")
    assert restored["verified"]
    new_table = Table.from_url(ProjectLayout(isolated_project).table("restored", "d", "train"))
    assert Path(new_table[0]["image"]).read_bytes() == b"original media"
    assert new_table.project_name == "restored"
    QaLog("restored", "d").require_approved(release["id"], [str(new_table.url)])
    with pytest.raises(BackupError, match="never overwrites"):
        restore_project(archive, root=Url(isolated_project), name="restored")


def test_media_changed_or_missing_is_reported_and_approval_fails(isolated_project, tmp_path):
    table, image = source(tmp_path)
    manifest = media_manifest([table])
    log = QaLog("p", "d")
    f = review_fingerprints(table)
    log.set_status(f, "reviewed", fingerprints=f)
    r = log.release("v1", {"train": {"url": str(table.url), "name": table.name, "images": 1, "verified": 1}})
    image.write_bytes(b"changed media!")
    assert verify_media(manifest)["changed"] == [sample_key(str(image))]
    with pytest.raises(QaError):
        log.approve(r["id"])
    image.unlink()
    assert verify_media(manifest)["missing"] == [sample_key(str(image))]


@pytest.mark.parametrize("kind", ["traversal", "checksum", "future", "unlisted", "size"])
def test_unsafe_or_damaged_archive_never_publishes(isolated_project, tmp_path, kind):
    source(tmp_path)
    good = tmp_path / "good.zip"
    backup_project("p", good, root=Url(isolated_project))
    with zipfile.ZipFile(good) as z:
        contents = {n: z.read(n) for n in z.namelist()}
    manifest = json.loads(contents["manifest.json"])
    first = next(iter(manifest["files"]))
    if kind == "traversal":
        manifest["files"]["project/../../escape"] = manifest["files"].pop(first)
        contents["project/../../escape"] = contents.pop(first)
    elif kind == "checksum":
        contents[first] += b"tampered"
    elif kind == "future":
        manifest["format_version"] = 999
    elif kind == "unlisted":
        contents["project/unlisted"] = b"unexpected"
    contents["manifest.json"] = json.dumps(manifest).encode()
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        for n, data in contents.items():
            z.writestr(n, data)
    with pytest.raises(BackupError):
        restore_project(bad, root=Url(isolated_project), name="must-not-exist", max_bytes=1 if kind == "size" else 100000000)
    assert not Path(ProjectLayout(isolated_project).project("must-not-exist").path).exists()
    assert not (tmp_path / "escape").exists()