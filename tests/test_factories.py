import pytest

from granum import Table
from granum.core.objects.table import infer_schema
from granum.core.schemas import (
    CategoricalLabelSchema,
    EmbeddingSchema,
    Float32Schema,
    ImageSchema,
    Int64Schema,
    StringSchema,
)
from granum.errors import TableError

# -- inference --------------------------------------------------------------


def test_infer_schema_by_value_type():
    assert isinstance(infer_schema([1, 2]), Int64Schema)
    assert isinstance(infer_schema([1.5]), Float32Schema)
    assert isinstance(infer_schema(["x"]), StringSchema)
    assert isinstance(infer_schema([[0.1, 0.2]]), EmbeddingSchema)


def test_infer_schema_detects_images():
    assert isinstance(infer_schema(["/a/b.jpg"]), ImageSchema)
    assert isinstance(infer_schema(["/a/b"], name="image"), ImageSchema)


def test_infer_schema_skips_nones():
    assert isinstance(infer_schema([None, 3]), Int64Schema)


# -- image folder -----------------------------------------------------------


def test_from_image_folder(image_folder):
    table = Table.from_image_folder(image_folder, project_name="demo")
    assert len(table) == 5
    assert table.columns == ["image", "label", "weight"]
    assert table.get_simple_value_map("label") == {0: "cat", 1: "dog"}
    assert table.dataset_name == "pets"
    labels = [row["label"] for row in table]
    assert labels.count(0) == 3 and labels.count(1) == 2


def test_from_image_folder_ignores_non_images(image_folder):
    table = Table.from_image_folder(image_folder, project_name="demo")
    assert all(not row["image"].endswith(".txt") for row in table)


def test_from_image_folder_stores_paths_not_pixels(image_folder):
    table = Table.from_image_folder(image_folder, project_name="demo")
    assert str(image_folder) in table[0]["image"]


def test_from_image_folder_errors(tmp_path):
    with pytest.raises(TableError):
        Table.from_image_folder(tmp_path / "missing", project_name="demo")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(TableError):
        Table.from_image_folder(empty, project_name="demo")
    no_images = tmp_path / "shell"
    (no_images / "classA").mkdir(parents=True)
    with pytest.raises(TableError):
        Table.from_image_folder(no_images, project_name="demo")


def test_image_folder_table_is_a_torch_style_dataset(image_folder):
    """The adoption test: a Table indexes like a Dataset with no conversion step."""
    table = Table.from_image_folder(image_folder, project_name="demo")
    assert len(table) == 5
    sample = table[0]
    assert set(sample) == {"image", "label", "weight"}


# -- pandas / csv / parquet -------------------------------------------------


def test_from_pandas():
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"image": ["/a.jpg", "/b.jpg"], "label": [0, 1]})
    table = Table.from_pandas(df, project_name="demo", dataset_name="train")
    assert len(table) == 2
    assert isinstance(table.schema["image"], ImageSchema)


def test_to_pandas_roundtrip():
    pytest.importorskip("pandas")
    table = Table.from_dict_data({"a": [1, 2, 3]}, project_name="demo")
    assert list(table.to_pandas()["a"]) == [1, 2, 3]


def test_from_csv(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("image,label\n/a.jpg,0\n/b.jpg,1\n")
    table = Table.from_csv(path, project_name="demo", dataset_name="train")
    assert len(table) == 2
    assert table[0]["image"] == "/a.jpg"


def test_from_csv_empty_rejected(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("image,label\n")
    with pytest.raises(TableError):
        Table.from_csv(path, project_name="demo")


def test_from_parquet(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "data.parquet"
    pq.write_table(pa.table({"a": [1, 2, 3]}), str(path))
    table = Table.from_parquet(path, project_name="demo", dataset_name="train")
    assert len(table) == 3


def test_explicit_schema_beats_inference():
    table = Table.from_dict_data(
        {"label": [0, 1]},
        schema={"label": CategoricalLabelSchema(classes=["cat", "dog"])},
        project_name="demo",
    )
    assert isinstance(table.schema["label"], CategoricalLabelSchema)
