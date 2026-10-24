"""Fire-and-forget persistence of messages + audit_log in PocketBase."""
from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.config import Settings
from app.core.pb import PocketBase

log = logging.getLogger("audit")


class Audit:
    def __init__(self, cfg: Settings, pb: PocketBase) -> None:
        self.cfg, self.pb = cfg, pb

    def _run(self, fn: Any) -> None:
        def safe() -> None:
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                log.warning("audit write failed: %s", e)
        threading.Thread(target=safe, daemon=True).start()

    def event(self, u: Any, endpoint: str, query: str = "", status: int = 200, **extra: Any) -> None:
        rec = {"user": getattr(u, "id", None) if getattr(u, "id", "dev") != "dev" else None,
               "role": getattr(u, "role", "service"), "access_level": getattr(u, "access_level", None),
               "endpoint": endpoint, "query": query[:2000], "status": status, "meta": extra}
        self._run(lambda: self.pb.create(self.cfg.pb_audit, rec))

    def chat(self, u: Any, endpoint: str, cid: str, message: str, out: dict[str, Any]) -> None:
        uid = getattr(u, "id", None) if getattr(u, "id", "dev") != "dev" else None
        pts = [s["point"] for s in out.get("sources", [])]

        def w() -> None:
            self.pb.create(self.cfg.pb_messages, {"conversation_id": cid, "user": uid, "role": "user", "content": message})
            self.pb.create(self.cfg.pb_messages, {"conversation_id": cid, "user": uid, "role": "assistant",
                                                  "content": out["answer"], "sources": out.get("sources", []),
                                                  "meta": {"no_answer": out["no_answer"], "clarification": out["clarification"],
                                                           "query_used": out["query_used"], "gray_zone": out.get("gray_zone")}})
            self.pb.create(self.cfg.pb_audit, {"user": uid, "role": getattr(u, "role", None),
                                               "access_level": getattr(u, "access_level", None), "endpoint": endpoint,
                                               "query": message[:2000], "status": 200, "latency_ms": out["latency_ms"],
                                               "meta": {"conversation_id": cid, "points": pts, "no_answer": out["no_answer"],
                                                        "clarification": bool(out["clarification"])}})
        self._run(w)