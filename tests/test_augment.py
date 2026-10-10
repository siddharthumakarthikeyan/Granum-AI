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


def test_blur_and_noise_take_a_limit_and_the_kinds_to_use():
    # A recipe saved before kinds existed still works, and records the kind it gets.
    assert normalize_recipe({"copies": 1, "blur": {"max": 2}})["blur"] == {"max": 2.0, "gaussian": True}
    recipe = normalize_recipe({"copies": 1, "blur": {"max": 3, "median": True, "box": True, "gaussian": False},
                               "noise": {"max": 10, "salt_pepper": True, "iso": True}})
    assert recipe["blur"] == {"max": 3.0, "median": True, "box": True}
    assert recipe["noise"] == {"max": 10.0, "salt_pepper": True, "iso": True}
    for bad in ({"blur": {"max": 2, "motion": True}}, {"blur": {"median": True}}, {"noise": {"max": 80, "iso": True}}):
        with pytest.raises(AugmentError):
            normalize_recipe({"copies": 1, **bad})

    kinds = {draw(recipe, 40, 40, np.random.default_rng(seed)).blur_type for seed in range(40)}
    assert kinds == {"median", "box"}
    assert draw(recipe, 40, 40, np.random.default_rng(0), fixed="max").noise_type == "salt_pepper"

    rng = np.random.default_rng(3)
    source = Image.fromarray(rng.integers(0, 256, size=(40, 40, 3), dtype=np.uint8))
    for kind in ("gaussian", "median", "average", "box"):
        d = draw(normalize_recipe({"copies": 1, "blur": {"max": 3, kind: True}}), 40, 40, rng, fixed="max")
        out = np.asarray(apply_image(source, d), dtype=float)
        assert d.blur_type == kind and out.std() < np.asarray(source, dtype=float).std()
    # A wide median keeps the frame, removes specks and leaves flat areas as they were.
    specks = np.full((90, 120, 3), 200, dtype=np.uint8)
    specks[::9, ::9] = 0
    wide = np.asarray(apply_image(Image.fromarray(specks), draw(normalize_recipe({"copies": 1, "blur": {"max": 20, "median": True}}), 120, 90, rng, fixed="max")))
    assert wide.shape == specks.shape and wide.min() > 150
    flat = Image.new("RGB", (40, 40), (120, 120, 120))
    for kind in ("gaussian", "salt_pepper", "iso"):
        d = draw(normalize_recipe({"copies": 1, "noise": {"max": 10, kind: True}}), 40, 40, rng, fixed="max")
        out = np.asarray(apply_image(flat, d))
        assert d.noise_type == kind and out.shape == (40, 40, 3) and out.std() > 0
    # Salt and pepper only ever writes black or white.
    d = draw(normalize_recipe({"copies": 1, "noise": {"max": 10, "salt_pepper": True}}), 40, 40, rng, fixed="max")
    assert set(np.unique(np.asarray(apply_image(flat, d)))) == {0, 120, 255}


def test_translation_and_zoom_move_the_image_and_its_labels():
    recipe = normalize_recipe({"copies": 1, "translation": {"horizontal_min": -10, "horizontal_max": 20, "vertical_min": 0, "vertical_max": 50}})
    low = draw(recipe, 100, 50, np.random.default_rng(0), fixed="min")
    high = draw(recipe, 100, 50, np.random.default_rng(0), fixed="max")
    assert low.geometric and high.geometric and high.size == (100, 50)
    assert apply_instances([{"vertices": [20, 10, 40, 20]}], low)[0]["vertices"] == [10, 10, 30, 20]
    assert apply_instances([{"vertices": [20, 10, 40, 20]}], high)[0]["vertices"] == [40, 35, 60, 45]
    image = Image.new("RGB", (100, 50), (200, 0, 0))
    moved = apply_image(image, high)
    assert moved.getpixel((5, 40)) == (0, 0, 0) and moved.getpixel((60, 40)) == (200, 0, 0)
    for seed in range(10):
        d = draw(recipe, 100, 50, np.random.default_rng(seed))
        assert -10 <= d.matrix[0, 2] <= 20 and 0 <= d.matrix[1, 2] <= 25

    zoom = normalize_recipe({"copies": 1, "zoom": {"min": 50, "max": 200}})
    out_ = draw(zoom, 100, 100, np.random.default_rng(0), fixed="min")
    in_ = draw(zoom, 100, 100, np.random.default_rng(0), fixed="max")
    assert out_.size == in_.size == (100, 100)
    # About the centre: zooming out halves a box around it, zooming in doubles it.
    assert apply_instances([{"vertices": [40, 40, 60, 60]}], out_)[0]["vertices"] == [45, 45, 55, 55]
    assert apply_instances([{"vertices": [40, 40, 60, 60]}], in_)[0]["vertices"] == [30, 30, 70, 70]
    assert apply_image(Image.new("RGB", (100, 100), (9, 9, 9)), out_).getpixel((5, 5)) == (0, 0, 0)
    assert not draw(normalize_recipe({"copies": 1, "zoom": {"min": 100, "max": 100}}), 100, 100, np.random.default_rng(0)).geometric

    for bad in (
        {"translation": {"horizontal_min": 5, "horizontal_max": 0, "vertical_min": 0, "vertical_max": 0}},
        {"translation": {"horizontal_min": 0, "horizontal_max": 0, "vertical_min": 9, "vertical_max": 1}},
        {"translation": {"horizontal_min": 0, "horizontal_max": 5}},
        {"zoom": {"min": 5, "max": 100}},
    ):
        with pytest.raises(AugmentError):
            normalize_recipe({"copies": 1, **bad})


