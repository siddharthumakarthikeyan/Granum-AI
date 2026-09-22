"""The neighbour graph: duplicates, leaks, uniqueness and outliers on vectors we control.

The maths is tested on hand-made vectors rather than on real images, so a failure means the rule
is wrong rather than that a model changed. One test does run the real descriptor embedder over
drawn images, because "a resized copy is found" is the claim that matters most and it has to hold
end to end.
"""

import time

import numpy as np
import pytest
from PIL import Image

from granum.metrics.embeddings import (
    NeighbourPolicy,
    available_embedder,
    describe_embedder,
    duplicate_groups,
    embed_images,
    group_spread,
    leaks,
    neighbours,
    normalise,
    outlier_scores,
    project,
    similar_to,
    source_key,
    summarise,
    typical_distance,
    uniqueness,
)


def spread(count: int, dimensions: int = 16, seed: int = 0) -> np.ndarray:
    """Vectors with nothing in common: every pair far apart."""
    generator = np.random.default_rng(seed)
    return normalise(generator.normal(size=(count, dimensions)).astype(np.float32))


def test_a_copy_is_its_own_nearest_neighbour_group():
    vectors = spread(12)
    vectors[5] = vectors[2]  # an exact copy
    index, distance = neighbours(vectors, k=5)
    groups = duplicate_groups(index, distance, typical_distance(vectors))
    assert groups == [[2, 5]]


def test_duplicate_groups_are_transitive():
    # A chain of small differences: three re-exports of one picture.
    vectors = spread(10)
    base = vectors[0]
    vectors[1] = normalise((base + 0.01 * spread(1, seed=9)[0])[None])[0]
    vectors[2] = normalise((vectors[1] + 0.01 * spread(1, seed=8)[0])[None])[0]
    index, distance = neighbours(vectors, k=5)
    assert [0, 1, 2] in duplicate_groups(index, distance, typical_distance(vectors))


def test_the_same_geometry_gives_the_same_answer_at_any_scale():
    # Five images: 1 and 3 are a copy pair, everything else is ordinary. The second dataset is
    # the first with every distance ten times smaller -- a set of images of one place rather
    # than of the world. With the unit scaled the same way, the answer must not move.
    index = np.array([[3, 2, 4], [2, 0, 4], [1, 0, 4], [0, 2, 1], [0, 1, 2]], np.int32)
    close = np.array([[0.002, 0.30, 0.34], [0.28, 0.30, 0.33], [0.28, 0.30, 0.31],
                      [0.002, 0.31, 0.33], [0.31, 0.33, 0.34]], np.float32)
    assert duplicate_groups(index, close, 0.40) == [[0, 3]]
    assert duplicate_groups(index, close / 10, 0.040) == [[0, 3]]
    # ...and with the unit left at the larger set's value, everything looks like a duplicate.
    assert len(duplicate_groups(index, close / 10, 0.40)[0]) == 5


def export(stem: str, hash_: str, split: str = "train") -> str:
    """A filename as Roboflow writes it: the source stem, then this copy's own hash."""
    return f"/d/{split}/{stem}_jpg.rf.{hash_ * 32:.32}.jpg"


def test_the_source_of_an_exported_copy_is_read_from_its_name():
    assert source_key(export("frame_07", "a")) == "frame_07"
    # Two exports of one picture, dealt into different splits, are still one picture.
    assert source_key(export("frame_07", "b", "valid")) == "frame_07"
    # Nothing to read: an image is its own source, and nothing is grouped by accident.
    assert source_key("/d/train/frame_07.jpg") == "/d/train/frame_07.jpg"
    assert source_key("/d/train/aug_0001.jpg", augmented_from="/d/train/frame_07.jpg") == "/d/train/frame_07.jpg"


def test_an_augmented_copy_is_an_export_not_a_duplicate():
    """A flip of a picture looks exactly like the picture. Only its name says which it is."""
    vectors = spread(10)
    vectors[3] = vectors[2]  # the flip: as close as anything can be
    keys = [export(f"frame_{i}", "a") for i in range(10)]
    keys[3] = export("frame_2", "b")  # ...and the same source as keys[2]
    sets = ["train"] * 10
    index, distance = neighbours(vectors, k=5)
    report = summarise(keys, sets, vectors, index, distance, sources=[source_key(k) for k in keys])

    assert report["duplicates"]["groups"] == []
    assert report["duplicates"]["redundant"] == 0
    assert report["exports"]["sources"] == 9 and report["exports"]["repeated"] == 1
    assert report["exports"]["groups"][0]["source"] == "frame_2"
    assert report["exports"]["groups"][0]["images"] == [keys[2], keys[3]]


