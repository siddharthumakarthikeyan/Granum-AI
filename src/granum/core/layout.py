"""The on-disk project layout.

::

    <project_root>/
      projects/
        index.granum.json
        <project>/
          index.granum.json
          default_aliases.granum.yaml
          datasets/
            <dataset>/
              tables/
                <table>/
                  object.granum.json
                  row_cache.parquet
              bulk_data/
              cache/thumbnails/
          runs/
            <run>/
              object.granum.json
              metrics_0000/object.granum.json
              cache/thumbnails/

A Granum object is always a *directory* containing ``object.granum.json``, the same way
a web server treats a directory containing ``index.html``. The object's URL is the
directory, never the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from granum.core.url import Url

OBJECT_FILENAME = "object.granum.json"
INDEX_FILENAME = "index.granum.json"
ROW_CACHE_FILENAME = "row_cache.parquet"

_UNSAFE = re.compile(r"[^A-Za-z0-9._\- ]+")


def sanitize(name: str) -> str:
    """Make ``name`` safe to use as a directory segment."""
    cleaned = _UNSAFE.sub("-", str(name).strip()).strip(" .-")
    if not cleaned:
        raise ValueError(f"{name!r} does not contain any usable characters")
    return cleaned


@dataclass(frozen=True)
class ProjectLayout:
    """Resolves the canonical locations beneath a project root."""

    root: Url

    def __init__(self, root: Url | str) -> None:
        object.__setattr__(self, "root", Url(root))

    @property
    def projects_dir(self) -> Url:
        return self.root / "projects"

    def project(self, project_name: str) -> Url:
        return self.projects_dir / sanitize(project_name)

    def datasets_dir(self, project_name: str) -> Url:
        return self.project(project_name) / "datasets"

    def dataset(self, project_name: str, dataset_name: str) -> Url:
        return self.datasets_dir(project_name) / sanitize(dataset_name)

    def tables_dir(self, project_name: str, dataset_name: str) -> Url:
        return self.dataset(project_name, dataset_name) / "tables"

    def table(self, project_name: str, dataset_name: str, table_name: str) -> Url:
        return self.tables_dir(project_name, dataset_name) / sanitize(table_name)

    def bulk_data(self, project_name: str, dataset_name: str) -> Url:
        return self.dataset(project_name, dataset_name) / "bulk_data"

    def dataset_cache(self, project_name: str, dataset_name: str) -> Url:
        return self.dataset(project_name, dataset_name) / "cache"

    def thumbnails(self, project_name: str, dataset_name: str) -> Url:
        return self.dataset_cache(project_name, dataset_name) / "thumbnails"

    def runs_dir(self, project_name: str) -> Url:
        return self.project(project_name) / "runs"

    def run(self, project_name: str, run_name: str) -> Url:
        return self.runs_dir(project_name) / sanitize(run_name)

    def project_aliases(self, project_name: str) -> Url:
        return self.project(project_name) / "default_aliases.granum.yaml"

    def index_marker(self, url: Url) -> Url:
        """The change-signal marker for a location.

        Touched by every writer so the Stage 3 indexer can skip unchanged trees with a
        single metadata lookup instead of a full recursive listing.
        """
        return Url(url) / INDEX_FILENAME
