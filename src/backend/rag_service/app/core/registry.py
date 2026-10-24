"""Tiny on-disk registry of indexed versions; the 'active' pointer is swapped only after a successful build."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Registry:
    """indexes/registry.json: {"active": slug, "versions": {slug: {label, chunks, indexed_at}}}."""

    def __init__(self, index_dir: Path) -> None:
        self.dir, self.path = index_dir, index_dir / "registry.json"

    def read(self) -> dict[str, Any]:
        """Current registry content (empty skeleton if absent)."""
        if not self.path.exists():
            return {"active": None, "versions": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def activate(self, slug: str, label: str, chunks: int) -> None:
        """Register a finished build and make it the active one (atomic write)."""
        data = self.read()
        data["versions"][slug] = {"label": label, "chunks": chunks,
                                  "indexed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        data["active"] = slug
        self.restore(data)

    def restore(self, data: dict[str, Any]) -> None:
        """Atomically persist a registry snapshot, including the active pointer."""
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)
