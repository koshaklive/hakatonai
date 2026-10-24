"""Hybrid retrieval: direct match → dense+BM25 → RRF → optional rerank → anchors / related / parent head."""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from app.core.chunks import Chunk, point_of, strip_prefix
from app.core.config import Settings
from app.core.search import normalize_query
from app.search.anchors import Anchor, match_anchors
from app.search.direct import extract_points
from app.search.index import LoadedIndex
from app.search.tokenize import tokenize


class QueryEmbedder(Protocol):
    """Minimal embedder interface (llm_layer.embeddings.Embedder satisfies it)."""
    def embed_query(self, text: str) -> np.ndarray: ...


class Reranker(Protocol):
    """Minimal reranker interface (llm_layer.embeddings.Reranker satisfies it)."""
    def rerank(self, query: str, docs: list[str], top_k: int = 5) -> list[tuple[int, float]]: ...


@dataclass
class Hit:
    """One context fragment (a whole point, parts already glued)."""
    point: str
    chunk_ids: list[str]
    chapter: str
    chapter_no: int | None
    page: int | None
    page_end: int | None
    version: str
    text: str
    relevance: float
    source: str                      # direct | hybrid | anchor | related
    head: str | None = None          # parent intro for sub-points
    scores: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["relevance_pct"] = round(100 * self.relevance)
        return d


@dataclass
class SearchResult:
    """Search output."""
    query: str
    method: str                      # direct | hybrid | lexical
    hits: list[Hit]
    max_relevance: float
    version: str
    timings_ms: dict[str, int]


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


