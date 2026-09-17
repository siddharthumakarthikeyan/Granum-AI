"""Samplers that honour a Table's sample weights.

Weights are how a dashboard edit reaches training without touching the training code:
set a mislabelled image's weight to 0 and every sampler here stops yielding it; raise an
underrepresented sample's weight and it is seen more often.

Each factory returns a ``torch.utils.data.Sampler`` so it drops straight into a
``DataLoader``::

    table = Table.from_url(url).latest()
    loader = DataLoader(table.with_transform(load), sampler=create_weighted_sampler(table))
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from typing import Any

import numpy as np

from granum.core.objects.table import WEIGHT_COLUMN, Table
from granum.errors import TableError


def _torch_sampler_base() -> type:
    try:
        from torch.utils.data import Sampler
    except ImportError as exc:  # pragma: no cover - exercised only without torch
        raise ImportError("samplers need PyTorch: pip install torch") from exc
    return Sampler


def sample_weights(table: Table) -> np.ndarray:
    """The weight column as floats, or all ones for a Table without one."""
    if WEIGHT_COLUMN not in table.schema:
        return np.ones(len(table), dtype=np.float64)
    weights = np.asarray(table.to_arrow().column(WEIGHT_COLUMN).to_pylist(), dtype=np.float64)
    if np.any(~np.isfinite(weights)) or np.any(weights < 0):
        raise TableError(f"{table.name!r} has negative or non-finite weights")
    return weights


def _included(table: Table, exclude_zero_weights: bool) -> np.ndarray:
    weights = sample_weights(table)
    indices = np.flatnonzero(weights > 0) if exclude_zero_weights else np.arange(len(weights))
    if len(indices) == 0:
        raise TableError(f"every sample in {table.name!r} has weight 0; nothing to sample")
    return indices


def create_weighted_sampler(
    table: Table,
    *,
    num_samples: int | None = None,
    replacement: bool = True,
    seed: int | None = None,
) -> Any:
    """Draw samples with probability proportional to their weight.

    Defaults to one epoch's worth of draws over the samples with non-zero weight, so an
    epoch stays the same length when weights are only redistributed. Weight-0 samples are
    never drawn.
    """
    import torch
    from torch.utils.data import WeightedRandomSampler

    weights = sample_weights(table)
    positive = int(np.count_nonzero(weights))
    if positive == 0:
        raise TableError(f"every sample in {table.name!r} has weight 0; nothing to sample")
    if not replacement and num_samples is not None and num_samples > positive:
        raise TableError(
            f"cannot draw {num_samples} samples without replacement from {positive} "
            f"with non-zero weight"
        )
    generator = torch.Generator().manual_seed(seed) if seed is not None else None
    return WeightedRandomSampler(
        torch.as_tensor(weights, dtype=torch.double),
        num_samples=num_samples if num_samples is not None else positive,
        replacement=replacement,
        generator=generator,
    )


def create_random_sampler(
    table: Table, *, exclude_zero_weights: bool = True, seed: int | None = None
) -> Any:
    """Every included sample once per epoch, in a fresh random order."""
    Sampler = _torch_sampler_base()
    indices = _included(table, exclude_zero_weights)

    class RandomSubsetSampler(Sampler):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            self.indices = indices
            self.epoch = 0

        def __iter__(self) -> Iterator[int]:
            rng = np.random.default_rng(None if seed is None else seed + self.epoch)
            self.epoch += 1
            return iter(rng.permutation(self.indices).tolist())

        def __len__(self) -> int:
            return len(self.indices)

    return RandomSubsetSampler()


def create_sequential_sampler(table: Table, *, exclude_zero_weights: bool = True) -> Any:
    """Every included sample once, in table order -- for evaluation passes."""
    Sampler = _torch_sampler_base()
    indices = _included(table, exclude_zero_weights).tolist()

    class SequentialSubsetSampler(Sampler):  # type: ignore[misc, valid-type]
        def __iter__(self) -> Iterator[int]:
            return iter(indices)

        def __len__(self) -> int:
            return len(indices)

    return SequentialSubsetSampler()


def create_repeat_by_weight_sampler(table: Table, *, seed: int | None = None) -> Any:
    """Each sample repeated ``weight`` times per epoch, shuffled.

    Unlike weighted random sampling, integer weights are exact: weight 2 means twice per
    epoch, every epoch. A fractional part is honoured on average -- weight 1.5 yields the
    sample once, plus a second time with probability 0.5 each epoch. The epoch length
    therefore varies slightly when weights are fractional.
    """
    Sampler = _torch_sampler_base()
    weights = sample_weights(table)
    if not np.any(weights > 0):
        raise TableError(f"every sample in {table.name!r} has weight 0; nothing to sample")
    whole = np.floor(weights).astype(np.int64)
    fraction = weights - whole

    class RepeatByWeightSampler(Sampler):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            self.epoch = 0

        def __iter__(self) -> Iterator[int]:
            rng = np.random.default_rng(None if seed is None else seed + self.epoch)
            self.epoch += 1
            counts = whole + (rng.random(len(weights)) < fraction)
            return iter(rng.permutation(np.repeat(np.arange(len(weights)), counts)).tolist())

        def __len__(self) -> int:
            return int(whole.sum() + math.ceil(fraction.sum()))

    return RepeatByWeightSampler()
