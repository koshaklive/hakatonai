"""FastAPI app (stage 1): /health /ingest /search /chunks/{id} /versions + contract stubs for chat 3."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.chunks import point_of, strip_prefix
from app.core.config import Settings
from app.core.pb import PocketBase
from app.core.registry import Registry
from app.ingest import build_index, ingest_version, load_active, make_embedder
from app.search.anchors import load_anchors
from app.search.hybrid import Searcher
from app.search.tokenize import stemmer_name
from app.security.auth import AuthUser, Authenticator

log = logging.getLogger("api")
PREVIEW_CHARS = 300


class SearchRequest(BaseModel):
    """POST /search body (access_level is NOT accepted from the client)."""
    query: str = Field(min_length=1)
    top_k: int = 5
    filters: dict[str, Any] | None = None


class IngestRequest(BaseModel):
    """POST /ingest body."""
    version_id: str


def create_app(cfg: Settings | None = None) -> FastAPI:
    """Application factory (tests pass their own Settings)."""
    cfg = cfg or Settings()
    app = FastAPI(title="DOU RAG service")
    pb = PocketBase(cfg)
    auth = Authenticator(cfg, pb)
    st: dict[str, Any] = {"embedder": None, "searcher": None}

    def reload() -> None:
        idx = load_active(cfg)
        st["searcher"] = Searcher(cfg, idx, st["embedder"], None, load_anchors(cfg.anchors_file)) if idx else None

    @app.on_event("startup")
    def _startup() -> None:
        st["embedder"] = make_embedder(cfg)
        if cfg.rerank:
            try:
                from llm_layer.embeddings import Reranker
                st["reranker"] = Reranker()
            except Exception as e:  # noqa: BLE001
                log.warning("reranker unavailable: %s", e)
        reload()
        if st["searcher"] and st.get("reranker"):
            st["searcher"].reranker = st["reranker"]

    def user(authorization: str | None = Header(default=None)) -> AuthUser:
        try:
            return auth.authenticate(authorization)
        except PermissionError as e:
            raise HTTPException(401, str(e)) from e

    def searcher() -> Searcher:
        if st["searcher"] is None:
            raise HTTPException(503, "index is empty: run ingest first")
        return st["searcher"]

    @app.get("/health")
    def health() -> dict[str, Any]:
        s = st["searcher"]
        out: dict[str, Any] = {"pocketbase": pb.ping(), "index_version": s.index.version if s else None,
                               "chunks": len(s.index.chunks) if s else 0, "stemmer": stemmer_name(),
                               "dense": bool(s and s.index.dense), "rerank": cfg.rerank, "llm": None}
        try:
            from llm_layer.llm import LLM
            out["llm"] = LLM().health(ping=False)["ok"]
        except Exception as e:  # noqa: BLE001
            out["llm"] = f"unavailable: {type(e).__name__}"
        out["ok"] = bool(s) and out["pocketbase"]
        return out

    @app.post("/search")
    def search(req: SearchRequest, u: AuthUser = Depends(user)) -> dict[str, Any]:
        if len(req.query) > cfg.query_max_len:
            raise HTTPException(413, "query too long")
        r = searcher().search(req.query, req.top_k, u.access_level, req.filters)
        return {"query": r.query, "method": r.method, "version": r.version, "max_relevance": r.max_relevance,
                "timings_ms": r.timings_ms,
                "results": [{"point": h.point, "chapter": h.chapter, "page": h.page, "version": h.version,
                             "relevance": round(h.relevance, 4), "relevance_pct": round(100 * h.relevance),
                             "source": h.source, "head": h.head,
                             "text_preview": strip_prefix(h.text)[:PREVIEW_CHARS], "scores": h.scores} for h in r.hits]}

    @app.get("/chunks/{chunk_id:path}")
    def chunk(chunk_id: str, u: AuthUser = Depends(user)) -> dict[str, Any]:
        ix = searcher().index
        p = point_of(chunk_id)
        if p not in ix.points or ix.point_chunk(p)["access_level"] > u.access_level:
            raise HTTPException(404, "point not found")
        c = ix.point_chunk(p)
        return {"point": p, "chapter": c["chapter"], "page": c["page"], "page_end": ix.points[p][-1].get("page_end"),
                "version": c["version"], "effective_date": c.get("effective_date"), "refs": c.get("refs", []),
                "text": ix.point_text(p)}

    @app.get("/versions")
    def versions(u: AuthUser = Depends(user)) -> dict[str, Any]:
        return Registry(cfg.index_dir).read()

    @app.post("/ingest", status_code=202)
    def ingest(req: IngestRequest, bg: BackgroundTasks, x_ingest_key: str | None = Header(default=None),
               authorization: str | None = Header(default=None)) -> dict[str, str]:
        ok = bool(cfg.ingest_key and x_ingest_key == cfg.ingest_key)
        if not ok:
            try:
                ok = auth.authenticate(authorization).role in {"admin", "methodologist"}
            except PermissionError:
                ok = False
        if not ok:
            raise HTTPException(403, "ingest requires admin/methodologist token or X-Ingest-Key")

        def job() -> None:
            try:
                ingest_version(cfg, req.version_id, st["embedder"])
                reload()
            except Exception:  # noqa: BLE001
                log.exception("ingest failed for %s", req.version_id)
        bg.add_task(job)  # PocketBase hook has a 10 s timeout, embedding takes longer → async
        return {"status": "accepted", "version_id": req.version_id}

    @app.post("/modules/route", status_code=501)
    def modules_route() -> dict[str, str]:
        return {"detail": "contract only (chat 3)"}

    @app.post("/modules/fill", status_code=501)
    def modules_fill() -> dict[str, str]:
        return {"detail": "contract only (chat 3)"}

    return app


app = create_app()
