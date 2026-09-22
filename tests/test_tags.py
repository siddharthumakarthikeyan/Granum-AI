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
