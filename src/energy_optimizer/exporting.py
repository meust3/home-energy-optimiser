"""CSV export helpers for local observation history."""

import csv
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def export_rows_to_csv(
    rows: Sequence[dict[str, Any]],
    output_path: Path,
    *,
    fieldnames: Sequence[str] | None = None,
) -> int:
    """Write query rows exactly as represented; return the exported row count."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = (
        list(fieldnames) if fieldnames is not None else (list(rows[0]) if rows else [])
    )
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        if columns:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    return len(rows)
