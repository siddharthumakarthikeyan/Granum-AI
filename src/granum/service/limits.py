"""Explicit materialization budgets, not claims of universal dataset capacity."""
from dataclasses import asdict, dataclass
from typing import Any

import pyarrow.parquet as pq
from fastapi import HTTPException

from granum.core.layout import ROW_CACHE_FILENAME


@dataclass(frozen=True)
class WorkflowLimits:
    images: int = 25_000
    rows: int = 250_000
    uncompressed_bytes: int = 128 * 1024 * 1024

    def to_dict(self) -> dict[str, int]:
        return asdict(self)

    def check(self, tables: list[Any], workflow: str, *, images: bool = False) -> None:
        count = sum(len(t) for t in tables)
        maximum = self.images if images else self.rows
        if count > maximum:
            self.refuse(workflow, f"{count:,} rows exceeds the {maximum:,}-row materialization budget")
        size = 0
        for table in tables:
            url = table.url / ROW_CACHE_FILENAME
            metadata = pq.read_metadata(url.path, filesystem=url.fs)
            size += sum(metadata.row_group(g).total_byte_size for g in range(metadata.num_row_groups))
            if size > self.uncompressed_bytes:
                self.refuse(workflow, f"uncompressed Parquet exceeds the {self.uncompressed_bytes // 1024**2} MiB budget")

    @staticmethod
    def refuse(workflow: str, reason: str) -> None:
        raise HTTPException(413, f"{workflow}: {reason}. No partial result was returned. Narrow the dataset or collect fewer epochs/predictions; use the SDK for larger offline analysis.")