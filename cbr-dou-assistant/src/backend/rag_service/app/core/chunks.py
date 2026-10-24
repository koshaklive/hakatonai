"""Chunk contract helpers: loading, validation, part merging. No point numbers are hardcoded."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

Chunk = dict[str, Any]
_PREFIX = re.compile(r"^.+? > п\. [\w.]+?\.\s+")


def point_of(chunk_id: str) -> str:
    """'10.2#2' -> '10.2'; plain ids are returned unchanged."""
    return chunk_id.split("#", 1)[0]


def part_index(chunk: Chunk) -> int:
    """1-based part number of a split point (1 for non-split chunks)."""
    return int((chunk.get("part") or {}).get("index", 1))


def strip_prefix(text: str) -> str:
    """Remove the 'Глава N. ... > п. X.Y.' prefix from a chunk text."""
    return _PREFIX.sub("", text, count=1)


def load_chunks(path: str | Path) -> list[Chunk]:
    """Read the JSON array of chunks."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("chunks file must contain a JSON array")
    return data


def validate(chunks: list[Chunk]) -> dict[str, Any]:
    """Return {'indexable': [...], 'report': {...}}; raises ValueError on a broken contract."""
    seen: set[str] = set()
    indexable: list[Chunk] = []
    skipped_virtual = 0
    for c in chunks:
        for key in ("id", "text", "version", "access_level"):
            if key not in c:
                raise ValueError(f"chunk {c.get('id')!r} lacks required field {key!r}")
        if c["id"] in seen:
            raise ValueError(f"duplicate chunk id {c['id']!r}")
        seen.add(c["id"])
        if c.get("virtual"):
            skipped_virtual += 1
            continue
        if not str(c["text"]).strip():
            continue
        indexable.append(c)
    points = {point_of(c["id"]) for c in indexable}
    dangling = sorted({r for c in indexable for r in c.get("refs", [])
                       if not r.startswith("ch:") and r not in points})
    versions = {c["version"] for c in indexable}
    if len(versions) != 1:
        raise ValueError(f"file must hold exactly one version, got {sorted(versions)}")
    return {"indexable": indexable,
            "report": {"total": len(chunks), "indexed": len(indexable), "virtual_skipped": skipped_virtual,
                       "points": len(points), "dangling_refs": dangling, "version": versions.pop()}}


def slug(version: str) -> str:
    """Filesystem / collection-safe version label."""
    return re.sub(r"[^0-9A-Za-zА-Яа-я]+", "_", version).strip("_") or "v"