def test_two_different_pictures_that_are_the_same_shot_are_still_duplicates():
    """The rule separates sources, it does not switch the check off."""
    vectors = spread(10)
    vectors[5] = vectors[1]
    keys = [export(f"frame_{i}", "a") for i in range(10)]
    keys.append(export("frame_1", "b"))  # an augmented copy of frame_1 as well
    vectors = np.vstack([vectors, vectors[1][None]])
    sets = ["train"] * 11
    index, distance = neighbours(vectors, k=5)
    report = summarise(keys, sets, vectors, index, distance, sources=[source_key(k) for k in keys])

    group = report["duplicates"]["groups"][0]
    assert set(group) == {keys[1], keys[5], keys[10]}
    # Three images, two pictures: one picture to remove, and it takes its own copy with it.
    assert report["duplicates"]["redundant"] == 1
    assert sorted(report["duplicates"]["families"][0]) == [0, 0, 1]


def test_an_exported_copy_in_another_split_leaks_however_far_apart_it_looks():
    # A heavy colour shift puts the copy nowhere near its source in the embedding; the split
    # is still cut through one picture, which is the whole of what a leak is.
    vectors = spread(8)
    keys = [export(f"frame_{i}", "a") for i in range(8)]
    keys[6] = export("frame_1", "b", "valid")
    sets = ["train"] * 8
    sets[6] = "valid"
    index, distance = neighbours(vectors, k=4)
    found = leaks(index, distance, sets, typical_distance(vectors),
                  sources=[source_key(k) for k in keys], vectors=vectors)

    pair = next(item for item in found if item["same_source"])
    assert {item["a"] for item in found if item["same_source"]} <= {1, 6}
    assert pair["sets"] == ["train", "valid"] and pair["distance"] > 0.3


def test_a_continuum_is_reported_as_a_chain_not_as_duplicates():
    # Frames of one long take: each near the next, no two the same photograph.
    steps = normalise(np.stack([[np.cos(t / 400), np.sin(t / 400), 0.0] for t in range(120)]).astype(np.float32))
    keys = [f"/take/{i:03d}.jpg" for i in range(120)]
    index, distance = neighbours(steps, k=6)
    report = summarise(keys, ["train"] * 120, steps, index, distance)
    assert report["duplicates"]["groups"] == []
    assert len(report["chains"]) == 1 and report["chains"][0]["images"] == 120


def test_the_unit_survives_a_dataset_that_is_mostly_copies():
    # Half the set is export copies of the other half. A unit taken from nearest-neighbour
    # distance would collapse to nearly zero here; the typical distance does not move.
    base = spread(40)
    doubled = np.vstack([base, base])
    assert typical_distance(doubled) == pytest.approx(typical_distance(base), rel=0.25)
    index, distance = neighbours(doubled, k=5)
    groups = duplicate_groups(index, distance, typical_distance(doubled))
    assert len(groups) == 40 and all(len(group) == 2 for group in groups)


def test_uniqueness_ranks_copies_last_and_isolated_images_first():
    # Uniqueness reads the whole neighbourhood, not only the nearest image, so a copy in an
    # otherwise varied set is not zero -- it is the least unique thing in the set, which is the
    # property the sort depends on.
    vectors = spread(20)
    vectors[1] = vectors[0]  # a copy of image 0
    index, distance = neighbours(vectors, k=5)
    scores = uniqueness(index, distance, typical_distance(vectors))
    assert set(np.argsort(scores)[:2]) == {0, 1}
    assert ((scores >= 0) & (scores <= 1)).all()


def test_an_image_with_nothing_like_it_scores_as_an_outlier():
    vectors = np.vstack([normalise(np.tile([1.0, 0.0, 0.0], (12, 1)) + 0.01 * spread(12, 3)),
                         normalise(np.array([[0.0, 0.0, 1.0]], dtype=np.float32))])
    index, distance = neighbours(vectors, k=4)
    scores = outlier_scores(distance, typical_distance(vectors))
    assert scores[-1] == scores.max() and scores[-1] > NeighbourPolicy().outlier


