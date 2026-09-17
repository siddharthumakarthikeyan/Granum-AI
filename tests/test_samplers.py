from collections import Counter

import pytest

torch = pytest.importorskip("torch")

from granum import (  # noqa: E402
    Table,
    create_random_sampler,
    create_repeat_by_weight_sampler,
    create_sequential_sampler,
    create_weighted_sampler,
)
from granum.errors import TableError  # noqa: E402


def weighted(weights):
    table = Table.from_dict_data({"x": list(range(len(weights)))}, project_name="p", dataset_name="d")
    return table.apply_edits(values={"weight": dict(enumerate(weights))})


def test_weighted_sampler_never_draws_zero_weight_samples():
    table = weighted([1.0, 0.0, 1.0, 0.0])
    drawn = Counter(create_weighted_sampler(table, num_samples=2000, seed=0))
    assert set(drawn) == {0, 2}


def test_weighted_sampler_draws_in_proportion_to_weight():
    table = weighted([1.0, 3.0])
    drawn = Counter(create_weighted_sampler(table, num_samples=8000, seed=1))
    assert 2.6 < drawn[1] / drawn[0] < 3.4


def test_weighted_sampler_epoch_length_counts_non_zero_samples():
    assert len(create_weighted_sampler(weighted([1.0, 0.0, 2.0]))) == 2


def test_random_sampler_covers_each_included_sample_once():
    sampler = create_random_sampler(weighted([1.0, 0.0, 1.0, 1.0]), seed=3)
    first, second = list(sampler), list(sampler)
    assert sorted(first) == [0, 2, 3] and len(sampler) == 3
    assert sorted(second) == [0, 2, 3]


def test_random_sampler_can_include_zero_weights():
    assert sorted(create_random_sampler(weighted([1.0, 0.0]), exclude_zero_weights=False)) == [0, 1]


def test_sequential_sampler_is_ordered_and_skips_zero_weights():
    assert list(create_sequential_sampler(weighted([1.0, 0.0, 1.0]))) == [0, 2]


def test_repeat_by_weight_is_exact_for_integer_weights():
    order = list(create_repeat_by_weight_sampler(weighted([2.0, 0.0, 1.0, 3.0]), seed=0))
    assert Counter(order) == {0: 2, 2: 1, 3: 3}


def test_repeat_by_weight_honours_fractions_on_average():
    sampler = create_repeat_by_weight_sampler(weighted([1.5, 1.0]), seed=0)
    counts = Counter()
    for _ in range(400):
        counts.update(list(sampler))
    assert 560 < counts[0] < 640  # 1.5 per epoch
    assert counts[1] == 400


def test_all_zero_weights_is_an_error():
    table = weighted([0.0, 0.0])
    for factory in (create_weighted_sampler, create_random_sampler,
                    create_sequential_sampler, create_repeat_by_weight_sampler):
        with pytest.raises(TableError, match="weight 0"):
            factory(table)


def test_samplers_drive_a_dataloader():
    table = weighted([1.0, 0.0, 1.0])
    loader = torch.utils.data.DataLoader(
        table.with_transform(lambda s: s["x"]), batch_size=10,
        sampler=create_sequential_sampler(table),
    )
    assert next(iter(loader)).tolist() == [0, 2]
