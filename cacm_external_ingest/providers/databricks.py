"""Map common Databricks usage export headers toward FOCUS."""

from __future__ import annotations

import csv
from typing import IO, TextIO

COLUMN_MAP = {
    "timestamp": "ChargePeriodStart",
    "sku": "ServiceName",
    "dbus": "UsageQuantity",
    "cost": "BilledCost",
    "workspaceId": "SubAccountId",
    "clusterId": "ResourceId",
}


def transform(src: IO[str], dest: TextIO) -> None:
    reader = csv.DictReader(src)
    if not reader.fieldnames:
        raise ValueError("Databricks adapter: empty CSV")

    out_fields = list(reader.fieldnames)
    for _src, focus_col in COLUMN_MAP.items():
        if focus_col not in out_fields:
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
        out.setdefault("ProviderName", "Databricks")
        out.setdefault("BillingCurrency", "USD")
        out.setdefault("ChargeCategory", "Usage")
        if out.get("ChargePeriodStart") and not out.get("ChargePeriodEnd"):
            out["ChargePeriodEnd"] = out["ChargePeriodStart"]
        writer.writerow(out)
