import pytest

from granum import Table
from granum.core.qa import QaError, QaLog, review_fingerprints
from granum.core.schemas import CategoricalLabelSchema, ImageSchema


def dataset(root):
    root.mkdir(parents=True, exist_ok=True)
    paths = [root / "a.png", root / "b.png"]
    for path in paths:
        path.write_bytes(b"test media bytes")
    return Table.from_dict_data(
        {"image": [str(p) for p in paths], "label": [0, 1]},
        schema={"image": ImageSchema(sample_type="url"), "label": CategoricalLabelSchema(classes=["a", "b"])},
        project_name="p", dataset_name="d", table_name="train",
    )


def freeze(log, table, name="v1", mode="all"):
    return log.release(name, {"train": {"url": str(table.url), "name": table.name, "images": len(table), "verified": len(table)}}, mode=mode)


def test_selected_review_can_skip_an_unrelated_split(isolated_project):
    table = dataset(isolated_project)
    fingerprints = review_fingerprints(table)
    first = next(iter(fingerprints))
    assert review_fingerprints(table, [first]) == {first: fingerprints[first]}
    assert review_fingerprints(table, []) == {}
    assert review_fingerprints(table, [str(isolated_project / "not-in-this-set.png")]) == {}


def test_subset_and_client_counts_never_imply_approval(isolated_project):
    table = dataset(isolated_project)
    log = QaLog("p", "d")
    release = freeze(log, table, mode="verified")
    assert release["approval"] == "exploratory"
    with pytest.raises(QaError, match="exact annotations"):
        log.approve(release["id"])
    with pytest.raises(QaError, match="exploratory"):
        log.require_approved(release["id"], [str(table.url)])


def test_approval_requires_pinned_reviews_and_rejects_changed_labels(isolated_project):
    table = dataset(isolated_project)
    log = QaLog("p", "d")
    fingerprints = review_fingerprints(table)
    log.set_status(fingerprints, "reviewed")
    release = freeze(log, table)
    with pytest.raises(QaError):
        log.approve(release["id"])
    log.set_status(fingerprints, "reviewed", fingerprints=fingerprints, author="reviewer")
    approved = log.approve(release["id"], author="approver")
    assert approved["approval_record"]["author"] == "approver"
    assert log.require_approved(release["id"], [str(table.url)])["id"] == release["id"]
    assert log.approve(release["id"])["approval_record"] == approved["approval_record"]
    changed = table.apply_edits(values={"label": {0: 1}})
    with pytest.raises(QaError, match="exact annotations"):
        log.approve(freeze(log, changed, "changed")["id"])
    with pytest.raises(QaError, match="all training inputs"):
        log.require_approved(release["id"], [str(changed.url)])
    log.delete_release(release["id"])
    with pytest.raises(QaError):
        log.require_approved(release["id"], [str(table.url)])