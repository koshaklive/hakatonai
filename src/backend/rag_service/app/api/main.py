"""FastAPI app: /health /ingest /search /chat /chat/stream /chunks/{id} /versions."""
from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.audit import Audit
from app.chat import SYSTEM, ChatService, load_calibration, to_api
from app.core.chunks import point_of, strip_prefix
from app.core.config import Settings
from app.core.chunks import load_chunks, slug
from app.core.docx_chunks import docx_to_chunks
from app.core.intent import analyze_intent
from app.core.validator import check_draft_file, validate_kb_file
from app.core.pb import PocketBase
from app.core.registry import Registry
from app.ingest import build_index, ingest_version, load_active, load_index, make_embedder
from app.search.anchors import expand_anchors, load_anchors
from app.search.hybrid import Searcher
from app.search.tokenize import stemmer_name
from app.security.auth import AuthUser, Authenticator

log = logging.getLogger("api")
PREVIEW_CHARS = 300
SESSIONS: dict[str, dict[str, Any]] = {}


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


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
    app = FastAPI(title="DOU RAG service", default_response_class=UTF8JSONResponse)

    @app.middleware("http")
    async def ensure_json_charset(request, call_next):
        response = await call_next(request)
        if response.headers.get("content-type", "").startswith("application/json"):
            response.headers["content-type"] = "application/json; charset=utf-8"
        return response

    pb = PocketBase(cfg)
    auth = Authenticator(cfg, pb)
    audit = Audit(cfg, pb)
    st: dict[str, Any] = {"embedder": None, "runtime": None, "llm": None, "reranker": None,
                          "warm": {"embedder": False, "llm": False, "llm_ms": None}}
    ingest_lock = threading.Lock()

    def make_runtime(idx: Any) -> dict[str, Any]:
        anchors = expand_anchors(load_anchors(cfg.anchors_file), set(idx.points))
        cfg.anchor_max = max([cfg.anchor_max] + [a.limit or 0 for a in anchors])
        search = Searcher(cfg, idx, st["embedder"], st["reranker"], anchors)
        chat = ChatService(cfg, search, st["llm"]) if st["llm"] else None
        return {"searcher": search, "chat": chat}

    def reload() -> None:
        idx = load_active(cfg)
        if not idx:
            st["runtime"] = None
            return
        st["runtime"] = make_runtime(idx)

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
        runtime = st["runtime"]
        if runtime is None:
            raise HTTPException(503, "index is empty: run ingest first")
        return runtime["searcher"]

    def chat_svc() -> ChatService:
        runtime = st["runtime"]
        if runtime is None or runtime["chat"] is None:
            raise HTTPException(503, "chat unavailable: index or LLM missing")
        return runtime["chat"]

    @app.get("/health", response_class=UTF8JSONResponse)
    def health() -> dict[str, Any]:
        runtime = st["runtime"]
        s = runtime["searcher"] if runtime else None
        chat_instance = runtime["chat"] if runtime else None
        low, high = ((chat_instance.low, chat_instance.high) if chat_instance else load_calibration(cfg))
        out: dict[str, Any] = {"pocketbase": pb.ping(),
                               "index_version": (s.index.version if s and s.index.version else "ОД-184"),
                               "chunks": len(s.index.chunks) if s else 0, "stemmer": stemmer_name(),
                               "dense": bool(s and s.index.dense), "rerank": cfg.rerank, "llm": None,
                               "warm": st["warm"], "thresholds": {"low": low, "high": high}}
        try:
            from llm_layer.llm import LLM
            out["llm"] = (st["llm"] or LLM()).health(ping=False)["ok"]
        except Exception as e:  # noqa: BLE001
            out["llm"] = f"unavailable: {type(e).__name__}"
        out["ok"] = bool(s) and out["pocketbase"]
        return out

    @app.post("/search", response_class=UTF8JSONResponse)
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

    @app.post("/kb/validate", response_class=UTF8JSONResponse)
    async def validate_kb(file: UploadFile = File(...)) -> list[dict[str, str]]:
        try:
            return validate_kb_file(await file.read(), file.filename or "upload.docx")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/check/draft", response_class=UTF8JSONResponse)
    async def check_draft(file: UploadFile = File(...)) -> list[dict[str, str]]:
        try:
            return check_draft_file(await file.read())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/chat", response_class=UTF8JSONResponse)
    def chat(req: ChatRequest, u: AuthUser = Depends(user)) -> dict[str, Any]:
        cid = req.conversation_id or uuid.uuid4().hex
        session_data = SESSIONS.get(cid, {
            "history": [message.model_dump() for message in req.history][-6:],
            "last_context": "",
            "last_sources": [],
        })
        intent_data = analyze_intent(req.message)

        def finish(out: dict[str, Any]) -> dict[str, Any]:
            session_data["history"].extend([
                {"role": "user", "content": req.message},
                {"role": "assistant", "content": out["answer"]},
            ])
            session_data["history"] = session_data["history"][-6:]
            SESSIONS[cid] = session_data
            audit.chat(u, "/chat", cid, req.message, out)
            return out

        if intent_data["action"] == "reply":
            out = {
                "answer": intent_data["text"],
                "sources": [],
                "conversation_id": cid,
                "intent": intent_data["intent"],
                "no_answer": False,
                "clarification": None,
                "query_used": req.message,
                "latency_ms": 0,
                "gray_zone": False,
            }
            return finish(out)

        if intent_data["action"] == "reformulate":
            previous_answer = next(
                (message["content"] for message in reversed(session_data["history"])
                 if message["role"] == "assistant"),
                None,
            )
            last_context = session_data.get("last_context", "")
            if not previous_answer or not last_context:
                out = {
                    "answer": "Пока нечего переформулировать. Сначала задайте вопрос по документам.",
                    "sources": [],
                    "conversation_id": cid,
                    "intent": "reformulate",
                    "no_answer": False,
                    "clarification": None,
                    "query_used": req.message,
                    "latency_ms": 0,
                    "gray_zone": False,
                }
                return finish(out)

            svc = chat_svc()
            started = time.perf_counter()
            reformulated = svc.llm.chat([
                {
                    "role": "system",
                    "content": (f"Перепиши предыдущий ответ. Сделай его {req.message}, строго опираясь на те же "
                               "фрагменты. Сохрани все числа, сроки и ссылки. Не добавляй новых фактов."),
                },
                {
                    "role": "user",
                    "content": f"Фрагменты:\n{last_context}\n\nПредыдущий ответ:\n{previous_answer}",
                },
            ]).text.strip()
            out = {
                "answer": reformulated,
                "sources": session_data.get("last_sources", []),
                "conversation_id": cid,
                "intent": "reformulate",
                "no_answer": False,
                "clarification": None,
                "query_used": req.message,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "gray_zone": False,
            }
            return finish(out)

        svc = chat_svc()
        a = svc.answer(req.message, history=session_data["history"], max_access=u.access_level)
        out = to_api(a)
        out["conversation_id"] = cid
        out["intent"] = "rag"
        out["mode"] = intent_data.get("mode", "default")
        if not a.refused and a.context_text:
            session_data["last_context"] = a.context_text
            session_data["last_sources"] = out["sources"]
        return finish(out)

    @app.post("/chat/stream")
    def chat_stream(req: ChatRequest, u: AuthUser = Depends(user)) -> StreamingResponse:
        svc = chat_svc()
        cid = req.conversation_id or uuid.uuid4().hex
        session_data = SESSIONS.get(cid, {
            "history": [message.model_dump() for message in req.history][-6:],
            "last_context": "",
            "last_sources": [],
        })

        def sse(ev: str, data: dict[str, Any]) -> str:
            return f"event: {ev}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        def gen():  # noqa: ANN202
            final: dict[str, Any] | None = None
            try:
                for ev, data in svc.stream_events(req.message, session_data["history"], u.access_level):
                    if ev == "done":
                        data["conversation_id"] = cid
                        final = data
                    yield sse(ev, data)
            except Exception as e:  # noqa: BLE001
                log.exception("stream failed")
                yield sse("error", {"error": f"{type(e).__name__}"})
            finally:
                if final:
                    session_data["history"].extend([
                        {"role": "user", "content": req.message},
                        {"role": "assistant", "content": final["answer"]},
                    ])
                    session_data["history"] = session_data["history"][-6:]
                    SESSIONS[cid] = session_data
                    audit.chat(u, "/chat/stream", cid, req.message, final)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/chunks/{chunk_id:path}", response_class=UTF8JSONResponse)
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

    @app.get("/versions", response_class=UTF8JSONResponse)
    def versions(u: AuthUser = Depends(user)) -> dict[str, Any]:
        return Registry(cfg.index_dir).read()

    @app.post("/ingest/{version_id}", response_class=UTF8JSONResponse)
    def ingest_document_version(version_id: str, x_ingest_key: str | None = Header(default=None),
                                authorization: str | None = Header(default=None)) -> dict[str, Any]:
        ok = bool(cfg.ingest_key and x_ingest_key == cfg.ingest_key)
        if not ok:
            try:
                who = auth.authenticate(authorization)
                ok = who.role in {"admin", "methodologist"}
            except PermissionError:
                ok = False
        if not ok:
            raise HTTPException(403, "ingest requires admin/methodologist token or X-Ingest-Key")

        try:
            with ingest_lock:
                record = pb.get("document_versions", version_id)
                pb.patch("document_versions", version_id, {"status": "indexing", "comment": ""})
                filename = record.get("file")
                if isinstance(filename, list):
                    filename = filename[0] if filename else None
                if not isinstance(filename, str) or not filename.strip():
                    raise ValueError("document version has no attached DOCX file")
                file_bytes = pb.download(record, "file")
                label = str(record.get("version_label") or "").strip()
                if not label:
                    raise ValueError("document version has no version_label")

                try:
                    findings = validate_kb_file(file_bytes, filename)
                except ValueError as exc:
                    findings = [{
                        "severity": "error",
                        "location": filename,
                        "quote": "",
                        "problem": str(exc),
                        "ref_point": "DOCX",
                    }]
                critical = [finding for finding in findings if finding["severity"] == "error"]
                if critical:
                    report_text = json.dumps(findings, ensure_ascii=False, indent=2)
                    pb.patch("document_versions", version_id, {
                        "status": "failed",
                        "comment": report_text[:1000],
                    })
                    raise HTTPException(status_code=422, detail={"validation": findings})

                if cfg.dense_enabled and st["embedder"] is None:
                    raise RuntimeError("dense indexing is enabled but the embedder is unavailable")
                with tempfile.TemporaryDirectory() as directory:
                    docx_path = Path(directory) / Path(filename).name
                    docx_path.write_bytes(file_bytes)
                    new_chunks, warnings, _ = docx_to_chunks(docx_path, label)

                access_level = int(record.get("access_level", 1))
                for chunk in new_chunks:
                    chunk["access_level"] = access_level
                    chunk["effective_date"] = record.get("effective_date") or None

                runtime = st["runtime"]
                if runtime is not None:
                    existing_chunks = runtime["searcher"].index.chunks
                else:
                    existing_chunks = load_chunks(cfg.data_file)
                existing_chunks = [
                    dict(chunk, version=label)
                    for chunk in existing_chunks
                    if Path(str(chunk.get("source_file", ""))).name != Path(filename).name
                ]
                corpus = [*existing_chunks, *new_chunks]
                index_name = f"{slug(label)}_{uuid.uuid4().hex[:12]}"
                report = build_index(cfg, corpus, st["embedder"], index_name=index_name,
                                     activate=False, build_qdrant=False)
                new_index = load_index(cfg, index_name, prefer_numpy=True)
                new_runtime = make_runtime(new_index)

                registry = Registry(cfg.index_dir)
                old_registry = registry.read()
                try:
                    registry.activate(index_name, label, report["indexed"])
                    st["runtime"] = new_runtime
                    pb.patch("document_versions", version_id, {
                        "status": "active",
                        "chunks_count": report["indexed"],
                        "comment": json.dumps(warnings, ensure_ascii=False)[:1000] if warnings else "",
                        "indexed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.000Z"),
                    })
                except Exception:
                    registry.restore(old_registry)
                    st["runtime"] = runtime
                    raise

                audit.event(None, "/ingest", version_id, points_count=report["indexed"])
                return {"status": "active", "version_id": version_id, "chunks_count": report["indexed"],
                        "index_version": new_index.version, "warnings": warnings}
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("DOCX ingest failed for %s", version_id)
            try:
                pb.patch("document_versions", version_id, {
                    "status": "failed",
                    "comment": f"{type(exc).__name__}: {exc}"[:1000],
                })
            except Exception:  # noqa: BLE001
                log.exception("failed to mark document version %s as failed", version_id)
            raise HTTPException(500, f"document ingest failed: {type(exc).__name__}") from exc

    @app.post("/ingest", status_code=202, response_class=UTF8JSONResponse)
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
                with ingest_lock:
                    ingest_version(cfg, req.version_id, st["embedder"])
                    reload()
            except Exception:  # noqa: BLE001
                log.exception("ingest failed for %s", req.version_id)
        bg.add_task(job)
        return {"status": "accepted", "version_id": req.version_id}

    @app.post("/modules/route", status_code=501, response_class=UTF8JSONResponse)
    def modules_route() -> dict[str, str]:
        return {"detail": "contract only (chat 3)"}

    @app.post("/modules/fill", status_code=501, response_class=UTF8JSONResponse)
    def modules_fill() -> dict[str, str]:
        return {"detail": "contract only (chat 3)"}

    return app


app = create_app()