"""Download/list objects from AWS S3, Google Cloud Storage, and Azure Blob Storage."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

StorageKind = Literal["s3", "gcs", "azure"]

_AZURE_BLOB_RE = re.compile(
    r"^https://([^.]+)\.blob\.core\.windows\.net/(.+)$",
    re.IGNORECASE,
)
_AZURE_SCHEME_RE = re.compile(
    r"^azure://([^/]+)/([^/]+)/(.+)$",
    re.IGNORECASE,
)


class ObjectStorageError(RuntimeError):
    pass


def storage_kind(uri: str) -> StorageKind:
    uri = uri.strip()
    if uri.startswith("s3://"):
        return "s3"
    if uri.startswith("gs://"):
        return "gcs"
    if uri.startswith("azure://") or _AZURE_BLOB_RE.match(uri):
        return "azure"
    raise ObjectStorageError(
        "Unsupported object URI. Use s3://, gs://, https://<account>.blob.core.windows.net/<container>/..., "
        "or azure://<account>/<container>/<blob>"
    )


def object_basename(uri: str) -> str:
    kind = storage_kind(uri)
    if kind == "azure":
        account, container, blob = _parse_azure(uri)
        name = blob.rstrip("/").split("/")[-1]
        if not name:
            raise ObjectStorageError(f"Cannot infer file name from Azure prefix URI: {uri}")
        return name
    path = uri.split("://", 1)[1]
    name = path.rstrip("/").split("/")[-1]
    if not name:
        raise ObjectStorageError(f"Cannot infer file name from URI: {uri}")
    return unquote(name)


def _parse_azure(uri: str) -> tuple[str, str, str]:
    m = _AZURE_SCHEME_RE.match(uri.strip())
    if m:
        return m.group(1), m.group(2), m.group(3)
    m = _AZURE_BLOB_RE.match(uri.strip())
    if not m:
        raise ObjectStorageError(f"Not a valid Azure blob URI: {uri}")
    account = m.group(1)
    rest = m.group(2).lstrip("/")
    if "/" not in rest:
        raise ObjectStorageError(
            f"Azure URI must include container and blob path: {uri}"
        )
    container, blob = rest.split("/", 1)
    return account, container, blob


def _run(cmd: list[str], *, what: str) -> None:
    if shutil.which(cmd[0]) is None:
        raise ObjectStorageError(f"{what} requires '{cmd[0]}' on PATH")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise ObjectStorageError(f"{what} failed (exit {e.returncode}): {' '.join(cmd)}") from e


def download_object(uri: str, dest: Path) -> None:
    """Download a single object to dest (file path)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    kind = storage_kind(uri)
    if kind == "s3":
        _run(["aws", "s3", "cp", uri, str(dest)], what="S3 download")
        return
    if kind == "gcs":
        _gcs_cp(uri, str(dest), recursive=False)
        return
    account, container, blob = _parse_azure(uri)
    if uri.startswith("https://"):
        _run(
            [
                "az",
                "storage",
                "blob",
                "download",
                "--blob-url",
                uri,
                "--file",
                str(dest),
            ],
            what="Azure blob download",
        )
        return
    _run(
        [
            "az",
            "storage",
            "blob",
            "download",
            "--account-name",
            account,
            "--container-name",
            container,
            "--name",
            blob,
            "--file",
            str(dest),
        ],
        what="Azure blob download",
    )


def sync_prefix(prefix_uri: str, dest_dir: Path) -> None:
    """Sync all objects under a prefix into dest_dir (for pipeline repo bootstrap)."""
    prefix_uri = prefix_uri.rstrip("/") + "/"
    dest_dir.mkdir(parents=True, exist_ok=True)
    kind = storage_kind(prefix_uri)
    if kind == "s3":
        _run(
            ["aws", "s3", "sync", prefix_uri, str(dest_dir) + "/"],
            what="S3 sync",
        )
        return
    if kind == "gcs":
        _gcs_cp(prefix_uri.rstrip("/"), str(dest_dir), recursive=True)
        return
    account, container, blob_prefix = _parse_azure(prefix_uri)
    cmd = [
        "az",
        "storage",
        "blob",
        "download-batch",
        "--destination",
        str(dest_dir),
        "--source",
        container,
        "--account-name",
        account,
    ]
    if blob_prefix:
        cmd.extend(["--pattern", f"{blob_prefix}*"])
    _run(cmd, what="Azure blob download-batch")


def list_csv_uris(prefix_uri: str) -> list[str]:
    """List gs:// / s3:// / Azure blob URIs for every .csv under prefix (prefix ends with /)."""
    prefix_uri = prefix_uri.rstrip("/") + "/"
    kind = storage_kind(prefix_uri)
    if kind == "s3":
        return _list_s3_csvs(prefix_uri)
    if kind == "gcs":
        return _list_gcs_csvs(prefix_uri)
    return _list_azure_csvs(prefix_uri)


def _list_s3_csvs(prefix: str) -> list[str]:
    proc = subprocess.run(
        ["aws", "s3", "ls", prefix, "--recursive"],
        check=True,
        capture_output=True,
        text=True,
    )
    bucket = prefix.split("/")[2]
    uris: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        key = parts[-1]
        if key.lower().endswith(".csv"):
            uris.append(f"s3://{bucket}/{key}")
    return sorted(uris)


def _list_gcs_csvs(prefix: str) -> list[str]:
    # gs://bucket/path/
    without = prefix[len("gs://") :]
    bucket = without.split("/", 1)[0]
    blob_prefix = without.split("/", 1)[1] if "/" in without else ""

    if shutil.which("gcloud"):
        proc = subprocess.run(
            [
                "gcloud",
                "storage",
                "ls",
                "--recursive",
                f"gs://{bucket}/{blob_prefix}**",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        uris = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.startswith("gs://") and line.lower().endswith(".csv"):
                uris.append(line)
        return sorted(uris)

    if shutil.which("gsutil"):
        proc = subprocess.run(
            ["gsutil", "ls", "-r", prefix.rstrip("/") + "**.csv"],
            check=True,
            capture_output=True,
            text=True,
        )
        return sorted(line.strip() for line in proc.stdout.splitlines() if line.strip())

    raise ObjectStorageError("GCS list requires gcloud or gsutil on PATH")


def _list_azure_csvs(prefix_uri: str) -> list[str]:
    account, container, blob_prefix = _parse_azure(prefix_uri)
    proc = subprocess.run(
        [
            "az",
            "storage",
            "blob",
            "list",
            "--account-name",
            account,
            "--container-name",
            container,
            "--prefix",
            blob_prefix,
            "--query",
            "[].name",
            "-o",
            "tsv",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    base = f"https://{account}.blob.core.windows.net/{container}/"
    return sorted(
        base + name.strip()
        for name in proc.stdout.splitlines()
        if name.strip().lower().endswith(".csv")
    )


def _gcs_cp(src: str, dest: str, *, recursive: bool) -> None:
    if shutil.which("gcloud"):
        cmd = ["gcloud", "storage", "cp"]
        if recursive:
            cmd.append("-r")
        cmd.extend([src, dest])
        _run(cmd, what="GCS copy")
        return
    if shutil.which("gsutil"):
        cmd = ["gsutil", "-m", "cp"]
        if recursive:
            cmd.append("-r")
        cmd.extend([src, dest])
        _run(cmd, what="GCS copy")
        return
    raise ObjectStorageError("GCS operations require gcloud or gsutil on PATH")
