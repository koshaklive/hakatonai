"""PocketBase JWT check on every request; role and access_level come from the verified user record only."""
from __future__ import annotations

import time
from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class AuthUser:
    """Authenticated caller."""
    id: str
    role: str
    access_level: int
    token: str = ""


class Authenticator:
    """auth-refresh against PocketBase (tiny TTL cache so a burst of requests costs one round-trip)."""

    def __init__(self, cfg: Settings, pb=None) -> None:  # noqa: ANN001
        self.cfg, self.pb, self._cache = cfg, pb, {}

    def authenticate(self, header: str | None) -> AuthUser:
        """Raise PermissionError on missing/invalid token."""
        if self.cfg.auth_mode == "dev":
            return AuthUser("dev", "admin", self.cfg.dev_access_level)
        if not header:
            raise PermissionError("missing token")
        token = header.removeprefix("Bearer ").strip()
        hit = self._cache.get(token)
        if hit and hit[0] > time.time():
            return hit[1]
        try:
            rec = self.pb.verify_user_token(token)
        except Exception as e:  # noqa: BLE001
            raise PermissionError("invalid token") from e
        user = AuthUser(rec["id"], rec.get("role", "employee"), int(rec.get("access_level", 1)), token)
        if self.cfg.auth_cache_ttl > 0:
            self._cache[token] = (time.time() + self.cfg.auth_cache_ttl, user)
        return user
