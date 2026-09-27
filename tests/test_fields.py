"""The columns a reader can sort, group, filter and summarise by, and what they add up to."""

import math

import pytest
from fastapi.testclient import TestClient

import granum
from granum import Table
from granum.core.fields import (
    describe_field,
    field_label,
    field_values,
    scalar_fields,
    summarize,
    usable_fields,
)
from granum.core.index import Index
from granum.core.schemas import (
    BoolSchema,
    EmbeddingSchema,
    ExampleIdSchema,
    CategoricalLabelSchema,
    Float32Schema,
    ImageSchema,
    Int32Schema,
    Int32ListSchema,
    SampleWeightSchema,
    StringSchema,
)
from granum.core.schemas.geometry import BoundingBoxes2DSchema
from granum.service.cache import ByteCache
from granum.core.url import Url
from granum.errors import TableError
from granum.service.app import create_app


def P(path):
    return str(Url(path))


def test_field_label_reads_like_a_person_wrote_it():
    assert field_label("removed_from") == "Removed from"
    assert field_label("width") == "Width"
    assert field_label("capture-time") == "Capture time"
    assert field_label("") == ""


def test_kinds_come_from_meaning_not_storage():
    assert describe_field("weight", SampleWeightSchema())["kind"] == "number"
    assert describe_field("width", Int32Schema())["kind"] == "number"
    assert describe_field("score", Float32Schema())["kind"] == "number"
    assert describe_field("night", BoolSchema())["kind"] == "bool"
    assert describe_field("city", StringSchema())["kind"] == "string"
    weather = describe_field("weather", CategoricalLabelSchema(classes=["sun", "rain"]))
    assert weather["kind"] == "class" and weather["classes"] == {"0": "sun", "1": "rain"}
    # The picture, the boxes over it, a vector and a list column offer a reader nothing.
    assert describe_field("image", ImageSchema(sample_type="url")) is None
    assert describe_field("boxes", BoundingBoxes2DSchema()) is None
    assert describe_field("vector", EmbeddingSchema(shape=(8,))) is None
    assert describe_field("crowd", Int32ListSchema()) is None


def test_identifiers_are_marked_by_type_here_and_by_content_later():
    # A name is a guess: `sequence` is named like an identifier and is a drone set's most
    # useful facet. Only a kind says so for certain; the rest is decided over the values.
    assert describe_field("id", ExampleIdSchema())["identifier"] is True
    assert "identifier" not in describe_field("image_id", Int32Schema())
    assert "identifier" not in describe_field("sequence", StringSchema())


def make_table(name, images, **columns):
    schema = {"image": ImageSchema(sample_type="url"), "width": Int32Schema(),
              "city": StringSchema(), "night": BoolSchema(), "licence": StringSchema()}
    data = {"image": images, **columns}
    return Table.from_dict_data(data, schema=schema, project_name="demo",
                                dataset_name="streets", table_name=name)


def test_scalar_fields_and_values_skip_the_picture_and_the_nulls():
    table = make_table("train", [P("/a.png"), P("/b.png")], width=[640, None],
                       city=["Aachen", "Bonn"], night=[True, False], licence=["CC", "CC"])
    fields = scalar_fields(table)
    # `weight` comes from the table writer, not the caller's schema, and is a field like any other.
    assert [f["name"] for f in fields] == ["width", "city", "night", "licence", "weight"]

    values = field_values(table, fields)
    assert values[0] == {"width": 640, "city": "Aachen", "night": True, "licence": "CC", "weight": 1.0}
    # A null is left out rather than sent: a missing key and a null key read the same.
    assert "width" not in values[1]

    usable = usable_fields(fields, values)
    # `licence` says the same thing about every image, so it is not offered.
    assert [f["name"] for f in usable] == ["width", "city", "night"]
    assert {f["name"]: f["present"] for f in usable} == {"width": 1, "city": 2, "night": 2}
    # Few enough values to list, so the browser gets them without scanning.
    assert next(f for f in usable if f["name"] == "city")["values"] == ["Aachen", "Bonn"]
    assert "values" not in next(f for f in usable if f["name"] == "width")


def test_scalar_fields_skips_what_the_caller_already_shows():
    table = make_table("train", [P("/a.png")], width=[1], city=["Aachen"], night=[True], licence=["CC"])
    assert [f["name"] for f in scalar_fields(table, skip={"city", "licence", "weight"})] == ["width", "night"]


def test_summarize_a_number_column():
    summary = summarize([1, 2, 3, 4, None, float("nan")])
    assert summary["count"] == 6 and summary["present"] == 4 and summary["missing"] == 2
    assert summary["min"] == 1 and summary["max"] == 4 and summary["sum"] == 10
    assert summary["mean"] == 2.5
    assert math.isclose(summary["std"], math.sqrt(1.25))
    assert summary["quantiles"] == {"0.25": 1.75, "0.5": 2.5, "0.75": 3.25}
    assert summary["distinct"] == 4


def test_summarize_one_value_has_no_spread():
    summary = summarize([7.5, 7.5])
    assert summary["min"] == summary["max"] == summary["mean"] == 7.5
    assert summary["std"] == 0
    assert summary["quantiles"]["0.5"] == 7.5


def test_summarize_a_string_column_ranks_its_values():
    summary = summarize(["a", "b", "a", None, "c", "a"])
    assert summary["present"] == 5 and summary["missing"] == 1 and summary["distinct"] == 3
    assert summary["top"][0] == {"value": "a", "count": 3}
    # Nothing numeric to report, rather than a mean of strings read as zero.
    assert "mean" not in summary and "quantiles" not in summary


def test_summarize_nothing():
    summary = summarize([])
    assert summary == {"count": 0, "present": 0, "missing": 0, "distinct": 0, "top": []}


