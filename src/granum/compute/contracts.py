"""Validated, versioned declarations. No Python or shell expression comes from the UI."""
from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from granum.errors import GranumError


class PluginError(GranumError):
    pass


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Parameter(Contract):
    label: str = Field(min_length=1, max_length=120)
    kind: Literal["integer", "number", "boolean", "string", "choice"]
    default: Any
    minimum: float | None = Field(None, allow_inf_nan=False)
    maximum: float | None = Field(None, allow_inf_nan=False)
    choices: list[str] = Field(default_factory=list, max_length=100)

    def validate_value(self, value: Any) -> Any:
        valid = (type(value) is int if self.kind == "integer" else
                 type(value) in (int, float) if self.kind == "number" else
                 type(value) is bool if self.kind == "boolean" else
                 isinstance(value, str) and len(value) <= 2000)
        if not valid or self.kind == "choice" and value not in self.choices:
            raise PluginError(f"Invalid value for {self.label}")
        if self.kind in {"integer", "number"} and (not math.isfinite(value) or
                self.minimum is not None and value < self.minimum or self.maximum is not None and value > self.maximum):
            raise PluginError(f"{self.label} is outside its allowed range")
        return value

    @model_validator(mode="after")
    def valid_default(self):
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum exceeds maximum")
        self.validate_value(self.default)
        return self


class Wheel(Contract):
    url: str = Field(min_length=1, max_length=2048)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Manifest(Contract):
    protocol: Literal[1] = 1
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:[a-z0-9.+-]*)$", max_length=64)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    entrypoint: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$")
    inputs: dict[str, list[str]] = Field(min_length=1, max_length=20)
    parameters: dict[str, Parameter] = Field(default_factory=dict, max_length=30)
    outputs: dict[str, Literal["integer", "number", "boolean", "string"]] = Field(min_length=1, max_length=50)
    wheels: list[Wheel] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def field_names(self):
        import re

        for key in [*self.inputs, *self.parameters, *self.outputs]:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key):
                raise ValueError("use simple identifiers for input, parameter and output names")
        if any(not kinds or len(kinds) > 20 or any(not isinstance(k, str) or len(k) > 80 for k in kinds) for kinds in self.inputs.values()):
            raise ValueError("each input needs supported schema kinds")
        return self

    def values(self, supplied: dict[str, Any]) -> dict[str, Any]:
        if set(supplied) - self.parameters.keys():
            raise PluginError("Unknown plugin parameters")
        return {key: spec.validate_value(supplied.get(key, spec.default)) for key, spec in self.parameters.items()}


class Catalogue(Contract):
    version: Literal[1] = 1
    plugins: list[Manifest] = Field(max_length=200)


ANNOTATIONS = Manifest(
    id="annotation-metrics", version="1.0.0", title="Annotation metrics",
    description="Find crowded images, small objects, border touches and overlapping boxes. Crowd regions are excluded; overlap is a proxy, not measured occlusion.",
    entrypoint="granum_compute_sdk.annotations:run",
    inputs={"annotations": ["bounding_boxes_2d"]},
    parameters={
        "small_area": Parameter(label="Small object area (pixels²)", kind="number", default=1024, minimum=0, maximum=1e9),
        "border_margin": Parameter(label="Border margin (pixels)", kind="number", default=1, minimum=0, maximum=10000),
    },
    outputs={"object_count": "integer", "small_object_count": "integer", "border_touch_count": "integer", "max_box_iou": "number"},
)
