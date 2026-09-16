"""Map common Snowflake billing export headers toward FOCUS (extend via mapping file later)."""

from __future__ import annotations

import csv
from typing import IO, TextIO

# Vendor export column → FOCUS column
COLUMN_MAP = {
    "USAGE_DATE": "ChargePeriodStart",
    "USAGE_TYPE": "ServiceName",
    "CREDITS_USED": "BilledCost",
    "ACCOUNT_NAME": "SubAccountName",
    "REGION": "RegionName",
    "WAREHOUSE_NAME": "ResourceName",
}


def transform(src: IO[str], dest: TextIO) -> None:
    reader = csv.DictReader(src)
    if not reader.fieldnames:
        raise ValueError("Snowflake adapter: empty CSV")

    out_fields = list(reader.fieldnames)
    for src_col, focus_col in COLUMN_MAP.items():
        if src_col in (reader.fieldnames or []) and focus_col not in out_fields:
            out_fields.append(focus_col)

    for req in (
        "BilledCost",
        "BillingCurrency",
        "ChargeCategory",
        "ChargePeriodStart",
        "ChargePeriodEnd",
        "ProviderName",
    ):
        if req not in out_fields:
            out_fields.append(req)

    writer = csv.DictWriter(dest, fieldnames=out_fields, extrasaction="ignore")
    writer.writeheader()

    for row in reader:
        out = dict(row)
        for src_col, focus_col in COLUMN_MAP.items():
            if src_col in row and row[src_col]:
                out[focus_col] = row[src_col]
        out.setdefault("ProviderName", "Snowflake")
        out.setdefault("BillingCurrency", out.get("BillingCurrency") or "USD")
        out.setdefault("ChargeCategory", out.get("ChargeCategory") or "Usage")
        if out.get("ChargePeriodStart") and not out.get("ChargePeriodEnd"):
            out["ChargePeriodEnd"] = out["ChargePeriodStart"]
        writer.writerow(out)
