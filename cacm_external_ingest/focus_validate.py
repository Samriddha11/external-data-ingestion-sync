"""Deterministic FOCUS CSV validation (hard gate before upload)."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import IO, Iterable, List, Optional

# Subset of FOCUS 1.x columns required for CACM external ingest (see Harness docs).
REQUIRED_COLUMNS = (
    "BilledCost",
    "BillingCurrency",
    "ChargeCategory",
    "ChargePeriodEnd",
    "ChargePeriodStart",
    "ProviderName",
)

CHARGE_CATEGORIES = frozenset(
    {"Usage", "Purchase", "Tax", "Credit", "Adjustment"}
)

ISO_DT = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
)


@dataclass
class ValidationIssue:
    severity: str  # error | warn
    field: str
    message: str
    row: Optional[int] = None


@dataclass
class ValidationReport:
    ok: bool
    row_count: int
    issues: List[ValidationIssue] = field(default_factory=list)
    billed_cost_total: float = 0.0
    period_start_min: Optional[str] = None
    period_end_max: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "row_count": self.row_count,
            "billed_cost_total": self.billed_cost_total,
            "period_start_min": self.period_start_min,
            "period_end_max": self.period_end_max,
            "issues": [
                {
                    "severity": i.severity,
                    "field": i.field,
                    "message": i.message,
                    "row": i.row,
                }
                for i in self.issues
            ],
        }


def validate_focus_csv(
    fp: IO[str],
    max_file_bytes: int = 20 * 1024 * 1024,
    max_rows_sample: int = 50_000,
) -> ValidationReport:
    issues: List[ValidationIssue] = []
    raw = fp.read()
    if isinstance(raw, str):
        size = len(raw.encode("utf-8"))
    else:
        size = len(raw)
        raw = raw.decode("utf-8", errors="replace")

    if size > max_file_bytes:
        issues.append(
            ValidationIssue(
                "error",
                "file",
                f"File size {size} bytes exceeds {max_file_bytes} (20 MB). Split before upload.",
            )
        )
        return ValidationReport(ok=False, row_count=0, issues=issues)

    reader = csv.DictReader(raw.splitlines())
    if not reader.fieldnames:
        issues.append(ValidationIssue("error", "header", "Missing CSV header row."))
        return ValidationReport(ok=False, row_count=0, issues=issues)

    headers = {h.strip() for h in reader.fieldnames if h}
    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        issues.append(
            ValidationIssue(
                "error",
                "header",
                f"Missing required FOCUS columns: {', '.join(missing)}",
            )
        )

    row_count = 0
    total = 0.0
    pmin: Optional[datetime] = None
    pmax: Optional[datetime] = None

    for row_num, row in enumerate(reader, start=2):
        row_count += 1
        if row_count > max_rows_sample:
            issues.append(
                ValidationIssue(
                    "warn",
                    "file",
                    f"Stopped scanning after {max_rows_sample} rows (sample limit).",
                )
            )
            break

        cat = (row.get("ChargeCategory") or "").strip()
        if cat and cat not in CHARGE_CATEGORIES:
            issues.append(
                ValidationIssue(
                    "error",
                    "ChargeCategory",
                    f"Invalid value '{cat}'",
                    row_num,
                )
            )

        cost_raw = (row.get("BilledCost") or "").strip()
        if cost_raw:
            try:
                total += float(cost_raw)
            except ValueError:
                issues.append(
                    ValidationIssue(
                        "error",
                        "BilledCost",
                        f"Not numeric: '{cost_raw}'",
                        row_num,
                    )
                )

        for col in ("ChargePeriodStart", "ChargePeriodEnd"):
            val = (row.get(col) or "").strip()
            if val and not ISO_DT.match(val):
                issues.append(
                    ValidationIssue(
                        "error",
                        col,
                        f"Expected ISO-8601 datetime, got '{val}'",
                        row_num,
                    )
                )
            if val:
                try:
                    dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                    if col == "ChargePeriodStart":
                        pmin = dt if pmin is None or dt < pmin else pmin
                    else:
                        pmax = dt if pmax is None or dt > pmax else pmax
                except ValueError:
                    pass

    if row_count == 0:
        issues.append(ValidationIssue("error", "file", "CSV has no data rows."))

    errors = [i for i in issues if i.severity == "error"]
    return ValidationReport(
        ok=len(errors) == 0,
        row_count=row_count,
        issues=issues,
        billed_cost_total=round(total, 6),
        period_start_min=pmin.isoformat() if pmin else None,
        period_end_max=pmax.isoformat() if pmax else None,
    )
