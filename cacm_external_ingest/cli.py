#!/usr/bin/env python3
"""CLI: transform → validate → (optional) ingest to CACM External Data."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from .focus_validate import validate_focus_csv
from .harness_api import HarnessExternalDataClient, DEFAULT_BASE
from .invoice_period import invoice_period_from_csv
from .object_storage import (
    ObjectStorageError,
    download_object,
    list_csv_uris,
    object_basename,
    sync_prefix,
)
from .providers.registry import transform_to_focus


def _remote_uri(args: argparse.Namespace) -> str | None:
    return args.object_uri or args.s3_uri


def _remote_prefix(args: argparse.Namespace) -> str | None:
    return args.object_prefix or args.s3_prefix


def _run_one_file(
    args: argparse.Namespace,
    raw_path: Path,
    focus_path: Path,
    report_path: Path,
    client: HarnessExternalDataClient | None,
    upload_object_name: str | None = None,
) -> int:
    with raw_path.open(encoding="utf-8", errors="replace") as src, focus_path.open(
        "w", encoding="utf-8", newline=""
    ) as dest:
        transform_to_focus(args.provider_type, src, dest)

    if getattr(args, "inspect_only", False):
        lines = focus_path.read_text(encoding="utf-8", errors="replace").splitlines()
        print("=== After transform ===", file=sys.stderr)
        for line in lines[:3]:
            print(line)
        return 0

    with focus_path.open(encoding="utf-8") as f:
        report = validate_focus_csv(f)

    report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print(json.dumps(report.to_dict(), indent=2))

    if not report.ok:
        print("Hard validation failed.", file=sys.stderr)
        errors = [i for i in report.issues if i.severity == "error"]
        for i in errors[:25]:
            loc = f" (row {i.row})" if i.row else ""
            print(f"  - [{i.field}]{loc}: {i.message}", file=sys.stderr)
        if len(errors) > 25:
            print(f"  ... and {len(errors) - 25} more errors", file=sys.stderr)
        print(f"Full report: {report_path}", file=sys.stderr)
        return 1

    if args.validate_only:
        print("Validate-only mode; skipping ingest.")
        return 0

    if client is None:
        raise RuntimeError("client required for ingest")
    object_name = upload_object_name or args.object_name or focus_path.name
    result = client.ingest_focus_csv(
        args.provider_id,
        args.invoice_period,
        focus_path,
        object_name=object_name,
    )
    print("Ingest submitted:", json.dumps(result, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="CACM external FOCUS cost ingest")
    p.add_argument("--account-id")
    p.add_argument("--api-key")
    p.add_argument("--base-url", default=DEFAULT_BASE)
    p.add_argument("--provider-id")
    p.add_argument(
        "--provider-type",
        default="custom",
        help="custom | snowflake | databricks (adapter for transform)",
    )
    p.add_argument(
        "--invoice-period",
        help="YYYYMMDD-YYYYMMDD (or use --derive-invoice-period-from-csv)",
    )
    p.add_argument(
        "--derive-invoice-period-from-csv",
        action="store_true",
        help="Set invoice period from BillingPeriodStart/End in the source CSV",
    )
    p.add_argument(
        "--object-name",
        help="Filename sent to Harness signed URL (default: source file name)",
    )
    p.add_argument("--input-file", help="Local raw or FOCUS CSV")
    p.add_argument(
        "--object-uri",
        help="Remote CSV: s3://, gs://, azure://account/container/blob, or Azure blob HTTPS URL",
    )
    p.add_argument(
        "--s3-uri",
        help="Alias for --object-uri (s3:// only)",
    )
    p.add_argument(
        "--object-prefix",
        help="Folder prefix ending with / — process every .csv (use with --invoice-periods-json)",
    )
    p.add_argument(
        "--s3-prefix",
        help="Alias for --object-prefix (s3:// only)",
    )
    p.add_argument(
        "--invoice-periods-json",
        help='Map object URI to invoice period, e.g. \'{"s3://b/a/july.csv":"20260701-20260731"}\'',
    )
    p.add_argument(
        "--sync-repo-prefix",
        help="Sync a cloud prefix into --sync-repo-dest (pipeline bootstrap; s3/gs/azure)",
    )
    p.add_argument(
        "--sync-repo-dest",
        help="Destination directory for --sync-repo-prefix",
    )
    p.add_argument(
        "--validate-only",
        action="store_true",
        help="Transform + validate; do not call Harness ingest APIs",
    )
    p.add_argument(
        "--inspect-only",
        action="store_true",
        help="After transform, print CSV headers and first data row; skip validation/ingest",
    )
    p.add_argument(
        "--report-out",
        default="validation_report.json",
        help="Write validation JSON here",
    )
    args = p.parse_args(argv)

    if args.sync_repo_prefix:
        if not args.sync_repo_dest:
            p.error("--sync-repo-prefix requires --sync-repo-dest")
        try:
            sync_prefix(args.sync_repo_prefix, Path(args.sync_repo_dest))
        except ObjectStorageError as e:
            print(str(e), file=sys.stderr)
            return 2
        print(f"Synced {args.sync_repo_prefix} → {args.sync_repo_dest}", file=sys.stderr)
        return 0

    for req, label in (
        (args.account_id, "--account-id"),
        (args.api_key, "--api-key"),
        (args.provider_id, "--provider-id"),
    ):
        if not req:
            p.error(f"{label} is required for ingest/validate")

    if not args.invoice_period and not args.derive_invoice_period_from_csv:
        p.error("Provide --invoice-period or --derive-invoice-period-from-csv")

    client = None
    if not args.validate_only:
        client = HarnessExternalDataClient(args.account_id, args.api_key, args.base_url)

    remote_prefix = _remote_prefix(args)
    if remote_prefix:
        if not args.invoice_periods_json:
            print("--object-prefix (or --s3-prefix) requires --invoice-periods-json", file=sys.stderr)
            return 2
        period_map: dict[str, str] = json.loads(args.invoice_periods_json)
        try:
            uris = list_csv_uris(remote_prefix)
        except ObjectStorageError as e:
            print(str(e), file=sys.stderr)
            return 2
        if not uris:
            print(f"No CSV files under {remote_prefix}", file=sys.stderr)
            return 2
        for uri in uris:
            if uri not in period_map:
                print(f"No invoice period for {uri} in --invoice-periods-json", file=sys.stderr)
                return 2
            args.invoice_period = period_map[uri]
            print(f"\n=== {uri} → {args.invoice_period} ===", file=sys.stderr)
            with tempfile.TemporaryDirectory() as td:
                raw_path = Path(td) / "raw.csv"
                focus_path = Path(td) / "focus.csv"
                report_path = Path(td) / "validation_report.json"
                try:
                    download_object(uri, raw_path)
                except ObjectStorageError as e:
                    print(str(e), file=sys.stderr)
                    return 2
                code = _run_one_file(
                    args,
                    raw_path,
                    focus_path,
                    report_path,
                    client,
                    object_basename(uri),
                )
                if code != 0:
                    return code
        return 0

    remote_uri = _remote_uri(args)
    with tempfile.TemporaryDirectory() as td:
        raw_path = Path(td) / "raw.csv"
        focus_path = Path(td) / "focus.csv"
        report_path = Path(args.report_out)

        if remote_uri:
            try:
                download_object(remote_uri, raw_path)
            except ObjectStorageError as e:
                print(str(e), file=sys.stderr)
                return 2
        elif args.input_file:
            raw_path.write_bytes(Path(args.input_file).read_bytes())
        else:
            print(
                "Provide --input-file, --object-uri, --object-prefix, or --sync-repo-prefix",
                file=sys.stderr,
            )
            return 2

        if args.derive_invoice_period_from_csv:
            args.invoice_period = invoice_period_from_csv(raw_path)
            print(f"Derived invoice_period: {args.invoice_period}", file=sys.stderr)

        upload_name = args.object_name
        if not upload_name and args.input_file:
            upload_name = Path(args.input_file).name
        elif not upload_name and remote_uri:
            upload_name = object_basename(remote_uri)

        return _run_one_file(
            args, raw_path, focus_path, report_path, client, upload_name
        )


if __name__ == "__main__":
    raise SystemExit(main())
