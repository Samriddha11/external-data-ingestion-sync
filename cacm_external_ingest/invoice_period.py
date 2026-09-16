"""Derive Harness invoicePeriod from FOCUS BillingPeriod columns."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import IO, Union

DATE_ONLY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _to_yyyymmdd(val: str) -> str:
    val = (val or "").strip()[:10]
    m = DATE_ONLY.match(val)
    if not m:
        raise ValueError(f"Cannot parse billing date: {val!r}")
    return f"{m.group(1)}{m.group(2)}{m.group(3)}"


def invoice_period_from_csv(path_or_fp: Union[str, Path, IO[str]]) -> str:
    """Use BillingPeriodStart-BillingPeriodEnd from first data row (matches Snowflake exports)."""
    if isinstance(path_or_fp, (str, Path)):
        with Path(path_or_fp).open(encoding="utf-8", errors="replace") as f:
            return invoice_period_from_csv(f)
    reader = csv.DictReader(path_or_fp)
    if not reader.fieldnames:
        raise ValueError("CSV has no header")
    row = next(reader, None)
    if not row:
        raise ValueError("CSV has no data rows")
    start = row.get("BillingPeriodStart") or row.get("ChargePeriodStart")
    end = row.get("BillingPeriodEnd") or row.get("ChargePeriodEnd")
    if not start or not end:
        raise ValueError("Missing BillingPeriodStart/End or ChargePeriodStart/End in first row")
    return f"{_to_yyyymmdd(start)}-{_to_yyyymmdd(end)}"
