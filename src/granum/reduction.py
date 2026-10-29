"""Fit PCA, UMAP or PaCMAP once and project other tables into the same coordinate system."""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import pickle
import tempfile
from collections.abc import Callable
from copy import copy
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa

from granum.core.config import Config
from granum.core.objects.run import Run, get_active_run, init, set_active_run
from granum.core.objects.table import Table
from granum.core.schemas import Float32Schema
from granum.errors import GranumError


class ReductionError(GranumError):
    """Invalid input or an unavailable dimensionality-reduction backend."""


def methods() -> list[dict[str, Any]]:
    return [{"id": method, "installed": package is None or importlib.util.find_spec(package) is not None,
             "install": None if package is None else "pip install 'granum[reduction]'"}
            for method, package in (("pca", None), ("umap", "umap"), ("pacmap", "pacmap"))]


def matrix(values: Any) -> np.ndarray:
    try:
        array = np.asarray(values, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ReductionError("embeddings must be equal-length numeric vectors") from exc
    if array.ndim != 2 or not array.shape[0] or not array.shape[1] or not np.isfinite(array).all():
        raise ReductionError("embeddings must be a nonempty matrix of finite numbers, without missing vectors")
    return array


class Reducer:
    def __init__(self, method: str = "pca", *, dimensions: int = 2, neighbours: int = 15,
                 seed: int = 0, min_distance: float = 0.1) -> None:
        if method not in {"pca", "umap", "pacmap"}:
            raise ReductionError("method must be pca, umap or pacmap")
        if dimensions not in (2, 3) or not 2 <= neighbours <= 200 or not 0 <= seed <= 2**31 - 1:
            raise ReductionError("use 2 or 3 dimensions, 2–200 neighbours and a nonnegative 32-bit seed")
        if not 0 <= min_distance <= 1:
            raise ReductionError("minimum distance must be between 0 and 1")
        self.method, self.dimensions, self.neighbours = method, dimensions, neighbours
        self.seed, self.min_distance = seed, min_distance
        self.reference: np.ndarray | None = None
        self.points: np.ndarray | None = None
        self.backend: Any = None
        self.mean: np.ndarray | None = None
        self.axes: np.ndarray | None = None

    def fit_transform(self, values: Any) -> np.ndarray:
        data = matrix(values)
        self.reference = data.copy()
        if self.method == "pca":
            self.mean = data.mean(axis=0)
            _, _, axes = np.linalg.svd(data - self.mean, full_matrices=False)
            self.axes = np.zeros((self.dimensions, data.shape[1]), dtype=np.float32)
            count = min(len(axes), self.dimensions)
            self.axes[:count] = axes[:count]
            # Resolve SVD sign ambiguity deterministically for saved/repeated views.
            for axis in self.axes:
                if axis[np.abs(axis).argmax()] < 0:
                    axis *= -1
            result = (data - self.mean) @ self.axes.T
        else:
            if len(data) < 10:
                raise ReductionError(f"{self.method} requires at least 10 samples; use PCA for smaller tables")
            try:
                if self.method == "umap":
                    from umap import UMAP

                    self.backend = UMAP(n_components=self.dimensions, n_neighbors=min(self.neighbours, len(data) - 1),
                                        min_dist=self.min_distance, random_state=self.seed, transform_seed=self.seed,
                                        init="random", n_jobs=1)
                else:
                    from pacmap import PaCMAP

                    self.backend = PaCMAP(n_components=self.dimensions, n_neighbors=min(self.neighbours, max(2, (len(data) - 1) // 4)),
                                          random_state=self.seed, save_tree=True)
            except ImportError as exc:
                raise ReductionError(f"{self.method} is not installed; install granum[reduction]") from exc
            result = self.backend.fit_transform(data.copy())
        self.points = np.asarray(result, dtype=np.float32)
        if self.points.shape != (len(data), self.dimensions) or not np.isfinite(self.points).all():
            raise ReductionError("the projection returned invalid coordinates")
        return self.points.copy()

    def transform(self, values: Any) -> np.ndarray:
        if self.reference is None or self.points is None:
            raise ReductionError("fit the reducer before transforming another table")
        data = matrix(values)
        if data.shape[1] != self.reference.shape[1]:
            raise ReductionError("embedding dimensions differ from the fitted reference")
        if np.array_equal(data, self.reference):
            return self.points.copy()
        if self.method == "pca":
            result = (data - self.mean) @ self.axes.T
        elif self.method == "pacmap":
            result = self.backend.transform(data.copy(), basis=self.reference.copy())
        else:
            result = self.backend.transform(data.copy())
        result = np.asarray(result, dtype=np.float32)
        if result.shape != (len(data), self.dimensions) or not np.isfinite(result).all():
            raise ReductionError("the projection returned invalid coordinates")
        return result

    def manifest(self) -> dict[str, Any]:
        return {"method": self.method, "dimensions": self.dimensions, "neighbours": self.neighbours,
                "seed": self.seed, "min_distance": self.min_distance,
                "reference_sha256": hashlib.sha256(self.reference.tobytes()).hexdigest() if self.reference is not None else None}

    def save(self, path: str | Path) -> Path:
        """Save a fitted coordinate system to a new local directory, atomically.

        PCA uses numeric arrays only. UMAP and PaCMAP also contain Python model
        state; load those only from a source you trust (``load(..., trusted=True)``).
        """
        if self.reference is None or self.points is None:
            raise ReductionError("fit the reducer before saving it")
        target = Path(path)
        if target.exists():
            raise ReductionError("the reducer destination already exists; choose a new directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".granum-reducer-", dir=target.parent) as temporary:
            stage = Path(temporary) / "model"
            stage.mkdir()
            arrays = {"reference": self.reference, "points": self.points}
            if self.method == "pca":
                arrays.update(mean=self.mean, axes=self.axes)
            np.savez(stage / "arrays.npz", **arrays)
            if self.method == "pacmap":
                from pacmap.pacmap import save

                # PaCMAP temporarily detaches its neighbour index during serialization.
                save(copy(self.backend), str(stage / "backend"))
            elif self.method == "umap":
                with (stage / "backend.pkl").open("wb") as handle:
                    pickle.dump(self.backend, handle, protocol=pickle.HIGHEST_PROTOCOL)
            packages = ["numpy"] + (["umap-learn", "scikit-learn"] if self.method == "umap" else ["pacmap"] if self.method == "pacmap" else [])
            metadata = {"format": "granum-reducer", "version": 1, **self.manifest(),
                        "versions": {name: importlib.metadata.version(name) for name in packages},
                        "files": {file.name: _digest(file) for file in stage.iterdir()}}
            (stage / "manifest.json").write_text(json.dumps(metadata, indent=2))
            stage.rename(target)
        return target

    @classmethod
    def load(cls, path: str | Path, *, trusted: bool = False) -> Reducer:
        """Restore a saved fit without refitting. Nonlinear models require explicit trust.

        File checksums detect damage, not an untrusted author's executable model.
        No dashboard endpoint accepts or loads uploaded pickle models.
        """
        folder = Path(path)
        try:
            metadata = json.loads((folder / "manifest.json").read_text())
            if metadata.get("format") != "granum-reducer" or metadata.get("version") != 1:
                raise ReductionError("unsupported reducer format")
            result = cls(**{key: metadata[key] for key in ("method", "dimensions", "neighbours", "seed", "min_distance")})
            if result.method != "pca" and not trusted:
                raise ReductionError("this reducer contains Python model state; use trusted=True only for a model from a trusted source")
            files = metadata["files"]
            allowed = {"arrays.npz", "backend.pkl", "backend.ann", "backend.faiss", "backend.voyager"}
            if not isinstance(files, dict) or "arrays.npz" not in files or set(files) - allowed:
                raise ReductionError("invalid reducer file list")
            for name, digest in files.items():
                if _digest(folder / name) != digest:
                    raise ReductionError(f"reducer file {name} is damaged or changed")
            with np.load(folder / "arrays.npz", allow_pickle=False) as arrays:
                result.reference, result.points = matrix(arrays["reference"]), matrix(arrays["points"])
                if result.points.shape != (len(result.reference), result.dimensions):
                    raise ReductionError("saved projection dimensions do not match")
                if result.method == "pca":
                    result.mean = np.asarray(arrays["mean"], dtype=np.float32)
                    result.axes = matrix(arrays["axes"])
                    if result.mean.shape != (result.reference.shape[1],) or result.axes.shape != (result.dimensions, result.reference.shape[1]) or not np.isfinite(result.mean).all():
                        raise ReductionError("saved PCA dimensions do not match")
            if result.manifest()["reference_sha256"] != metadata["reference_sha256"]:
                raise ReductionError("saved reference does not match its fingerprint")
            if result.method != "pca":
                for package, version in metadata["versions"].items():
                    if importlib.metadata.version(package) != version:
                        raise ReductionError(f"restore this reducer with {package}=={version}, or fit a new projection")
                if "backend.pkl" not in files:
                    raise ReductionError("saved reducer is missing its model")
                if result.method == "pacmap":
                    from pacmap.pacmap import load

                    result.backend = load(str(folder / "backend"))
                else:
                    with (folder / "backend.pkl").open("rb") as handle:
                        result.backend = pickle.load(handle)
            return result
        except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
            raise ReductionError(f"could not load the saved reducer: {exc}") from exc


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def values_from(table: Table, column: str) -> np.ndarray:
    if column not in table.schema or table.schema[column].kind != "embedding":
        raise ReductionError(f"{column!r} is not an embedding column in {table.name}")
    return matrix(table.to_arrow().column(column).to_pylist())


def reduce_table(table: Table, column: str, *, reducer: Reducer | None = None, prefix: str = "projection") -> Table:
    reducer = reducer or Reducer()
    names = [f"{prefix}_{axis}" for axis in "xyz"[:reducer.dimensions]]
    if not prefix.strip() or any(name in table.schema for name in names):
        raise ReductionError("choose a nonempty projection prefix whose columns do not already exist")
    values = values_from(table, column)
    points = reducer.fit_transform(values) if reducer.reference is None else reducer.transform(values)
    arrow, schema = table.to_arrow(), table.schema
    for index, name in enumerate(names):
        arrow = arrow.append_column(name, pa.array(points[:, index], type=pa.float32()))
        schema = schema.with_column(name, Float32Schema(writable=False))
    return table._derive(arrow=arrow, schema=schema, op="reduce_embeddings",
                         args={**reducer.manifest(), "column": column, "prefix": prefix})


def reduce_run(run: Run, column: str, *, reducer: Reducer | None = None, prefix: str = "projection",
               reference: int = -1, config: Config | None = None,
               cancelled: Callable[[], bool] = lambda: False,
               progress: Callable[[str, int, int], None] = lambda *_: None) -> Run:
    """Produce a separate analysis Run, preserving sample joins and the source Run unchanged.

    An already fitted reducer is reused without refitting. Otherwise ``reference`` selects
    the metrics table used to fit one coordinate system for every epoch.
    """
    tables = [table for table in run.metrics_tables() if column in table.schema]
    if not tables or not -len(tables) <= reference < len(tables):
        raise ReductionError("choose a reference metrics table containing the embedding column")
    reducer = reducer or Reducer()
    names = [f"{prefix}_{axis}" for axis in "xyz"[:reducer.dimensions]]
    if not prefix.strip() or any(name in table.schema for table in tables for name in names):
        raise ReductionError("projection columns already exist; choose a different prefix")
    for table in tables:
        values_from(table, column)
    fitted = reducer.reference is not None
    progress("Reusing saved projection" if fitted else "Fitting reference projection", 0, len(tables))
    if not fitted:
        reducer.fit_transform(values_from(tables[reference], column))
    elif any(values_from(table, column).shape[1] != reducer.reference.shape[1] for table in tables):
        raise ReductionError("embedding dimensions differ from the fitted reference")
    if cancelled():
        raise ReductionError("projection cancelled")
    active = get_active_run()
    result = init(run.project_name, f"{run.name}-{reducer.method}", config=config,
                  description=f"Embedding analysis of {run.name}",
                  parameters={"analysis": "embeddings", "source_run": str(run.url),
                              "reference_table": None if fitted else str(tables[reference].url),
                              "reused_reducer": fitted,
                              "column": column, "prefix": prefix, **reducer.manifest()})
    set_active_run(active)
    try:
        for i, table in enumerate(tables):
            if cancelled():
                raise ReductionError("projection cancelled")
            points = reducer.transform(values_from(table, column))
            data = table.to_pydict()
            schemas = dict(table.schema.columns)
            for axis, name in enumerate(names):
                data[name] = points[:, axis].tolist()
                schemas[name] = Float32Schema(writable=False)
            result.add_metrics(data, schema=schemas, foreign_table_url=table.foreign_table_url, constants=table.constants)
            progress("Projecting epochs", i + 1, len(tables))
        result.set_status("finished")
    except Exception:
        result.set_status("cancelled" if cancelled() else "failed")
        raise
    return result
