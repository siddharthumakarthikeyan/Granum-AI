"""Augmented copies for dataset versions: recipes, geometry on every label kind, pixels."""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from granum.core.augment import (
    AugmentError,
    Draw,
    apply_image,
    apply_instances,
    draw,
    normalize_recipe,
)


def test_recipe_is_checked_and_tidied():
    assert normalize_recipe(None) is None
    assert normalize_recipe({"copies": 3}) is None  # nothing to do
    recipe = normalize_recipe({"copies": 2, "flip": {"horizontal": True, "vertical": False}, "rotation": {"min": -10, "max": 15}})
    assert recipe == {"copies": 2, "flip": {"horizontal": True}, "rotation": {"min": -10.0, "max": 15.0}}
    for bad in (
        {"copies": 0, "flip": {"horizontal": True}},
        {"copies": 11, "flip": {"horizontal": True}},
        {"copies": 2, "warp": {"max": 1}},
        {"copies": 2, "rotation": {"min": 20, "max": 10}},
        {"copies": 2, "rotation": {"min": -500, "max": 10}},
        {"copies": 2, "blur": {"max": "a lot"}},
        {"copies": 2, "flip": {"diagonal": True}},
    ):
        with pytest.raises(AugmentError):
            normalize_recipe(bad)


def _identity(width: int, height: int) -> Draw:
    return Draw(matrix=np.eye(3), size=(width, height), geometric=True)


def test_horizontal_flip_mirrors_boxes_masks_and_keypoints():
    d = _identity(100, 50)
    d.matrix = np.array([[-1, 0, 100], [0, 1, 0], [0, 0, 1.0]])
    [out] = apply_instances([{
        "vertices": [10, 5, 30, 25], "label": 1, "area": 400.0,
        "segmentation": json.dumps([[10, 5, 30, 5, 30, 25]]),
        "coco_extra": json.dumps({"keypoints": [12, 6, 2, 0, 0, 0], "num_keypoints": 1}),
    }], d)
    assert out["vertices"] == [70, 5, 90, 25]
    assert json.loads(out["segmentation"]) == [[90, 5, 70, 5, 70, 25]]
    assert json.loads(out["coco_extra"])["keypoints"] == [88, 6, 2, 0, 0, 0]
    assert out["area"] == 200.0  # the triangle, not the box


def test_quarter_turn_swaps_the_frame():
    for seed in range(20):
        d = draw({"copies": 1, "rotate90": {"clockwise": True}}, 100, 50, np.random.default_rng(seed))
        if d.geometric:
            break
    assert d.size == (50, 100)
    [out] = apply_instances([{"vertices": [0, 0, 10, 20]}], d)
    # Clockwise: the top-left corner goes to the top-right.
    assert out["vertices"] == [30, 0, 50, 10]
    image = apply_image(Image.new("RGB", (100, 50)), d)
    assert image.size == (50, 100)


def test_boxes_mostly_cut_off_are_dropped_and_masks_clipped():
    d = _identity(100, 100)
    d.matrix = np.array([[2, 0, 0], [0, 2, 0], [0, 0, 1.0]])  # zoom into the top-left quarter
    kept = apply_instances([
        {"vertices": [10, 10, 20, 20]},                          # stays whole
        {"vertices": [48, 10, 70, 20]},                          # 4 of 44 px wide stays: dropped
        {"vertices": [40, 40, 60, 60], "segmentation": json.dumps([[40, 40, 60, 40, 60, 60, 40, 60]])},
    ], d)
    assert [k["vertices"] for k in kept] == [[20, 20, 40, 40], [80, 80, 100, 100]]
    [mask] = json.loads(kept[1]["segmentation"])
    assert set(zip(mask[0::2], mask[1::2])) == {(80, 80), (100, 80), (100, 100), (80, 100)}


def test_keypoints_pushed_out_become_unlabelled_and_rle_masks_are_dropped():
    d = _identity(100, 100)
    d.matrix = np.array([[1, 0, 60], [0, 1, 0], [0, 0, 1.0]])  # shift right by 60
    [out] = apply_instances([{
        "vertices": [10, 10, 30, 30],
        "segmentation": json.dumps({"counts": "abc", "size": [100, 100]}),
        "coco_extra": json.dumps({"keypoints": [15, 15, 2, 50, 15, 2], "num_keypoints": 2}),
    }], d)
    assert out["segmentation"] is None
    extra = json.loads(out["coco_extra"])
    assert extra["keypoints"] == [75, 15, 2, 0, 0, 0] and extra["num_keypoints"] == 1


def test_colour_only_draws_leave_labels_alone_and_change_pixels():
    recipe = normalize_recipe({"copies": 1, "brightness": {"min": 40, "max": 40}, "grayscale": {"percent": 100}})
    d = draw(recipe, 20, 10, np.random.default_rng(1))
    assert not d.geometric
    instances = [{"vertices": [1, 2, 3, 4]}]
    assert apply_instances(instances, d) == instances
    out = apply_image(Image.new("RGB", (20, 10), (100, 50, 0)), d)
    r, g, b = out.getpixel((5, 5))
    assert r == g == b and r > 50


def test_fixed_draws_show_the_ends_of_a_range():
    recipe = normalize_recipe({"copies": 1, "rotation": {"min": -10, "max": 25}, "brightness": {"min": -30, "max": 40}})
    low = draw(recipe, 100, 50, np.random.default_rng(0), fixed="min")
    high = draw(recipe, 100, 50, np.random.default_rng(0), fixed="max")
    assert low.brightness == -30 and high.brightness == 40

    def angle(d: Draw) -> float:
        return round(float(np.degrees(np.arctan2(d.matrix[1, 0], d.matrix[0, 0]))), 6)

    assert (angle(low), angle(high)) == (-10, 25)
    # Nothing is random: another generator gives the same draw.
    assert np.allclose(draw(recipe, 100, 50, np.random.default_rng(1), fixed="max").matrix, high.matrix)
    flipped = draw(normalize_recipe({"copies": 1, "flip": {"vertical": True}}), 100, 50, np.random.default_rng(0), fixed="max")
    assert flipped.geometric and flipped.matrix[1, 1] == -1
    with pytest.raises(AugmentError):
        draw(recipe, 100, 50, np.random.default_rng(0), fixed="middle")
