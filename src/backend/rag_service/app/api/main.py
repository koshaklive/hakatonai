"""FastAPI app: /health /ingest /search /chat /chat/stream /chunks/{id} /versions."""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.audit import Audit
from app.chat import SYSTEM, ChatService, to_api
from app.core.chunks import point_of, strip_prefix
from app.core.config import Settings
from app.core.intent import analyze_intent
from app.core.pb import PocketBase
from app.core.registry import Registry
from app.ingest import ingest_version, load_active, make_embedder
from app.search.anchors import expand_anchors, load_anchors
from app.search.hybrid import Searcher
from app.search.tokenize import stemmer_name
from app.security.auth import AuthUser, Authenticator

log = logging.getLogger("api")
PREVIEW_CHARS = 300


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = 5
    filters: dict[str, Any] | None = None


class IngestRequest(BaseModel):
    version_id: str


class ChatMsg(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[ChatMsg] = Field(default_factory=list)
    conversation_id: str | None = None


def create_app(cfg: Settings | None = None) -> FastAPI:
    cfg = cfg or Settings()
    app = FastAPI(title="DOU RAG service")
    pb = PocketBase(cfg)
    auth = Authenticator(cfg, pb)
    audit = Audit(cfg, pb)
    st: dict[str, Any] = {"embedder": None, "searcher": None, "llm": None, "chat": None, "reranker": None,
                          "warm": {"embedder": False, "llm": False, "llm_ms": None}}

    def reload() -> None:
        idx = load_active(cfg)
        if not idx:
            st["searcher"] = st["chat"] = None
            return
        anchors = expand_anchors(load_anchors(cfg.anchors_file), set(idx.points))
        cfg.anchor_max = max([cfg.anchor_max] + [a.limit or 0 for a in anchors])
        st["searcher"] = Searcher(cfg, idx, st["embedder"], st["reranker"], anchors)
        st["chat"] = ChatService(cfg, st["searcher"], st["llm"]) if st["llm"] else None

    def warm_llm() -> None:
        t = time.perf_counter()
        try:
            st["llm"].chat([{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": "Контекст:\n[п. 0] (прогрев)\nпрогрев\n\nВопрос: прогрев"}],
                           max_tokens=8, temperature=0)
            st["warm"].update(llm=True, llm_ms=int((time.perf_counter() - t) * 1000))
        except Exception as e:  # noqa: BLE001
            log.warning("llm warmup failed: %s", e)

    @app.on_event("startup")
    def _startup() -> None:
        st["embedder"] = make_embedder(cfg)
        if cfg.warmup and st["embedder"] is not None:
            try:
                st["embedder"].embed_query("прогрев")
                st["warm"]["embedder"] = True
            except Exception as e:  # noqa: BLE001
                log.warning("embedder warmup failed: %s", e)
        try:
            from llm_layer.llm import LLM
            st["llm"] = LLM()
        except Exception as e:  # noqa: BLE001
            log.warning("LLM unavailable: %s", e)
        if cfg.rerank:
            try:
                from llm_layer.embeddings import Reranker
                st["reranker"] = Reranker()
            except Exception as e:  # noqa: BLE001
                log.warning("reranker unavailable: %s", e)
        reload()
        if cfg.warmup and st["llm"]:
            threading.Thread(target=warm_llm, daemon=True).start()

    def user(authorization: str | None = Header(default=None)) -> AuthUser:
        try:
            return auth.authenticate(authorization)
        except PermissionError as e:
            raise HTTPException(401, str(e)) from e

    def searcher() -> Searcher:
        if st["searcher"] is None:
            raise HTTPException(503, "index is empty: run ingest first")
        return st["searcher"]

    def chat_svc() -> ChatService:
        if st["chat"] is None:
            raise HTTPException(503, "chat unavailable: index or LLM missing")
        return st["chat"]

    @app.get("/health")
    def health() -> dict[str, Any]:
        s = st["searcher"]
        out: dict[str, Any] = {"pocketbase": pb.ping(), "index_version": s.index.version if s else None,
                               "chunks": len(s.index.chunks) if s else 0, "stemmer": stemmer_name(),
                               "dense": bool(s and s.index.dense), "rerank": cfg.rerank, "llm": None,
                               "warm": st["warm"], "thresholds": ({"low": st["chat"].low, "high": st["chat"].high}
                                                                  if st["chat"] else None)}
        try:
            from llm_layer.llm import LLM
            out["llm"] = (st["llm"] or LLM()).health(ping=False)["ok"]
        except Exception as e:  # noqa: BLE001
            out["llm"] = f"unavailable: {type(e).__name__}"
        out["ok"] = bool(s) and out["pocketbase"]
        return out

    @app.post("/search")
    def search(req: SearchRequest, u: AuthUser = Depends(user)) -> dict[str, Any]:
        if len(req.query) > cfg.query_max_len:
            raise HTTPException(413, "query too long")
        r = searcher().search(req.query, req.top_k, u.access_level, req.filters)
        audit.event(u, "/search", req.query, points=[h.point for h in r.hits])
        return {"query": r.query, "method": r.method, "version": r.version, "max_relevance": r.max_relevance,
                "timings_ms": r.timings_ms,
                "results": [{"point": h.point, "chapter": h.chapter, "page": h.page, "version": h.version,
                             "relevance": round(h.relevance, 4), "relevance_pct": round(100 * h.relevance),
                             "source": h.source, "head": h.head,
                             "text_preview": strip_prefix(h.text)[:PREVIEW_CHARS], "scores": h.scores} for h in r.hits]}

    @app.post("/chat")
    def chat(req: ChatRequest, u: AuthUser = Depends(user)) -> dict[str, Any]:
        cid = req.conversation_id or uuid.uuid4().hex
        intent_data = analyze_intent(req.message)
        if intent_data["action"] == "reply":
            out = {
                "answer": intent_data["text"],
                "sources": [],
                "conversation_id": cid,
                "intent": intent_data["intent"],
            }
            audit.chat(u, "/chat", cid, req.message, out)
            return out

        svc = chat_svc()
        a = svc.answer(req.message, [m.model_dump() for m in req.history], max_access=u.access_level)
        out = to_api(a)
        out["conversation_id"] = cid
        out["intent"] = "rag"
        out["mode"] = intent_data.get("mode", "default")
        audit.chat(u, "/chat", cid, req.message, out)
        return out

    @app.post("/chat/stream")
    def chat_stream(req: ChatRequest, u: AuthUser = Depends(user)) -> StreamingResponse:
        svc = chat_svc()
        cid = req.conversation_id or uuid.uuid4().hex

        def sse(ev: str, data: dict[str, Any]) -> str:
            return f"event: {ev}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        def gen():  # noqa: ANN202
            final: dict[str, Any] | None = None
            try:
                for ev, data in svc.stream_events(req.message, [m.model_dump() for m in req.history], u.access_level):
                    if ev == "done":
                        data["conversation_id"] = cid
                        final = data
                    yield sse(ev, data)
            except Exception as e:  # noqa: BLE001
                log.exception("stream failed")
                yield sse("error", {"error": f"{type(e).__name__}"})
            finally:
                if final:
                    audit.chat(u, "/chat/stream", cid, req.message, final)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/chunks/{chunk_id:path}")
    def chunk(chunk_id: str, u: AuthUser = Depends(user)) -> dict[str, Any]:
        ix = searcher().index
        p = point_of(chunk_id)
        if p not in ix.points or ix.point_chunk(p)["access_level"] > u.access_level:
            raise HTTPException(404, "point not found")
        c = ix.point_chunk(p)
        audit.event(u, "/chunks", p)
        return {"point": p, "doc": c.get("doc", "instruction"), "chapter": c["chapter"], "page": c["page"],
                "page_end": ix.points[p][-1].get("page_end"), "version": c["version"],
                "effective_date": c.get("effective_date"), "refs": c.get("refs", []), "text": ix.point_text(p)}

    @app.get("/versions")
    def versions(u: AuthUser = Depends(user)) -> dict[str, Any]:
        return Registry(cfg.index_dir).read()

    @app.post("/ingest", status_code=202)
    def ingest(req: IngestRequest, bg: BackgroundTasks, x_ingest_key: str | None = Header(default=None),
               authorization: str | None = Header(default=None)) -> dict[str, str]:
        ok = bool(cfg.ingest_key and x_ingest_key == cfg.ingest_key)
        who: Any = None
        if not ok:
            try:
                who = auth.authenticate(authorization)
                ok = who.role in {"admin", "methodologist"}
            except PermissionError:
                ok = False
        if not ok:
            raise HTTPException(403, "ingest requires admin/methodologist token or X-Ingest-Key")
        audit.event(who, "/ingest", req.version_id)

        def job() -> None:
            try:
                ingest_version(cfg, req.version_id, st["embedder"])
                reload()
            except Exception:  # noqa: BLE001
                log.exception("ingest failed for %s", req.version_id)
        bg.add_task(job)
        return {"status": "accepted", "version_id": req.version_id}

    @app.post("/modules/route", status_code=501)
    def modules_route() -> dict[str, str]:
        return {"detail": "contract only (chat 3)"}

    @app.post("/modules/fill", status_code=501)
    def modules_fill() -> dict[str, str]:
        return {"detail": "contract only (chat 3)"}

    return app


app = create_app()