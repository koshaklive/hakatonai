"""Anchors: topic regexes → points that must always be in context (config in anchors.yaml, not in code)."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger("anchors")


@dataclass
class Anchor:
    """One anchor rule."""
    name: str
    patterns: list[re.Pattern[str]]
    points: list[str]


def load_anchors(path: str | Path) -> list[Anchor]:
    """Parse anchors.yaml (missing file → no anchors)."""
    p = Path(path)
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return [Anchor(a["name"], [re.compile(x, re.I) for x in a["patterns"]], [str(x) for x in a["points"]])
            for a in raw.get("anchors", [])]


def match_anchors(query: str, anchors: list[Anchor], known_points: set[str]) -> list[str]:
    """Ordered, de-duplicated anchor points triggered by the query (unknown points are skipped with a warning)."""
    out: list[str] = []
    for a in anchors:
        if any(p.search(query) for p in a.patterns):
            for pt in a.points:
                if pt not in known_points:
                    log.warning("anchor %s points to unknown point %s", a.name, pt)
                elif pt not in out:
                    out.append(pt)
    return out
