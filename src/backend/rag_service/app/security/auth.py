"""PocketBase JWT verification; access_level comes from the token claim or (authoritatively) the user record."""
from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.core.pb import PocketBase


@dataclass
class AuthUser:
    id: str
    email: str
    role: str
    access_level: int


def jwt_payload(token: str) -> dict[str, Any]:
    try:
        b = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))
    except Exception as e:  # noqa: BLE001
        raise PermissionError("malformed token") from e


class Authenticator:
    def __init__(self, cfg: Settings, pb: PocketBase) -> None:
        self.cfg, self.pb = cfg, pb
        self._cache: dict[str, tuple[float, AuthUser]] = {}

    def authenticate(self, authorization: str | None) -> AuthUser:
        if self.cfg.auth_mode == "dev":
            return AuthUser("dev", "dev@local", "admin", self.cfg.dev_access_level)
        if not authorization or not authorization.lower().startswith("bearer "):
            raise PermissionError("missing bearer token")
        token = authorization.split(None, 1)[1].strip()
        p = jwt_payload(token)
        if p.get("type") != "auth" or float(p.get("exp", 0)) < time.time():
            raise PermissionError("token expired or not an auth token")
        key = hashlib.sha256(token.encode()).hexdigest()
        hit = self._cache.get(key)
        if hit and hit[0] > time.time():
            return hit[1]
        try:
            rec = self.pb.auth_refresh(token, self.cfg.pb_users_collection)["record"]
        except (httpx.HTTPError, KeyError) as e:
            raise PermissionError("invalid token") from e
        lvl = rec.get("access_level", p.get("access_level", 1))
        u = AuthUser(rec["id"], rec.get("email", ""), rec.get("role", "user"), max(1, int(lvl or 1)))
        self._cache[key] = (time.time() + self.cfg.auth_cache_ttl, u)
        if len(self._cache) > 1000:
            self._cache = {k: v for k, v in self._cache.items() if v[0] > time.time()}
        return u