def test_summarize_does_not_average_booleans():
    # True is an int in Python; averaging a flag column would be a number that means nothing.
    summary = summarize([True, False, True])
    assert "mean" not in summary
    assert summary["top"][0]["count"] == 2


def test_images_endpoint_offers_the_sets_own_columns():
    make_table("train", [P("/a.png"), P("/b.png")], width=[640, 1280],
               city=["Aachen", "Bonn"], night=[True, False], licence=["CC", "CC"])
    make_table("valid", [P("/c.png")], width=[800], city=["Cologne"], night=[True], licence=["CC"])
    index = Index([granum.get_config().project_root])
    index.refresh()
    api = TestClient(create_app(index=index, config=granum.get_config(), cache=ByteCache(),
                                allowed_hosts=["testserver"], serve_dashboard=False))

    payload = api.get("/api/images", params={"project": "demo", "dataset": "streets"}).json()
    fields = {f["name"]: f for f in payload["fields"]}
    assert set(fields) == {"width", "city", "night"}
    assert fields["city"]["values"] == ["Aachen", "Bonn", "Cologne"]
    assert fields["width"]["kind"] == "number" and fields["width"]["label"] == "Width"

    by_image = {i["image"]: i for i in payload["images"]}
    assert by_image[P("/a.png")]["values"] == {"width": 640, "city": "Aachen", "night": True}
    # The constant column is pruned from the rows as well as from the descriptors.
    assert all("licence" not in (i.get("values") or {}) for i in payload["images"])


def test_table_summary_asks_the_same_question_of_a_whole_column():
    table = make_table("train", [P("/a.png"), P("/b.png"), P("/c.png")], width=[640, 1280, None],
                       city=["Aachen", "Bonn", "Bonn"], night=[True, False, True], licence=["CC"] * 3)
    assert table.summary("width")["mean"] == 960
    assert table.summary("width")["missing"] == 1
    assert table.summary("city")["top"][0] == {"value": "Bonn", "count": 2}
    with pytest.raises(TableError):
        table.summary("nope")


def test_a_blob_column_is_not_a_field():
    # A COCO import keeps the original record as JSON. It is 200 characters per image, it
    # cannot be filtered on, and shipping one per image would cost megabytes.
    schema = {"image": ImageSchema(sample_type="url"), "coco_image": StringSchema(), "city": StringSchema()}
    blob = '{"license":1,"file_name":"%s.jpg","date_captured":"2026-09-16T12:22:19+00:00","extra":{"name":"a long original name that pushes this past the limit"}}'
    table = Table.from_dict_data(
        {"image": [P("/a.png"), P("/b.png")], "coco_image": [blob % "a", blob % "b"], "city": ["Aachen", "Bonn"]},
        schema=schema, project_name="demo", dataset_name="streets", table_name="train")
    fields = scalar_fields(table)
    values = field_values(table, fields)
    assert [f["name"] for f in usable_fields(fields, values)] == ["city"]


def test_a_nearly_unique_string_is_dropped_and_a_nearly_unique_number_is_marked():
    schema = {"image": ImageSchema(sample_type="url"), "content_hash": StringSchema(), "image_id": Int32Schema()}
    # Enough images for uniqueness to mean something: in a set of five, every column looks
    # like an identifier.
    images = [P(f"/{i}.png") for i in range(40)]
    table = Table.from_dict_data(
        {"image": images, "content_hash": [f"hash-{i}" for i in range(40)], "image_id": list(range(40))},
        schema=schema, project_name="demo", dataset_name="streets", table_name="train")
    fields = usable_fields(scalar_fields(table), field_values(table, scalar_fields(table)))
    by_name = {f["name"]: f for f in fields}
    assert "content_hash" not in by_name
    assert by_name["image_id"]["identifier"] is True


def test_values_are_listed_until_there_are_too_many_of_them():
    from granum.core.fields import MAX_LISTED_VALUES

    schema = {"image": ImageSchema(sample_type="url"), "sequence": StringSchema()}
    count = MAX_LISTED_VALUES + 40
    images = [P(f"/{i}.png") for i in range(count * 2)]
    # Two images per sequence, so no sequence is nearly unique.
    table = Table.from_dict_data(
        {"image": images, "sequence": [f"s{i // 2}" for i in range(count * 2)]},
        schema=schema, project_name="demo", dataset_name="streets", table_name="train")
    fields = scalar_fields(table)
    field = usable_fields(fields, field_values(table, fields))[0]
    assert field["distinct"] == count and field["wide"] is True and "values" not in field


def test_a_wide_import_is_cut_to_a_payload_budget():
    from granum.core import fields as fields_module

    rows = 200
    # Two images per value, so no column reads as an identifier.
    columns = {f"c{i}": [f"value-{i}-{r // 2}" for r in range(rows)] for i in range(8)}
    schema = {"image": ImageSchema(sample_type="url"),
              **{name: StringSchema() for name in columns}}
    table = Table.from_dict_data(
        {"image": [P(f"/{r}.png") for r in range(rows)], **columns},
        schema=schema, project_name="demo", dataset_name="wide", table_name="train")
    described = scalar_fields(table)
    values = field_values(table, described)
    everything = usable_fields(described, values)
    assert len(everything) == 8

    # A budget that fits three of them keeps the first three, in schema order.
    budget = sum(len("c0") + 4 + len("value-0-00") for _ in range(rows)) * 3 + 10
    original = fields_module.MAX_VALUES_BYTES
    try:
        fields_module.MAX_VALUES_BYTES = budget
        kept = usable_fields(described, values)
    finally:
        fields_module.MAX_VALUES_BYTES = original
    assert [f["name"] for f in kept] == ["c0", "c1", "c2"]
