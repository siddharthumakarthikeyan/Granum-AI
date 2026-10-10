"""Tags on images and named views: two small stores that must survive a reload."""

import pytest

from granum.core.tags import TagError, TagStore, ViewStore, clean_tag


def test_a_tag_is_a_word_a_person_can_type(isolated_project):
    assert clean_tag("  night  shots ") == "night shots"
    for bad in ("", "   ", "@night", "x" * 41):
        with pytest.raises(TagError):
            clean_tag(bad)


def test_tags_go_on_and_come_off_and_the_log_remembers(isolated_project):
    store = TagStore("p", "d")
    store.record(["/d/a.png", "/d/b.png"], add=["night"])
    store.record(["/d/a.png"], add=["recheck"])
    assert store.current() == {"/d/a.png": ["night", "recheck"], "/d/b.png": ["night"]}
    assert store.counts() == {"night": 2, "recheck": 1}

    store.record(["/d/a.png"], remove=["night"])
    assert store.current()["/d/a.png"] == ["recheck"]
    # Taking a tag off is an event, not an erasure: the log still holds what happened.
    assert len(store.events()) == 4
    # An image with no tags left is not an image with an empty list.
    store.record(["/d/b.png"], remove=["night"])
    assert "/d/b.png" not in store.current()


def test_tagging_nothing_writes_nothing(isolated_project):
    store = TagStore("p", "d")
    assert store.record([], add=["night"])["images"] == 0
    assert store.record(["/d/a.png"])["images"] == 0
    assert store.current() == {}


def test_a_view_is_saved_by_name_and_replaced_by_the_same_name(isolated_project):
    views = ViewStore("p", "d")
    first = views.save("Night, unverified", {"split": "valid", "status": "unverified"})
    assert first["state"]["split"] == "valid" and first["id"]
    again = views.save("night, unverified", {"split": "train"})
    assert len(views.all()) == 1 and views.all()[0]["state"]["split"] == "train"
    assert again["id"] != first["id"]

    views.save("Everything", {})
    assert [v["name"] for v in views.all()] == ["Everything", "night, unverified"]
    assert views.delete(again["id"]) is True
    assert [v["name"] for v in views.all()] == ["Everything"]
    assert views.delete("nothing") is False


def test_a_view_needs_a_name_and_stays_small(isolated_project):
    views = ViewStore("p", "d")
    with pytest.raises(TagError):
        views.save("   ", {})
    with pytest.raises(TagError):
        views.save("big", {"classes": list(range(2000))})


def test_a_damaged_view_file_reads_as_no_views(isolated_project):
    views = ViewStore("p", "d")
    views.save("one", {})
    views.url.write_text("{not json")
    assert views.all() == []


def test_a_tag_can_go_on_one_box_rather_than_on_the_picture():
    from granum.core.tags import TagStore
    from granum.core.url import sample_key

    store = TagStore("demo", "pets")
    store.record(["/d/a.png"], add=["night"], author="sam")
    store.record(["/d/a.png"], add=["occluded"], objects=["a12"], author="sam")
    store.record(["/d/a.png"], add=["occluded", "tiny"], objects=["i3"], author="sam")

    # The two claims stay apart: the picture is at night, one box in it is occluded.
    assert store.current() == {sample_key("/d/a.png"): ["night"]}
    assert store.current_objects() == {sample_key("/d/a.png"): {"a12": ["occluded"], "i3": ["occluded", "tiny"]}}
    assert store.counts() == {"night": 1}
    assert store.object_counts() == {"occluded": 2, "tiny": 1}

    store.record(["/d/a.png"], remove=["occluded"], objects=["i3"], author="sam")
    assert store.current_objects()[sample_key("/d/a.png")] == {"a12": ["occluded"], "i3": ["tiny"]}


def test_a_box_is_addressed_by_its_annotation_id_where_it_has_one():
    from granum.core.tags import object_key

    assert object_key({"annotation_id": 7, "label": 1}, 3) == "a7"
    assert object_key({"label": 1}, 3) == "i3"
    assert object_key(None, 0) == "i0"
    # The prefixes keep box 3 of an unnumbered image apart from annotation 3.
    assert object_key({"annotation_id": 3}, 0) != object_key({}, 3)


def test_tagging_objects_needs_exactly_one_image():
    import pytest as _pytest

    from granum.core.tags import TagError, TagStore

    store = TagStore("demo", "pets")
    with _pytest.raises(TagError):
        store.record(["/d/a.png", "/d/b.png"], add=["occluded"], objects=["i0"])
    with _pytest.raises(TagError):
        store.record(["/d/a.png"], add=["occluded"], objects=[f"i{i}" for i in range(501)])
