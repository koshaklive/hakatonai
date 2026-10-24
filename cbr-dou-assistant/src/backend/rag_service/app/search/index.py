"""Loaded index = chunks + BM25 (+ optional dense). Persisted as chunks.json; BM25 is rebuilt on load."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.core.chunks import Chunk, part_index, point_of, strip_prefix
from app.core.config import Settings
from app.search.bm25 import BM25
from app.search.dense import DenseIndex
from app.search.tokenize import find_abbreviations, tokenize


def lexical_text(c: Chunk) -> str:
    """Text fed to BM25: chunk text plus curated keywords."""
    return c["text"] + " " + " ".join(c.get("keywords", []))


@dataclass
class LoadedIndex:
    """In-memory view of one indexed version."""
    version: str
    chunks: list[Chunk]
    bm25: BM25
    abbrevs: frozenset[str]
    dense: DenseIndex | None = None
    by_id: dict[str, Chunk] = field(init=False)
    points: dict[str, list[Chunk]] = field(init=False)
    access: np.ndarray = field(init=False)
    pos: dict[str, int] = field(init=False)

    def __post_init__(self) -> None:
        self.by_id = {c["id"]: c for c in self.chunks}
        self.pos = {c["id"]: i for i, c in enumerate(self.chunks)}
        pts: dict[str, list[Chunk]] = {}
        for c in self.chunks:
            pts.setdefault(point_of(c["id"]), []).append(c)
        self.points = {p: sorted(cs, key=part_index) for p, cs in pts.items()}
        self.access = np.array([c["access_level"] for c in self.chunks])

    def point_text(self, point: str) -> str:
        """Full text of a point: parts glued in order, repeated prefixes removed."""
        cs = self.points[point]
        return "\n".join([cs[0]["text"], *[strip_prefix(c["text"]) for c in cs[1:]]])

    def point_chunk(self, point: str) -> Chunk:
        """First part of a point (carries chapter/page/version)."""
        return self.points[point][0]


def build_lexical(chunks: list[Chunk], cfg: Settings, dense: DenseIndex | None = None) -> LoadedIndex:
    """Build BM25 + abbreviation vocabulary from validated chunks."""
    chunks = [c for c in chunks if not c.get("virtual") and str(c["text"]).strip()]  # defensive: never index virtual
    abbrevs = frozenset(find_abbreviations((c["text"] for c in chunks), cfg.abbr_min_df))
    docs = [tokenize(lexical_text(c), abbrevs) for c in chunks]
    return LoadedIndex(chunks[0]["version"], chunks, BM25(docs, cfg.bm25_k1, cfg.bm25_b), abbrevs, dense)


def save_chunks(idx_dir: Path, chunks: list[Chunk]) -> None:
    """Atomically write chunks.json into the version directory."""
    idx_dir.mkdir(parents=True, exist_ok=True)
    tmp = idx_dir / "chunks.json.tmp"
    tmp.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    tmp.replace(idx_dir / "chunks.json")


def load_chunks_dir(idx_dir: Path) -> list[Chunk]:
    """Read chunks.json of a version directory."""
    return json.loads((idx_dir / "chunks.json").read_text(encoding="utf-8"))
