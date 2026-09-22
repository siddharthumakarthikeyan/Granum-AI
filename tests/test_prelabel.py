"""Pre-labelling: a model's boxes become labels, and never pretend to be anyone else's."""

import pytest

from granum import BoundingBoxes2D, Table
from granum.core.prelabel import MANUAL, MODEL, PrelabelError, box_column, write_prelabelled


def boxes(*instances, width=100.0, height=100.0):
    return {"width": width, "height": height,
            "instances": [{"vertices": list(v), "label": label} for v, label in instances]}


def prediction(*instances, width=100.0, height=100.0):
    return {"width": width, "height": height,
            "instances": [{"vertices": list(v), "label": label, "confidence": c} for v, label, c in instances]}


@pytest.fixture
def unlabelled(isolated_project):
    """Three images: one labelled by a person, two with nothing on them."""
    return Table.from_dict_data(
        {"image": ["/d/a.png", "/d/b.png", "/d/c.png"],
         "bbs": [boxes(([10, 10, 30, 30], 0)), boxes(), None]},
        schema={"bbs": BoundingBoxes2D.schema(["car", "van"])},
        project_name="draft", dataset_name="street", table_name="train",
    )


def instances_of(table, row):
    return table.to_arrow().column("bbs").to_pylist()[row]["instances"]


def test_a_model_fills_the_empty_images_and_leaves_the_labelled_one_alone(unlabelled):
    written = write_prelabelled(
        unlabelled,
        {0: prediction(([12, 12, 28, 28], 1, 0.9)),
         1: prediction(([40, 40, 60, 60], 0, 0.8), ([70, 70, 90, 90], 1, 0.6)),
         2: prediction(([5, 5, 15, 15], 0, 0.7))},
        model="yolo26m.pt",
    )
    assert (written["images"], written["boxes"], written["kept"]) == (2, 3, 1)
    table = written["table"]

    # The labelled image keeps its own box, now marked as a person's.
    kept = instances_of(table, 0)
    assert len(kept) == 1 and kept[0]["label"] == 0
    assert kept[0]["source"] == MANUAL and kept[0]["confidence"] is None

    drafted = instances_of(table, 1)
    assert [i["label"] for i in drafted] == [0, 1]
    assert [i["source"] for i in drafted] == [MODEL, MODEL]
    assert drafted[0]["confidence"] == pytest.approx(0.8)

    # A row with no geometry at all gets the size the model saw.
    empty = table.to_arrow().column("bbs").to_pylist()[2]
    assert (empty["width"], empty["height"]) == (100.0, 100.0)
    assert len(empty["instances"]) == 1


def test_replacing_draws_over_a_person_only_when_asked(unlabelled):
    written = write_prelabelled(unlabelled, {0: prediction(([12, 12, 28, 28], 1, 0.9))},
                                model="yolo26m.pt", mode="replace")
    assert written["images"] == 1 and written["kept"] == 0
    drafted = instances_of(written["table"], 0)
    assert len(drafted) == 1 and drafted[0]["label"] == 1 and drafted[0]["source"] == MODEL
    # The labels that were there are where they always were: in the version before this one.
    assert instances_of(unlabelled, 0)[0]["label"] == 0


def test_the_new_version_is_a_version_of_the_same_set(unlabelled):
    written = write_prelabelled(unlabelled, {1: prediction(([40, 40, 60, 60], 0, 0.8))}, model="m.pt")
    table = written["table"]
    assert table.base_name == unlabelled.base_name
    assert table.parents == (unlabelled.url,)
    assert table.producer["op"] == "prelabel"
    assert table.producer["args"]["model"] == "m.pt" and table.producer["args"]["boxes"] == 1
    assert box_column(table) == "bbs"


def test_pre_labelling_twice_does_not_relabel_the_first_draft_as_a_persons(unlabelled):
    once = write_prelabelled(unlabelled, {1: prediction(([40, 40, 60, 60], 0, 0.8))}, model="m.pt")["table"]
    twice = write_prelabelled(once, {2: prediction(([5, 5, 15, 15], 0, 0.7))}, model="m.pt")["table"]
    assert [i["source"] for i in instances_of(twice, 1)] == [MODEL]
    assert [i["source"] for i in instances_of(twice, 2)] == [MODEL]
    assert [i["source"] for i in instances_of(twice, 0)] == [MANUAL]


def test_a_mode_nobody_defined_is_refused(unlabelled):
    with pytest.raises(PrelabelError):
        write_prelabelled(unlabelled, {}, model="m.pt", mode="overwrite-everything")


def test_a_set_with_no_box_column_says_so(isolated_project):
    plain = Table.from_dict_data({"image": ["/d/a.png"]}, project_name="draft", dataset_name="street",
                                 table_name="images")
    with pytest.raises(PrelabelError):
        write_prelabelled(plain, {}, model="m.pt")