def test_gamma_bends_the_tones_and_leaves_labels_alone():
    recipe = normalize_recipe({"copies": 1, "gamma": {"min": 0.5, "max": 2}})
    dark = draw(recipe, 10, 10, np.random.default_rng(0), fixed="min")
    bright = draw(recipe, 10, 10, np.random.default_rng(0), fixed="max")
    assert (dark.gamma, bright.gamma) == (0.5, 2.0) and not dark.geometric
    grey = Image.new("RGB", (10, 10), (128, 128, 128))
    assert apply_image(grey, dark).getpixel((0, 0))[0] < 128 < apply_image(grey, bright).getpixel((0, 0))[0]
    # Black and white stay where they are.
    assert apply_image(Image.new("RGB", (4, 4), (255, 255, 255)), dark).getpixel((0, 0)) == (255, 255, 255)
    assert apply_image(Image.new("RGB", (4, 4)), bright).getpixel((0, 0)) == (0, 0, 0)
    with pytest.raises(AugmentError):
        normalize_recipe({"copies": 1, "gamma": {"min": 0, "max": 1}})


def test_grid_mask_blacks_out_a_regular_grid():
    recipe = normalize_recipe({"copies": 1, "gridmask": {"size_min": 10, "size_max": 20, "ratio_min": 0.3, "ratio_max": 0.5}})
    white = Image.new("RGB", (100, 100), (255, 255, 255))
    low = draw(recipe, 100, 100, np.random.default_rng(0), fixed="min")
    high = draw(recipe, 100, 100, np.random.default_rng(0), fixed="max")
    assert (low.gridmask_size, low.gridmask_ratio, high.gridmask_size, high.gridmask_ratio) == (10, 0.3, 20, 0.5)
    assert not low.geometric
    # Holes are ratio x ratio of each cell.
    assert (np.asarray(apply_image(white, low)) == 0).mean() == pytest.approx(0.09, abs=0.01)
    assert (np.asarray(apply_image(white, high)) == 0).mean() == pytest.approx(0.25, abs=0.01)
    for seed in range(10):
        d = draw(recipe, 100, 100, np.random.default_rng(seed))
        assert 10 <= d.gridmask_size <= 20 and 0.3 <= d.gridmask_ratio <= 0.5
    # A preview at reduced size keeps the grid in proportion.
    small = np.asarray(apply_image(white.resize((50, 50)), high, scale=0.5))
    assert (small == 0).mean() == pytest.approx(0.25, abs=0.02)
    for bad in ({"size_min": 30, "size_max": 20, "ratio_min": 0.3, "ratio_max": 0.5},
                {"size_min": 10, "size_max": 20, "ratio_min": 0.3, "ratio_max": 1},
                {"size": 10, "ratio": 0.5}):
        with pytest.raises(AugmentError):
            normalize_recipe({"copies": 1, "gridmask": bad})


def test_every_augmentation_together_in_one_recipe():
    from granum.core.augment import describe

    recipe = normalize_recipe({
        "copies": 2, "flip": {"horizontal": True}, "rotate90": {"clockwise": True}, "crop": {"min": 0, "max": 20},
        "rotation": {"min": -15, "max": 15}, "shear": {"horizontal": 10, "vertical": 10},
        "translation": {"horizontal_min": -10, "horizontal_max": 10, "vertical_min": -10, "vertical_max": 10},
        "zoom": {"min": 80, "max": 120}, "grayscale": {"percent": 50}, "hue": {"min": -15, "max": 15},
        "saturation": {"min": -25, "max": 25}, "brightness": {"min": -20, "max": 20}, "exposure": {"min": -10, "max": 10},
        "gamma": {"min": 0.8, "max": 1.2}, "blur": {"max": 2, "gaussian": True, "median": True, "average": True, "box": True},
        "noise": {"max": 5, "gaussian": True, "salt_pepper": True, "iso": True}, "cutout": {"count": 3, "size": 10},
        "gridmask": {"size_min": 8, "size_max": 16, "ratio_min": 0.2, "ratio_max": 0.4},
    })
    assert len(describe(recipe)) == len(recipe) - 1
    assert "blur max 2 (gaussian, median, average, box)" in describe(recipe)
    image = Image.fromarray(np.random.default_rng(0).integers(0, 256, size=(48, 64, 3), dtype=np.uint8))
    instances = [{"vertices": [20, 15, 44, 33], "label": 0}]
    for seed in range(25):
        d = draw(recipe, 64, 48, np.random.default_rng(seed))
        assert apply_image(image, d).size == d.size
        for box in apply_instances(instances, d):
            x0, y0, x1, y1 = box["vertices"]
            assert 0 <= x0 < x1 <= d.size[0] and 0 <= y0 < y1 <= d.size[1]
    for at in ("min", "max"):
        d = draw(recipe, 64, 48, np.random.default_rng(0), fixed=at)
        assert apply_image(image.resize((32, 24)), d, scale=0.5).size == (round(d.size[0] * 0.5), round(d.size[1] * 0.5))
