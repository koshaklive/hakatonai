"""anchors.yaml loader: regex patterns → forced points; supports globs (MTX.int.[1-4], MTX.ext.*) and per-anchor `limit`."""
from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger("anchors")
_GLOB = re.compile(r"[*?\[]")


class Pat(str):
    """Pattern usable both as a plain string and as a compiled regex (.search)."""
    def __new__(cls, s: str) -> "Pat":
        o = super().__new__(cls, "(?i)" + s)
        o._rx = re.compile(s, re.I)
        return o

    def search(self, text: str):  # noqa: ANN201
        return self._rx.search(text)


@dataclass
class Anchor:
    name: str
    patterns: list[Pat]
    points: list[str]
    limit: int | None = None
    raw_points: list[str] = field(default_factory=list)


def load_anchors(path: str | Path) -> list[Anchor]:
    p = Path(path)
    if not p.exists():
        return []
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out = []
    for a in doc.get("anchors", []):
        pts = [str(x) for x in a.get("points", [])]
        out.append(Anchor(a["name"], [Pat(x) for x in a.get("patterns", [])], pts, a.get("limit"), pts))
    return out


def _nat(s: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def expand_anchors(anchors: list[Anchor], ids: set[str]) -> list[Anchor]:
    """Resolve globs against indexed point ids, drop unknown literals, apply per-anchor limit."""
    res = []
    for a in anchors:
        pts: list[str] = []
        for x in a.raw_points:
            got = sorted(fnmatch.filter(ids, x), key=_nat) if _GLOB.search(x) else ([x] if x in ids else [])
            if not got:
                log.warning("anchor %s: point %s not in index", a.name, x)
            pts += [g for g in got if g not in pts]
        if a.limit:
            pts = pts[:a.limit]
        if pts:
            res.append(Anchor(a.name, a.patterns, pts, a.limit, a.raw_points))
    return res


def match_anchors(query: str, anchors: list[Anchor], ids: set[str]) -> list[str]:
    """Return unique point ids for anchors whose patterns match the query."""
    points: list[str] = []
    for anchor in expand_anchors(anchors, ids):
        if any(pattern.search(query) for pattern in anchor.patterns):
            points.extend(point for point in anchor.points if point not in points)
    return points