import json
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pytest

import granum
from granum import Table
from granum.core.index import Index
from granum.core.layout import OBJECT_FILENAME
from granum.core.objects.base import write_table_payload
from granum.core.qa import QaError, QaLog, _append, _read
from granum.core.storage import atomic_bytes


def _writer(root, value):
    granum.set_config(granum.Config.load(overrides={"project-root-url": root}, use_config_files=False, use_env=False))
    t = Table.from_dict_data({"x": [value]}, project_name="p", dataset_name="d", table_name="same")
    QaLog("p", "d").add_comment("image", f"writer {value}")
    return str(t.url)


def test_process_writers_reserve_distinct_revisions_and_keep_all_events(isolated_project):
    with ProcessPoolExecutor(max_workers=4) as pool:
        urls = list(pool.map(_writer, [str(isolated_project)] * 8, range(8)))
    assert len(set(urls)) == 8
    assert sorted(Table.from_url(u)[0]["x"] for u in urls) == list(range(8))
    assert len(QaLog("p", "d").events()) == 8


def test_failed_replace_preserves_previous_file_and_cleans_temporary(tmp_path, monkeypatch):
    target = tmp_path / "metadata.json"
    target.write_bytes(b"old")
    def fail(*args):
        raise OSError("injected crash before publication")
    monkeypatch.setattr("granum.core.storage.os.replace", fail)
    with pytest.raises(OSError):
        atomic_bytes(target, b"new")
    assert target.read_bytes() == b"old"
    assert list(tmp_path.glob(".granum-write-*")) == []


def test_failed_publication_is_not_indexed_or_overwritten(isolated_project, monkeypatch):
    table = Table.from_dict_data({"x": [1]})
    with pytest.raises(granum.errors.GranumError, match="overwrite"):
        write_table_payload(table.url, table.to_arrow(), table.to_dict())
    import granum.core.objects.base as base
    original = base.write_object_payload
    def fail(*args):
        raise OSError("injected interruption after parquet")
    monkeypatch.setattr(base, "write_object_payload", fail)
    with pytest.raises(OSError):
        table.set_values("weight", {0: 0.5})
    index = Index([isolated_project])
    index.refresh(force=True)
    assert len(index.tables()) == 1
    monkeypatch.setattr(base, "write_object_payload", original)
    retry = table.set_values("weight", {0: 0.5})
    assert retry[0]["weight"] == 0.5
    assert retry.url != table.url


def test_torn_tail_does_not_swallow_next_record_and_interior_corruption_fails(isolated_project):
    log = QaLog("p", "d")
    _append(log.url, [{"a": 1}])
    with open(log.url.path, "ab") as handle:
        handle.write(b'{"torn": "\xe2')
    _append(log.url, [{"a": 2}])
    assert _read(log.url) == [{"a": 1}, {"a": 2}]
    log.url.write_text('{"a":1}\nnot json\n{"a":2}\n')
    with pytest.raises(QaError, match="corrupt log"):
        _read(log.url)
    log.url.write_text('{"a":1}\n42\n')
    with pytest.raises(QaError, match="expected a JSON object"):
        _append(log.url, [{"a": 3}])


def test_run_updates_merge_across_instances_and_aggregate_writers(isolated_project):
    run = granum.init("p", "run")
    peers = [granum.Run.from_url(run.url) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda pair: pair[1].set_parameters({str(pair[0]): pair[0]}).log({"step": pair[0]}), enumerate(peers)))
    loaded = granum.Run.from_url(run.url)
    assert len(loaded.parameters) == 8
    assert len(loaded.aggregate_metrics()) == 8


def test_newer_object_format_is_rejected(isolated_project):
    table = Table.from_dict_data({"x": [1]})
    path = Path(table.url.path) / OBJECT_FILENAME
    payload = json.loads(path.read_text())
    payload["format_version"] = 999
    path.write_text(json.dumps(payload))
    with pytest.raises(granum.errors.GranumError, match="unsupported object format"):
        Table.from_url(table.url)