def test_the_furthest_images_are_listed_even_when_none_is_far_enough_to_be_alone():
    """A set with no isolated image still has a loneliest one, and that is what to show.

    Half the datasets worth checking are one subject shot by one camera: nothing in them
    passes the threshold, and a tab that answered "no outliers" would be telling the reader
    the check does not work rather than what it found.
    """
    tight = normalise(np.tile([1.0, 0.0, 0.0], (10, 1)) + 0.02 * spread(10, 3))
    keys = [f"/data/{i}.jpg" for i in range(10)]
    index, distance = neighbours(tight, k=4)
    report = summarise(keys, ["train"] * 10, tight, index, distance)
    listed = report["outliers"]
    assert len(listed) == 10 and not any(row["alone"] for row in listed)
    assert [row["score"] for row in listed] == sorted((row["score"] for row in listed), reverse=True)

    # The same set with one image of something else: that one, and only it, is alone.
    apart = np.vstack([tight, normalise(np.array([[0.0, 0.0, 1.0]], dtype=np.float32))])
    index, distance = neighbours(apart, k=4)
    report = summarise([*keys, "/data/odd.jpg"], ["train"] * 11, apart, index, distance)
    assert report["outliers"][0] == {"image": "/data/odd.jpg", "score": report["outliers"][0]["score"],
                                     "set": "train", "alone": True}
    assert [row["alone"] for row in report["outliers"]].count(True) == 1


def test_leaks_are_only_reported_across_sets():
    vectors = spread(8)
    vectors[6] = vectors[1]        # the same picture in train and valid
    vectors[3] = vectors[2]        # a duplicate inside train: not a leak
    sets = ["train"] * 5 + ["valid"] * 3
    index, distance = neighbours(vectors, k=4)
    found = leaks(index, distance, sets, typical_distance(vectors))
    assert [(item["a"], item["b"]) for item in found] == [(1, 6)]
    assert found[0]["sets"] == ["train", "valid"]


def test_similar_to_never_returns_the_image_itself():
    vectors = spread(30)
    rows = similar_to(vectors, 4, k=5)
    assert len(rows) == 5 and all(index != 4 for index, _ in rows)
    assert rows == sorted(rows, key=lambda item: item[1])  # nearest first


def test_the_map_is_two_dimensional_bounded_and_repeatable():
    vectors = spread(40)
    points = project(vectors)
    assert points.shape == (40, 2)
    assert points.min() >= -1.0001 and points.max() <= 1.0001
    assert np.allclose(points, project(vectors))


def test_summary_names_images_not_row_numbers():
    vectors = spread(6)
    vectors[4] = vectors[0]
    keys = [f"/data/{i}.jpg" for i in range(6)]
    sets = ["train", "train", "train", "train", "valid", "valid"]
    index, distance = neighbours(vectors, k=3)
    report = summarise(keys, sets, vectors, index, distance)
    assert report["duplicates"]["groups"] == [["/data/0.jpg", "/data/4.jpg"]]
    assert report["duplicates"]["redundant"] == 1
    assert report["leaks"][0]["a"] == "/data/0.jpg" and report["leaks"][0]["b"] == "/data/4.jpg"
    assert set(report["uniqueness"]) == set(keys)


def test_empty_and_single_image_sets_do_not_raise():
    empty = np.zeros((0, 8), np.float32)
    index, distance = neighbours(empty, k=5)
    assert duplicate_groups(index, distance, 1.0) == [] and uniqueness(index, distance, 1.0).size == 0
    assert summarise([], [], empty, index, distance)["images"] == 0
    one = spread(1)
    index, distance = neighbours(one, k=5)
    assert duplicate_groups(index, distance, typical_distance(one)) == [] and similar_to(one, 0) == []


# -- the real embedder ------------------------------------------------------


def drawing(path, colour, size=(160, 120), box=None):
    image = Image.new("RGB", size, colour)
    if box:
        for x in range(box[0], box[2]):
            for y in range(box[1], box[3]):
                image.putpixel((x, y), (255, 255, 255))
    image.save(path)
    return str(path)


def test_a_resized_copy_is_found_by_the_plain_descriptor(tmp_path):
    original = drawing(tmp_path / "a.png", (30, 60, 120), box=(20, 20, 90, 80))
    resized = Image.open(original).resize((320, 240))
    resized.save(tmp_path / "a_big.png")
    others = [drawing(tmp_path / f"o{i}.png", (200 - i * 30, 40 + i * 20, i * 40),
                      box=(i * 5, i * 4, 40 + i * 6, 30 + i * 5)) for i in range(6)]

    paths = [original, str(tmp_path / "a_big.png"), *others]
    vectors, failed = embed_images(paths, embedder="descriptor")
    assert failed == [] and vectors.shape[0] == len(paths)
    index, distance = neighbours(vectors, k=3)
    assert [0, 1] in duplicate_groups(index, distance, typical_distance(vectors))


