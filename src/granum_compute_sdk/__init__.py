"""Dependency-free contract for Granum compute plugins (protocol version 1).

A plugin exports ``run(context: Context) -> Result``. Results address the original
sample IDs, even when work is reordered or batched. Only the host publishes data.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

__version__ = "0.1.0"


@dataclass(frozen=True)
class Sample:
    id: int
    values: dict[str, Any]


@dataclass
class Context:
    samples: list[Sample]
    parameters: dict[str, Any]
    source: dict[str, Any]

    def progress(self, done: int, total: int, phase: str = "Computing") -> None:
        print("GRANUM_PROGRESS " + json.dumps({"done": done, "total": total, "phase": phase}), flush=True)


@dataclass
class Result:
    sample_ids: list[int]
    columns: dict[str, list[Any]]
    summary: dict[str, Any] = field(default_factory=dict)


__all__ = ["Context", "Result", "Sample"]
