"""Snowflake / vendor CSV aligned with FOCUS-like columns (EffectiveCost, date-only periods)."""

from __future__ import annotations

import csv
import re
from typing import IO, TextIO

DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

FOCUS_PERIOD_COLUMNS = (
    "ChargePeriodStart",
    "ChargePeriodEnd",
    "BillingPeriodStart",
    "BillingPeriodEnd",
)


def _to_iso_datetime(val: str, end_of_day: bool = False) -> str:
    val = (val or "").strip()
    if not val:
        return val
    if DATE_ONLY.match(val):
        return f"{val}T{'23:59:59' if end_of_day else '00:00:00'}Z"
    if "T" not in val and len(val) >= 10:
        return f"{val[:10]}T{'23:59:59' if end_of_day else '00:00:00'}Z"
    if val.endswith("Z") or "+" in val:
        return val
    return f"{val}Z" if "T" in val else val


def transform(src: IO[str], dest: TextIO) -> None:
    reader = csv.DictReader(src)
    if not reader.fieldnames:
        raise ValueError("focus_vendor_export: empty CSV")

    fieldnames = list(reader.fieldnames)
    extra = []
    if "BilledCost" not in fieldnames:
        extra.append("BilledCost")
    if "BillingCurrency" not in fieldnames:
        extra.append("BillingCurrency")
    out_fields = fieldnames + [c for c in extra if c not in fieldnames]

    writer = csv.DictWriter(dest, fieldnames=out_fields, extrasaction="ignore")
    writer.writeheader()

    for row in reader:
        out = dict(row)
        if not out.get("BilledCost") and out.get("EffectiveCost"):
            out["BilledCost"] = out["EffectiveCost"]
        out.setdefault("BillingCurrency", "USD")
        if not out.get("ProviderName"):
            out["ProviderName"] = "Snowflake"
        if not out.get("ChargeCategory"):
            out["ChargeCategory"] = "Usage"

        for col in FOCUS_PERIOD_COLUMNS:
            if col not in out or not out[col]:
                continue
            end = col.endswith("End")
            out[col] = _to_iso_datetime(out[col], end_of_day=end)

        writer.writerow(out)
