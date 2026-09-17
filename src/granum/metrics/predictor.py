"""The bridge between a model and a metrics collector.

A bare model gives you its output. ``Predictor`` additionally captures hidden-layer
activations through forward hooks, which is what an embeddings collector needs -- that
lands in Stage 8, but the hook machinery is here so the contract does not change later.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from granum.errors import GranumError


class PredictorError(GranumError):
    """The model could not be called, or its output could not be interpreted."""


@dataclass
class Prediction:
    """One batch of model output."""

    outputs: Any
    activations: dict[int, np.ndarray] = field(default_factory=dict)

    def as_numpy(self) -> np.ndarray:
        """Model output as a numpy array, detached from any autograd graph."""
        return _to_numpy(self.outputs)

    def __len__(self) -> int:
        array = self.as_numpy()
        return int(array.shape[0]) if array.ndim else 0


def _to_numpy(value: Any) -> np.ndarray:
    if isinstance(value, np.ndarray):
        return value
    if hasattr(value, "detach"):  # torch tensor, without importing torch
        return value.detach().cpu().numpy()
    return np.asarray(value)


class Predictor:
    """Call a model over a batch and optionally capture intermediate activations.

    ``preprocess`` turns a batch (a dict of column name to list of values) into whatever
    the model expects. Without it the batch dict is handed to the model unchanged, which
    suits plain Python callables.

    ``layers`` are *indices* into ``model.named_modules()``, not module references --
    resolve them up front by walking ``named_modules()`` for the layer you want.
    """

    def __init__(
        self,
        model: Callable[[Any], Any],
        *,
        preprocess: Callable[[dict[str, list[Any]]], Any] | None = None,
        layers: Sequence[int] | None = None,
        device: str | None = None,
        eval_mode: bool = True,
    ) -> None:
        self.model = model
        self.preprocess = preprocess
        self.layers = list(layers or [])
        self.device = device
        self.eval_mode = eval_mode
        self._handles: list[Any] = []
        self._captured: dict[int, np.ndarray] = {}

        if self.layers:
            self._install_hooks()
        if device is not None and hasattr(model, "to"):
            model.to(device)

    # -- hooks --------------------------------------------------------------

    def _install_hooks(self) -> None:
        if not hasattr(self.model, "named_modules"):
            raise PredictorError(
                "layers= needs a model exposing named_modules(); a plain callable has "
                "no layers to hook"
            )
        modules = list(self.model.named_modules())
        for index in self.layers:
            if not 0 <= index < len(modules):
                raise PredictorError(
                    f"layer index {index} is out of range -- the model has "
                    f"{len(modules)} modules"
                )
            _, module = modules[index]
            self._handles.append(
                module.register_forward_hook(self._make_hook(index))
            )

    def _make_hook(self, index: int) -> Callable[..., None]:
        def hook(_module: Any, _inputs: Any, output: Any) -> None:
            self._captured[index] = _to_numpy(output)

        return hook

    def remove_hooks(self) -> None:
        for handle in self._handles:
            handle.remove()
        self._handles.clear()

    # -- calling ------------------------------------------------------------

    def __call__(self, batch: dict[str, list[Any]]) -> Prediction:
        self._captured = {}
        model_input = self.preprocess(batch) if self.preprocess is not None else batch

        if self.eval_mode and hasattr(self.model, "eval"):
            self.model.eval()

        outputs = self._forward(model_input)
        return Prediction(outputs=outputs, activations=dict(self._captured))

    def _forward(self, model_input: Any) -> Any:
        if hasattr(self.model, "parameters"):  # a torch module
            import torch

            with torch.no_grad():
                if self.device is not None and hasattr(model_input, "to"):
                    model_input = model_input.to(self.device)
                return self.model(model_input)
        return self.model(model_input)

    def __enter__(self) -> Predictor:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.remove_hooks()
