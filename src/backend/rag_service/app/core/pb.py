"""Minimal PocketBase 0.22 client (service user): records, file download, auth-refresh."""
from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import Settings


class PocketBase:
    """Synchronous client; re-authenticates the service user when the token expires."""

    def __init__(self, cfg: Settings) -> None:
        self.cfg, self._token, self._exp = cfg, "", 0.0
        self.http = httpx.Client(base_url=cfg.pb_url, timeout=10)

    def _auth(self) -> dict[str, str]:
        if time.time() > self._exp:
            r = self.http.post("/api/collections/users/auth-with-password",
                               json={"identity": self.cfg.pb_email, "password": self.cfg.pb_password})
            r.raise_for_status()
            self._token, self._exp = r.json()["token"], time.time() + 600
        return {"Authorization": self._token}

    def get(self, collection: str, rid: str) -> dict[str, Any]:
        """Fetch one record."""
        r = self.http.get(f"/api/collections/{collection}/records/{rid}", headers=self._auth())
        r.raise_for_status()
        return r.json()

    def patch(self, collection: str, rid: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update fields of a record."""
        r = self.http.patch(f"/api/collections/{collection}/records/{rid}", json=data, headers=self._auth())
        r.raise_for_status()
        return r.json()

    def list(self, collection: str, **params: Any) -> list[dict[str, Any]]:
        """List records (first page, perPage=200)."""
        r = self.http.get(f"/api/collections/{collection}/records", params={"perPage": 200, **params}, headers=self._auth())
        r.raise_for_status()
        return r.json()["items"]

    def download(self, record: dict[str, Any], field: str) -> bytes:
        """Download a file field of a record."""
        name = record[field]
        r = self.http.get(f"/api/files/{record['collectionId']}/{record['id']}/{name}", headers=self._auth())
        r.raise_for_status()
        return r.content

    def verify_user_token(self, token: str) -> dict[str, Any]:
        """Validate a user JWT via auth-refresh; returns the user record (raises on invalid token)."""
        r = self.http.post("/api/collections/users/auth-refresh", headers={"Authorization": token})
        r.raise_for_status()
        return r.json()["record"]

    def ping(self) -> bool:
        """True if PocketBase answers /api/health."""
        try:
            return self.http.get("/api/health", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False
