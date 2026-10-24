"""Minimal PocketBase client (service account + user token refresh)."""
from __future__ import annotations

import threading
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings


class PocketBase:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.http = httpx.Client(base_url=cfg.pb_url.rstrip("/"), timeout=10)
        self._tok: str | None = None
        self._lock = threading.Lock()

    def ping(self) -> bool:
        try:
            return self.http.get("/api/health").status_code == 200
        except httpx.HTTPError:
            return False

    def _login(self) -> None:
        body = {"identity": self.cfg.pb_email, "password": self.cfg.pb_password}
        r = self.http.post("/api/collections/_superusers/auth-with-password", json=body)
        if r.status_code == 404:  # PocketBase < 0.23
            r = self.http.post("/api/admins/auth-with-password", json=body)
        r.raise_for_status()
        self._tok = r.json()["token"]

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        with self._lock:
            if not self._tok:
                self._login()
        for attempt in (0, 1):
            r = self.http.request(method, path, headers={"Authorization": self._tok or ""}, **kw)
            if r.status_code == 401 and attempt == 0:
                with self._lock:
                    self._login()
                continue
            r.raise_for_status()
            return r
        raise RuntimeError("unreachable")

    def _req(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        return self._request(method, path, **kw).json()

    def get(self, collection: str, record_id: str) -> dict[str, Any]:
        return self._req("GET", f"/api/collections/{collection}/records/{record_id}")

    def patch(self, collection: str, record_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._req("PATCH", f"/api/collections/{collection}/records/{record_id}", json=data)

    def download(self, record: dict[str, Any], field: str) -> bytes:
        filename = record.get(field)
        if isinstance(filename, list):
            filename = filename[0] if filename else None
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError(f"record has no attached file in {field!r}")
        collection = record.get("collectionName") or "document_versions"
        record_id = record.get("id")
        if not record_id:
            raise ValueError("record has no id for attached file download")
        path = f"/api/files/{quote(collection, safe='')}/{quote(str(record_id), safe='')}/{quote(filename, safe='')}"
        return self._request("GET", path).content

    def create(self, collection: str, data: dict[str, Any]) -> dict[str, Any]:
        return self._req("POST", f"/api/collections/{collection}/records", json=data)

    def auth_refresh(self, token: str, collection: str) -> dict[str, Any]:
        r = self.http.post(f"/api/collections/{collection}/auth-refresh", headers={"Authorization": token})
        r.raise_for_status()
        return r.json()