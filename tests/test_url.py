import pytest

from granum import Url
from granum.core.url import (
    contract_aliases,
    expand_aliases,
    get_registered_url_aliases,
    register_url_alias,
    unregister_url_alias,
)
from granum.errors import AliasConflictError


def test_bare_paths_become_absolute():
    assert str(Url("relative/path")).startswith("/")


def test_join_and_parts():
    url = Url("/data") / "project" / "train.parquet"
    assert str(url) == "/data/project/train.parquet"
    assert url.name == "train.parquet"
    assert url.stem == "train"
    assert url.suffix == ".parquet"
    assert str(url.parent) == "/data/project"
    assert url.scheme == "file"


def test_remote_scheme_preserved():
    url = Url("s3://bucket/prefix") / "images" / "a.jpg"
    assert str(url) == "s3://bucket/prefix/images/a.jpg"
    assert url.scheme == "s3"
    assert str(url.parent) == "s3://bucket/prefix/images"


def test_url_is_hashable_and_equal():
    assert Url("/a/b") == Url("/a/b/")
    assert len({Url("/a/b"), Url("/a/b")}) == 1


def test_empty_url_rejected():
    with pytest.raises(ValueError):
        Url("   ")


def test_read_write_roundtrip(tmp_path):
    url = Url(str(tmp_path)) / "nested" / "file.txt"
    url.write_text("hello")
    assert url.exists()
    assert url.read_text() == "hello"
    assert url.parent.is_dir()


def test_ls_returns_urls(tmp_path):
    base = Url(str(tmp_path))
    (base / "a.txt").write_text("a")
    (base / "b.txt").write_text("b")
    names = [u.name for u in base.ls()]
    assert names == ["a.txt", "b.txt"]


def test_alias_expand_and_contract():
    register_url_alias("PROJECT_DATA", "/data/project")
    assert expand_aliases("<PROJECT_DATA>/1.jpg") == "/data/project/1.jpg"
    assert contract_aliases("/data/project/1.jpg") == "<PROJECT_DATA>/1.jpg"
    assert get_registered_url_aliases()["PROJECT_DATA"] == "/data/project"


def test_alias_longest_prefix_wins():
    register_url_alias("DATA", "/data")
    register_url_alias("PROJECT", "/data/project")
    assert contract_aliases("/data/project/1.jpg") == "<PROJECT>/1.jpg"


def test_alias_conflict_requires_force():
    register_url_alias("PROJECT_DATA", "/data/project")
    with pytest.raises(AliasConflictError):
        register_url_alias("PROJECT_DATA", "/somewhere/else")
    register_url_alias("PROJECT_DATA", "/somewhere/else", force=True)
    assert get_registered_url_aliases()["PROJECT_DATA"] == "/somewhere/else"


def test_unregister_alias():
    register_url_alias("TEMP", "/tmp/x")
    unregister_url_alias("TEMP")
    assert "TEMP" not in get_registered_url_aliases()


def test_aliased_url_resolves_for_io(tmp_path):
    register_url_alias("HERE", str(tmp_path))
    url = Url("<HERE>/note.txt")
    url.write_text("via alias")
    assert (tmp_path / "note.txt").read_text() == "via alias"
    assert url.resolved == f"{tmp_path}/note.txt"