def test_an_unreadable_image_is_reported_not_swallowed(tmp_path):
    good = drawing(tmp_path / "good.png", (10, 20, 30))
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    vectors, failed = embed_images([good, str(broken)], embedder="descriptor")
    assert failed == [1] and len(vectors) == 2


def test_the_chosen_embedder_describes_its_own_limits():
    assert describe_embedder("descriptor")["semantic"] is False
    assert describe_embedder("mobilenet_v3_small")["semantic"] is True
    assert available_embedder("descriptor") == "descriptor"


@pytest.mark.skipif(available_embedder() == "descriptor", reason="the training add-on is not installed")
def test_the_neural_embedder_groups_pictures_of_the_same_thing(tmp_path):
    # Two shades of one scene against three unrelated ones; the pair must be nearest neighbours.
    pair = [drawing(tmp_path / "s1.png", (40, 90, 160), box=(30, 20, 120, 90)),
            drawing(tmp_path / "s2.png", (44, 96, 168), box=(28, 18, 118, 88))]
    others = [drawing(tmp_path / f"x{i}.png", (220 - i * 60, 30, 30 + i * 70),
                      box=(5, 60 + i * 5, 30 + i * 10, 110)) for i in range(3)]
    vectors, _ = embed_images([*pair, *others])
    assert similar_to(vectors, 0, k=1)[0][0] == 1


# -- through the service ----------------------------------------------------


def dataset_with_a_copy(tmp_path):
    """A small dataset whose valid set holds a resized copy of a train image."""
    from granum import Table
    from granum.core.url import Url

    folder = tmp_path / "shapes"
    folder.mkdir()
    train = [drawing(folder / f"t{i}.png", (40 + i * 30, 90, 160 - i * 20),
                     box=(10 + i * 4, 10 + i * 3, 60 + i * 5, 70)) for i in range(5)]
    Image.open(train[1]).resize((320, 240)).save(folder / "v_copy.png")
    valid = [str(folder / "v_copy.png"),
             drawing(folder / "v1.png", (200, 30, 30), box=(50, 40, 120, 100))]

    tables = {}
    for name, paths in (("train", train), ("valid", valid)):
        tables[name] = Table.from_dict_data(
            {"image": [str(Url(p)) for p in paths]},
            project_name="look", dataset_name="shapes", table_name=name,
        )
    return tables


@pytest.fixture
def api(isolated_project, tmp_path):
    from fastapi.testclient import TestClient

    import granum
    from granum.core.index import Index
    from granum.service.app import create_app

    tables = dataset_with_a_copy(tmp_path)
    index = Index([granum.get_config().project_root])
    index.refresh()
    client = TestClient(create_app(index=index, config=granum.get_config(),
                                   allowed_hosts=["testserver"], serve_dashboard=False))
    return client, tables


def compute(client, wait=60):
    started = client.post("/api/embeddings", json={"project": "look", "dataset": "shapes",
                                                   "embedder": "descriptor"})
    assert started.status_code == 200, started.text
    job = started.json()
    for _ in range(wait):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] != "running":
            break
        time.sleep(0.2)
    assert job["status"] == "done", job
    return job


def test_the_service_embeds_a_dataset_and_finds_the_copy(api):
    client, tables = api
    before = client.get("/api/embeddings", params={"project": "look", "dataset": "shapes"}).json()
    assert before["status"] is None and before["images"] == 7 and before["missing"] == 7

    compute(client)

    after = client.get("/api/embeddings", params={"project": "look", "dataset": "shapes"}).json()
    assert after["status"]["images"] == 7 and after["missing"] == 0
    assert after["status"]["embedder"]["semantic"] is False  # the plain descriptor says so

    report = client.get("/api/embeddings/report", params={"project": "look", "dataset": "shapes"}).json()
    groups = report["duplicates"]["groups"]
    assert any(len(group) == 2 and any("t1.png" in image for image in group)
               and any("v_copy.png" in image for image in group) for group in groups)
    # The copy straddles train and valid, so it is also a leak.
    assert report["leaks"] and set(report["leaks"][0]["sets"]) == {"train", "valid"}


def test_a_group_of_re_exports_reads_as_tighter_than_a_chain_of_frames():
    """The spread separates "the same photograph twice" from "a sequence worth thinning"."""
    vectors = spread(12)
    vectors[1] = vectors[0]  # the same photograph again
    # Three frames of one fixed camera: each near the last, the ends not near each other.
    step = spread(1, seed=4)[0]
    for offset in range(1, 4):
        vectors[4 + offset] = normalise((vectors[4] + 0.05 * offset * step)[None])[0]
    scale = typical_distance(vectors)
    index, distance = neighbours(vectors, k=6)
    groups = duplicate_groups(index, distance, scale)
    copies = next(group for group in groups if 0 in group)
    chained = next(group for group in groups if 5 in group)
    assert group_spread(vectors, copies, scale) == 0.0
    assert group_spread(vectors, chained, scale) > group_spread(vectors, copies, scale)


