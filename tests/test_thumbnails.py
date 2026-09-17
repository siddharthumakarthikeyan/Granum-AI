import io

import pytest

from granum import Table
from granum.core.layout import ProjectLayout
from granum.core.schemas import ImageSchema, StringSchema
from granum.service import thumbnails as thumbs

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


@pytest.fixture
def photo_table(isolated_project, tmp_path):
    images = tmp_path / "photos"
    images.mkdir()
    paths = []
    for i in range(3):
        target = images / f"{i}.png"
        Image.new("RGB", (400, 300), (i * 40, 90, 200)).save(target)
        paths.append(str(target))
    table = Table.from_dict_data(
        {"image": paths, "caption": ["a", "b", "c"]},
        schema={"image": ImageSchema(sample_type="url"), "caption": StringSchema()},
        project_name="demo", dataset_name="photos",
    )
    return table, paths


def test_image_columns_detected(photo_table):
    table, _ = photo_table
    assert thumbs.image_columns(table) == ["image"]


def test_thumbnail_key_is_stable_and_short():
    key = thumbs.thumbnail_key("/some/very/long/path/to/an/image.jpg")
    assert key == thumbs.thumbnail_key("/some/very/long/path/to/an/image.jpg")
    assert len(key) == 32
    assert key != thumbs.thumbnail_key("/different.jpg")


def test_render_thumbnail_downscales_and_keeps_aspect():
    source = io.BytesIO()
    Image.new("RGB", (400, 200), (10, 20, 30)).save(source, "PNG")
    data = thumbs.render_thumbnail(source.getvalue(), 64)
    with Image.open(io.BytesIO(data)) as out:
        assert max(out.size) == 64
        assert out.size == (64, 32)


def test_create_for_table_writes_every_size(photo_table):
    table, paths = photo_table
    result = thumbs.create_for_table(table, sizes=(64, 128))
    assert result["images"] == 3
    assert result["written"] == 6      # 3 images x 2 sizes
    assert result["failed"] == 0

    cache_dir = ProjectLayout(__import__("granum").get_config().project_root).thumbnails(
        "demo", "photos"
    )
    assert thumbs.thumbnail_url(cache_dir, paths[0], 64).exists()
    assert thumbs.thumbnail_url(cache_dir, paths[0], 128).exists()


def test_second_run_skips_existing(photo_table):
    table, _ = photo_table
    thumbs.create_for_table(table, sizes=(64,))
    again = thumbs.create_for_table(table, sizes=(64,))
    assert again["written"] == 0
    assert again["skipped"] == 3


def test_overwrite_regenerates(photo_table):
    table, _ = photo_table
    thumbs.create_for_table(table, sizes=(64,))
    again = thumbs.create_for_table(table, sizes=(64,), overwrite=True)
    assert again["written"] == 3


def test_dry_run_writes_nothing(photo_table):
    table, paths = photo_table
    result = thumbs.create_for_table(table, sizes=(64,), dry_run=True)
    assert result["written"] == 3
    cache_dir = ProjectLayout(__import__("granum").get_config().project_root).thumbnails(
        "demo", "photos"
    )
    assert not thumbs.thumbnail_url(cache_dir, paths[0], 64).exists()


def test_thumbnail_is_much_smaller_than_the_original(photo_table):
    from granum.core.url import Url

    table, paths = photo_table
    thumbs.create_for_table(table, sizes=(64,))
    cache_dir = ProjectLayout(__import__("granum").get_config().project_root).thumbnails(
        "demo", "photos"
    )
    original = len(Url(paths[0]).read_bytes())
    thumbnail = len(thumbs.thumbnail_url(cache_dir, paths[0], 64).read_bytes())
    assert thumbnail < original


def test_unreadable_image_is_counted_not_fatal(isolated_project, tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_text("this is not a png")
    table = Table.from_dict_data(
        {"image": [str(broken)]},
        schema={"image": ImageSchema(sample_type="url")},
        project_name="demo", dataset_name="broken",
    )
    result = thumbs.create_for_table(table, sizes=(64,))
    assert result["failed"] == 1
    assert result["written"] == 0


def test_table_without_images_is_a_no_op(isolated_project):
    table = Table.from_dict_data({"a": [1, 2]}, project_name="demo", dataset_name="plain")
    assert thumbs.create_for_table(table)["images"] == 0


def test_nearest_size_rounds_up():
    assert thumbs.nearest_size(50, (64, 128, 256)) == 64
    assert thumbs.nearest_size(64, (64, 128, 256)) == 64
    assert thumbs.nearest_size(100, (64, 128, 256)) == 128
    assert thumbs.nearest_size(9000, (64, 128, 256)) == 256


def test_resolve_returns_none_when_absent(photo_table):
    table, paths = photo_table
    cache_dir = ProjectLayout(__import__("granum").get_config().project_root).thumbnails(
        "demo", "photos"
    )
    assert thumbs.resolve([cache_dir], paths[0], 64) is None
    thumbs.create_for_table(table, sizes=(64,))
    assert thumbs.resolve([cache_dir], paths[0], 64) is not None


def test_service_serves_the_thumbnail_when_asked(photo_table, isolated_project):
    """The dashboard asks for a size; it must get the small copy, not the original."""
    from fastapi.testclient import TestClient

    import granum
    from granum.core.index import Index
    from granum.core.url import Url
    from granum.service.app import create_app

    table, paths = photo_table
    thumbs.create_for_table(table, sizes=(64,))
    index = Index([isolated_project])
    index.refresh()
    client = TestClient(create_app(index=index, config=granum.get_config(), allowed_hosts=["testserver"]))

    full = client.get("/api/media", params={"url": paths[0]})
    small = client.get(
        "/api/media",
        params={"url": paths[0], "size": 64, "project": "demo", "dataset": "photos"},
    )
    assert full.status_code == small.status_code == 200
    assert len(small.content) < len(full.content)
    assert len(small.content) < len(Url(paths[0]).read_bytes())