class Searcher:
    """Stateless w.r.t. requests; holds one LoadedIndex plus optional embedder/reranker/anchors."""

    def __init__(self, cfg: Settings, index: LoadedIndex, embedder: QueryEmbedder | None = None,
                 reranker: Reranker | None = None, anchors: list[Anchor] | None = None) -> None:
        self.cfg, self.index, self.embedder, self.reranker = cfg, index, embedder, reranker
        self.anchors = anchors or []

    # ---- helpers ----
    def _allowed(self, max_access: int, filters: dict[str, Any] | None) -> np.ndarray:
        ok = self.index.access <= max_access
        for key, want in (filters or {}).items():
            wants = want if isinstance(want, list) else [want]
            ok &= np.array([c.get(key) in wants for c in self.index.chunks])
        return ok

    def _hit(self, point: str, rel: float, source: str, ids: list[str] | None = None,
             scores: dict[str, float] | None = None) -> Hit:
        ix = self.index
        c = ix.point_chunk(point)
        head = None
        if c.get("parent_id") and c["parent_id"] in ix.points:
            parent = strip_prefix(ix.point_text(c["parent_id"]))
            head = parent.split("\n", 1)[0][:300]
        cs = ix.points[point]
        return Hit(point, ids or [x["id"] for x in cs], c.get("chapter", ""), c.get("chapter_no"),
                   c.get("page"), cs[-1].get("page_end", c.get("page_end")), c["version"], ix.point_text(point),
                   rel, source, head, scores or {})

    def _normalize(self, query_tokens: list[str], bm_raw: np.ndarray, dense: dict[str, float]) -> dict[str, tuple[float, float]]:
        ub = self.index.bm25.upper_bound(query_tokens)
        ids = [c["id"] for c in self.index.chunks]
        return {cid: (dense.get(cid, 0.0), float(bm_raw[i]) / ub) for i, cid in enumerate(ids)}

    # ---- main ----
    def search(self, query: str, top_k: int | None = None, max_access: int = 1,
               filters: dict[str, Any] | None = None) -> SearchResult:
        """Run the full retrieval pipeline for one (already standalone) query."""
        query = normalize_query(query)
        cfg, ix = self.cfg, self.index
        limit = min(top_k or cfg.fragment_limit, cfg.fragment_limit)
        tm: dict[str, int] = {}
        t0 = time.perf_counter()
        allowed = self._allowed(max_access, filters)

        # 1) direct point match (regex), no vector search
        direct = [p for p in extract_points(query) if p in ix.points and allowed[ix.pos[ix.points[p][0]["id"]]]]
        if direct:
            hits = [self._hit(p, 1.0, "direct") for p in direct][:limit]
            hits = self._related(hits, limit)
            hits = self._visa_anchors(query, hits, max_access, limit)
            tm["total"] = int((time.perf_counter() - t0) * 1000)
            return SearchResult(query, "direct", hits, 1.0, ix.version, tm)

        # 2) lexical + dense candidates
        qt = tokenize(query, ix.abbrevs)
        bm_raw = np.where(allowed, ix.bm25.scores(qt), -1.0)
        bm_top = [i for i in np.argsort(-bm_raw)[:cfg.bm25_k] if bm_raw[i] > 0]
        tm["bm25"] = int((time.perf_counter() - t0) * 1000)
        dense_hits: list[tuple[str, float]] = []
        if ix.dense is not None and self.embedder is not None and cfg.dense_enabled:
            t1 = time.perf_counter()
            dense_hits = [(cid, s) for cid, s in ix.dense.search(self.embedder.embed_query(query), cfg.dense_k, max_access)
                          if cid in ix.pos and allowed[ix.pos[cid]]]
            tm["dense"] = int((time.perf_counter() - t1) * 1000)
        dense_map = dict(dense_hits)

        # 3) RRF
        rrf: dict[str, float] = {}
        for rank, i in enumerate(bm_top):
            cid = ix.chunks[i]["id"]
            rrf[cid] = rrf.get(cid, 0) + 1 / (cfg.rrf_k + rank + 1)
        for rank, (cid, _) in enumerate(dense_hits):
            rrf[cid] = rrf.get(cid, 0) + 1 / (cfg.rrf_k + rank + 1)
        ranked = sorted(rrf, key=lambda c: -rrf[c])
        norm = self._normalize(qt, bm_raw, dense_map)

        # 4) relevance per chunk
        rel: dict[str, float] = {}
        for cid in ranked:
            d, b = norm[cid]
            rel[cid] = min(1.0, (cfg.rel_w_dense * d + cfg.rel_w_bm25 * b) if dense_hits else b)
        method = "hybrid" if dense_hits else "lexical"

        # 5) optional rerank (CPU)
        if cfg.rerank and self.reranker is not None and ranked:
            t2 = time.perf_counter()
            pool = ranked[:cfg.rerank_pool]
            order = self.reranker.rerank(query, [ix.by_id[c]["text"] for c in pool], top_k=len(pool))
            ranked = [pool[i] for i, _ in order]
            rel = {pool[i]: _sigmoid(s) for i, s in order}
            tm["rerank"] = int((time.perf_counter() - t2) * 1000)

        # 6) aggregate parts → points
        seen: dict[str, Hit] = {}
        for cid in ranked:
            p = point_of(cid)
            if p in seen:
                seen[p].relevance = max(seen[p].relevance, rel[cid])
                seen[p].scores["rrf"] = max(seen[p].scores["rrf"], rrf.get(cid, 0))
                continue
            d, b = norm[cid]
            seen[p] = self._hit(p, rel[cid], "hybrid", scores={"dense": d, "bm25n": b, "rrf": rrf.get(cid, 0)})
        core = list(seen.values())

        # 7) anchors (forced) + related, within the global fragment limit
        hits = self._compose(query, core, limit, max_access)
        hits = self._visa_anchors(query, hits, max_access, limit)
        tm["total"] = int((time.perf_counter() - t0) * 1000)
        mx = max((h.relevance for h in core), default=0.0)
        return SearchResult(query, method, hits, mx, ix.version, tm)

    def _visa_anchors(self, query: str, hits: list[Hit], max_access: int, limit: int) -> list[Hit]:
        if not re.search(r"визир", query, re.I):
            return hits
        points = self.index.points
        forced = (["10.6"] if "10.6" in points else []) + sorted(
            point for point in points if point.startswith("MTX.")
        )
        result = list(hits)
        present = {hit.point for hit in result}
        for point in forced:
            if point in present or self.index.point_chunk(point)["access_level"] > max_access:
                continue
            if len(result) >= limit:
                if point == "10.6":
                    removable = next((i for i in range(len(result) - 1, -1, -1)
                                      if result[i].point != "10.6"), None)
                else:
                    removable = next((i for i in range(len(result) - 1, -1, -1)
                                      if result[i].point != "10.6" and result[i].source != "anchor"), None)
                if removable is None:
                    break
                result.pop(removable)
            result.append(self._hit(point, 0.0, "anchor"))
            present.add(point)
        return result

    def _extras(self, query: str, core: list[Hit], limit: int, max_access: int) -> list[Hit]:
        """Forced anchors and related refs that are not already inside the final top-`limit` window."""
        window = {h.point for h in core[:limit]}
        rel_of = {h.point: h.relevance for h in core}
        out: list[Hit] = []
        for p in match_anchors(query, self.anchors, set(self.index.points))[:self.cfg.anchor_max]:
            if p not in window and self.index.point_chunk(p)["access_level"] <= max_access:
                out.append(self._hit(p, rel_of.get(p, 0.0), "anchor"))
        if core:
            taken = window | {h.point for h in out}
            refs = [r for r in self.index.point_chunk(core[0].point).get("refs", [])
                    if r in self.index.points and r not in taken]
            out += [self._hit(r, rel_of.get(r, 0.0), "related") for r in refs
                    if self.index.point_chunk(r)["access_level"] <= max_access][:self.cfg.related_max]
        return out

    def _compose(self, query: str, core: list[Hit], limit: int, max_access: int) -> list[Hit]:
        """Core hits + anchors + related, never exceeding `limit`; at least CORE_MIN core hits survive."""
        extras = self._extras(query, core, limit, max_access)
        extras = extras[:max(0, limit - self.cfg.core_min)]
        drop = {e.point for e in extras}
        keep = [h for h in core if h.point not in drop][:limit - len(extras)]
        anchors = [e for e in extras if e.source == "anchor"]
        related = [e for e in extras if e.source == "related"]
        return (keep[:1] + anchors + keep[1:] + related)[:limit]

    def _related(self, hits: list[Hit], limit: int) -> list[Hit]:
        """For direct lookups: append referenced points (max RELATED_MAX) if there is room."""
        have = {h.point for h in hits}
        refs = [r for r in self.index.point_chunk(hits[0].point).get("refs", [])
                if r in self.index.points and r not in have]
        room = max(0, min(self.cfg.related_max, limit - len(hits)))
        return hits + [self._hit(r, 0.0, "related") for r in refs[:room]]