def test_the_report_follows_the_dataset_as_it_stands_now(api):
    """A duplicate deleted from the dataset stops being one; restored, it is one again.

    The vectors are keyed by image and outlive every version, so the graph has to be read
    against the sets as they are today -- otherwise the dashboard would keep offering to
    delete an image that is already gone.
    """
    client, tables = api
    compute(client)
    params = {"project": "look", "dataset": "shapes"}

    def paired(report: dict, name: str) -> bool:
        """Is this image in a duplicate group, and on one side of a cross-set leak?"""
        in_group = any(any(name in image for image in group) for group in report["duplicates"]["groups"])
        return in_group and any(name in pair["a"] or name in pair["b"] for pair in report["leaks"])

    before = client.get("/api/embeddings/report", params=params).json()
    assert paired(before, "v_copy")
    assert before["dropped"] == 0 and before["missing"] == 0

    copy = tables["valid"][0]["image"]
    assert "v_copy" in copy
    removed = client.post("/api/datasets/remove", json={
        "project": "look", "table": str(tables["valid"].url), "samples": [copy], "reason": "a copy"})
    assert removed.status_code == 200, removed.text

    after = client.get("/api/embeddings/report", params=params).json()
    assert not paired(after, "v_copy")
    assert after["images"] == before["images"] - 1
    # The vector is kept: the image left the dataset, not the disk.
    assert after["dropped"] == 1 and after["missing"] == 0

    client.post("/api/datasets/restore", json={"project": "look", "dataset": "shapes", "samples": [copy]})
    back = client.get("/api/embeddings/report", params=params).json()
    assert paired(back, "v_copy") and back["dropped"] == 0 and back["images"] == before["images"]


def test_similar_and_scores_are_served_per_image(api):
    client, tables = api
    compute(client)
    image = tables["train"][1]["image"]
    similar = client.get("/api/embeddings/similar",
                         params={"project": "look", "dataset": "shapes", "image": image, "k": 3}).json()
    assert len(similar["neighbours"]) == 3
    assert "v_copy.png" in similar["neighbours"][0]["image"]  # its own copy is nearest

    scores = client.get("/api/embeddings/scores", params={"project": "look", "dataset": "shapes"}).json()
    assert len(scores["uniqueness"]) == 7 and image in scores["duplicated"]

    points = client.get("/api/embeddings/map", params={"project": "look", "dataset": "shapes"}).json()
    assert len(points["points"]) == 7 and len(points["points"][0]) == 2


def test_neighbours_are_answered_over_the_dataset_as_it_stands_now(api):
    """A deleted image is not offered as something to look at, and never as a neighbour.

    The vectors outlive every version of a set, so "what else looks like this" has to be
    joined to the sets as they are -- otherwise the answer is a list of images the gallery
    cannot show.
    """
    client, tables = api
    compute(client)
    image = tables["train"][1]["image"]
    copy = tables["valid"][0]["image"]
    params = {"project": "look", "dataset": "shapes", "image": image, "k": 6}

    before = client.get("/api/embeddings/similar", params=params).json()
    assert before["set"] == "train"
    # Every distance is read against this: the median distance between two random images.
    assert before["scale"] > 0
    assert "v_copy.png" in before["neighbours"][0]["image"]
    assert before["neighbours"][0]["distance"] < before["scale"]
    assert all(neighbour["image"] != image for neighbour in before["neighbours"])

    removed = client.post("/api/datasets/remove", json={
        "project": "look", "table": str(tables["valid"].url), "samples": [copy], "reason": "a copy"})
    assert removed.status_code == 200, removed.text

    after = client.get("/api/embeddings/similar", params=params).json()
    assert all("v_copy.png" not in neighbour["image"] for neighbour in after["neighbours"])
    # The deleted image is still a question that can be asked, just not an answer.
    gone = client.get("/api/embeddings/similar",
                      params={**params, "image": copy}).json()
    assert gone["set"] is None
    assert any(neighbour["image"] == image for neighbour in gone["neighbours"])


def test_asking_before_computing_says_so_rather_than_failing(api):
    client, _ = api
    for path in ("/api/embeddings/report", "/api/embeddings/scores", "/api/embeddings/map"):
        response = client.get(path, params={"project": "look", "dataset": "shapes"})
        assert response.status_code == 404 and "embeddings" in response.text
