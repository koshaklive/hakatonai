"""Shared helpers for eval / compare / calibrate / chat checks (no business logic, no hardcoded points)."""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core.chunks import load_chunks, validate  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.search.anchors import load_anchors  # noqa: E402
from app.search.dense import NumpyDense  # noqa: E402
from app.search.hybrid import Searcher  # noqa: E402
from app.search.index import LoadedIndex, build_lexical  # noqa: E402

MODES = ("lexical", "dense", "hybrid", "rerank")


class QueryEmbedder:
    """Query embedder WITHOUT the sqlite cache, so latency numbers are real (Embedder.embed_query would hit the cache)."""

    def __init__(self, emb: Any) -> None:
        self.emb = emb

    def embed_query(self, text: str) -> np.ndarray:
        return self.emb.model.encode([text], normalize_embeddings=True, show_progress_bar=False)[0].astype(np.float32)


@dataclass
class World:
    cfg: Settings
    index: LoadedIndex
    embedder: QueryEmbedder | None
    reranker: Any | None
    anchors: list


def build_world(cfg: Settings, dense: bool, rerank: bool = False) -> World:
    """Index the data file in memory (vectors come from the Embedder's sqlite cache after the first run)."""
    chunks = validate(load_chunks(cfg.data_file))["indexable"]
    emb = qe = rr = dn = None
    if dense:
        from llm_layer.embeddings import Embedder
        emb = Embedder(model=cfg.emb_model)
        vecs = emb.embed([c["text"] for c in chunks])
        dn = NumpyDense([c["id"] for c in chunks], vecs, [c["access_level"] for c in chunks])
        qe = QueryEmbedder(emb)
    if rerank:
        from llm_layer.embeddings import Reranker
        rr = Reranker()
    return World(cfg, build_lexical(chunks, cfg, dn), qe, rr, load_anchors(cfg.anchors_file))


def searcher(w: World, mode: str = "hybrid", anchors: bool = True) -> Searcher:
    """One Searcher per comparison mode. dense-only = hybrid with BM25 candidates switched off (BM25_K=0)."""
    cfg = {"lexical": replace(w.cfg, rerank=False, bm25_k=max(w.cfg.bm25_k, 20)),
           "dense": replace(w.cfg, rerank=False, bm25_k=0),
           "hybrid": replace(w.cfg, rerank=False),
           "rerank": replace(w.cfg, rerank=True)}[mode]
    emb = None if mode == "lexical" else w.embedder
    rr = w.reranker if mode == "rerank" else None
    if mode != "lexical" and emb is None:
        raise RuntimeError(f"mode {mode!r} needs the dense embedder")
    if mode == "rerank" and rr is None:
        raise RuntimeError("mode 'rerank' needs the reranker")
    return Searcher(cfg, w.index, emb, rr, w.anchors if anchors else [])


def load_gold(path: str | Path | None) -> list[dict[str, Any]]:
    p = Path(path) if path else ROOT / "tests" / "gold_search.json"
    if not p.exists():
        sys.exit(f"gold file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def rank_of(points: list[str], expect: set[str]) -> int | None:
    return next((i + 1 for i, p in enumerate(points) if p in expect), None)


def metrics(ranks: list[int | None]) -> dict[str, float]:
    n = len(ranks) or 1
    return {"n": len(ranks), "hit1": sum(r == 1 for r in ranks) / n, "hit5": sum(r is not None for r in ranks) / n,
            "mrr": sum(1 / r for r in ranks if r) / n}


def pct(x: list[float], q: float) -> float:
    return float(np.percentile(x, q)) if x else float("nan")


def timed(s: Searcher, q: str, max_access: int = 3):
    t = time.perf_counter()
    r = s.search(q, max_access=max_access)
    return r, (time.perf_counter() - t) * 1000
