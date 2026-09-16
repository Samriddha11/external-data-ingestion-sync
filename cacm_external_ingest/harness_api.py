"""Harness CCM External Data Provider REST client."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

import requests

DEFAULT_BASE = "https://app.harness.io"


class HarnessExternalDataClient:
    def __init__(
        self,
        account_id: str,
        api_key: str,
        base_url: str = DEFAULT_BASE,
    ) -> None:
        api_key = (api_key or "").strip()
        if "\n" in api_key or "\r" in api_key:
            raise ValueError(
                "HARNESS_API_KEY contains a newline — export a single PAT on one line. "
                "Example: export HARNESS_API_KEY='pat.xxx'"
            )
        self.account_id = account_id
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "x-api-key": api_key,
                "Content-Type": "application/json",
            }
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url}/gateway/ccm/api{path}"

    def list_providers(self) -> Dict[str, Any]:
        r = self.session.post(
            self._url("/externaldata/provider/list"),
            params={"accountIdentifier": self.account_id},
            json={},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def get_signed_url(
        self,
        provider_id: str,
        invoice_period: str,
        object_name: str,
    ) -> str:
        r = self.session.get(
            self._url("/externaldata/signedurl"),
            params={
                "accountIdentifier": self.account_id,
                "providerId": provider_id,
                "invoicePeriod": invoice_period,
                "objectName": object_name,
            },
            timeout=60,
        )
        if not r.ok:
            raise RuntimeError(
                f"signedurl failed ({r.status_code}): {r.text[:2000]}"
            )
        body = r.json()
        data = body.get("data") or body
        if isinstance(data, dict):
            url = data.get("signedUrl") or data.get("url")
            if url:
                return url
        if isinstance(body.get("data"), str):
            return body["data"]
        raise RuntimeError(f"Unexpected signed URL response: {json.dumps(body)[:500]}")

    def create_file_metadata(
        self,
        provider_id: str,
        name: str,
        invoice_month: str,
        md5_hex: str,
        file_extension: str = "CSV",
    ) -> Dict[str, Any]:
        payload = {
            "externalDataFiles": {
                "accountId": self.account_id,
                "providerId": provider_id,
                "name": name,
                "invoiceMonth": invoice_month,
                "md5": md5_hex,
                "fileExtension": file_extension,
                "uploadStatus": "INPROGRESS",
                "signedUrlUsed": True,
            }
        }
        r = self.session.post(
            self._url("/externaldata/filesinfo"),
            params={"accountIdentifier": self.account_id},
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def update_file_metadata(
        self,
        file_id: str,
        record: Dict[str, Any],
        upload_status: str = "COMPLETE",
    ) -> Dict[str, Any]:
        record = dict(record)
        record["uploadStatus"] = upload_status
        payload = {"externalDataFiles": record}
        r = self.session.put(
            self._url(f"/externaldata/filesinfo/{file_id}"),
            params={"accountIdentifier": self.account_id},
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def trigger_ingestion(
        self,
        provider_id: str,
        invoice_periods: list[str],
    ) -> Dict[str, Any]:
        payload = {
            "accountId": self.account_id,
            "providerId": provider_id,
            "invoicePeriod": invoice_periods,
        }
        r = self.session.post(
            self._url("/externaldata/dataingestion"),
            params={"accountIdentifier": self.account_id},
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        return r.json()

    def upload_file(self, path: Path, signed_url: str) -> None:
        data = path.read_bytes()
        put = requests.put(
            signed_url,
            data=data,
            headers={"Content-Type": "text/csv"},
            timeout=300,
        )
        put.raise_for_status()

    @staticmethod
    def md5_file(path: Path) -> str:
        h = hashlib.md5()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def ingest_focus_csv(
        self,
        provider_id: str,
        invoice_period: str,
        csv_path: Path,
        object_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        object_name = object_name or csv_path.name
        md5_hex = self.md5_file(csv_path)
        signed = self.get_signed_url(provider_id, invoice_period, object_name)
        meta_resp = self.create_file_metadata(
            provider_id,
            object_name,
            invoice_period,
            md5_hex,
        )
        file_rec = (meta_resp.get("data") or meta_resp).copy()
        file_id = file_rec.get("uuid") or file_rec.get("id")
        if not file_id:
            raise RuntimeError(f"No file id in metadata response: {meta_resp}")

        self.upload_file(csv_path, signed)
        self.update_file_metadata(file_id, file_rec, "COMPLETE")
        ingest_resp = self.trigger_ingestion(provider_id, [invoice_period])
        return {
            "file_id": file_id,
            "md5": md5_hex,
            "ingestion": ingest_resp,
        }
