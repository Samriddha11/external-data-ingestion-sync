"""Provider-type adapters: raw vendor CSV → FOCUS CSV."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import IO, TextIO

from . import custom, databricks, focus_vendor_export, snowflake

TRANSFORMERS = {
    "custom": custom.transform,
    "snowflake": focus_vendor_export.transform,
    "focus_vendor": focus_vendor_export.transform,
    "databricks": databricks.transform,
    "SNOWFLAKE": focus_vendor_export.transform,
    "CUSTOM": custom.transform,
}


def transform_to_focus(provider_type: str, src: IO[str], dest: TextIO) -> None:
    key = (provider_type or "custom").strip()
    fn = TRANSFORMERS.get(key) or TRANSFORMERS.get(key.lower()) or custom.transform
    fn(src, dest)


def load_mapping_path(provider_type: str, mappings_dir: Path | None) -> Path | None:
    if not mappings_dir:
        return None
    name = f"{provider_type.lower()}.mapping.yaml"
    path = mappings_dir / name
    return path if path.is_file() else None
