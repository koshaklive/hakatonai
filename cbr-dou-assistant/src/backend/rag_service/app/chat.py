"""/chat pipeline: rewrite → search → refuse WITHOUT the LLM → generate → post-check citations.

Wiring in FastAPI (main.py):  svc = ChatService(cfg, searcher, LLM());  POST /chat → svc.answer(q, history, max_access=user_level)
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import Settings
from app.search.hybrid import Hit, Searcher

log = logging.getLogger("chat")

REFUSAL = "В действующей Инструкции нет ответа на этот вопрос. Попробуйте переформулировать вопрос или уточнить тему."
SYSTEM = (
    "Ты отвечаешь на вопросы по Инструкции по документационному обеспечению управления. "
    "Используй ТОЛЬКО фрагменты из блока «Контекст». Не добавляй сведений, которых там нет. "
    "Каждое утверждение подтверждай ссылкой в квадратных скобках ровно в том виде, как она стоит в заголовке фрагмента: "
    "[п. 6.4], [п. 10.3, 10.6] для Инструкции и, например, [MTX.int.6] или [MR.4.2] для остальных документов. "
    "Ссылайся только на фрагменты из контекста. Если в контексте нет ответа, ответь ровно: «" + REFUSAL + "» "
    "Отвечай кратко, на русском языке, цифры и сроки приводи как в тексте пункта.")
REWRITE = ("Перепиши последний вопрос пользователя в самостоятельный вопрос, понятный без истории диалога. "
           "Сохрани все числа, даты и номера пунктов. Верни только текст вопроса, без пояснений.")
_BRACKET = re.compile(r"\[([^\[\]]*)\]")
_TOKEN = re.compile(r"[A-Za-z][\w.\-]*|\d+(?:\.\d+)*")


class Chat(Protocol):
    def chat(self, messages: list[dict[str, str]], **kw: Any) -> Any: ...


@dataclass
class ChatAnswer:
    answer: str
    refused: bool
    reason: str | None                # None | empty_question | below_threshold | no_valid_citation
    query: str                        # standalone query used for search
    sources: list[dict[str, Any]]      # cited points (all context points if nothing was cited / on refusal)
    llm_calls: int
    max_relevance: float = 0.0
    dropped_refs: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)   # every point that was sent to the LLM (source tag included)
    timings_ms: dict[str, int] = field(default_factory=dict)


def check_citations(answer: str, allowed: set[str]) -> tuple[str, list[str], list[str]]:
    """Cites: [п. 6.4] / [п. 10.3, 10.6] (Instruction) and [MTX.int.6] / [MR.4.2] (other documents).
    Returns (answer without unsupported cites, valid ids, dropped ids). Bare footnote markers like [1] are left alone."""
    valid: list[str] = []
    dropped: list[str] = []

    def fix(m: re.Match[str]) -> str:
        body = m.group(1).strip()
        has_p = bool(re.match(r"(п|пп|пункт\w*)\b", body, re.I))
        toks = _TOKEN.findall(re.sub(r"^(?:пп|пункт\w*|п)\.?\s*", "", body, flags=re.I))
        if not toks or not (has_p or any(not is_num_id(t) or "." in t for t in toks)):
            return m.group(0)                       # not a citation (e.g. "[1]"), leave alone
        ok = [t for t in toks if t in allowed]
        dropped.extend(t for t in toks if t not in allowed)
        valid.extend(ok)
        nums = [t for t in ok if is_num_id(t)]
        other = [f"[{t}]" for t in ok if not is_num_id(t)]
        return " ".join(([f"[п. {', '.join(nums)}]"] if nums else []) + other)

    out = _BRACKET.sub(fix, answer)
    return re.sub(r"[ \t]+([.,;])", r"\1", re.sub(r"[ \t]{2,}", " ", out)).strip(), list(dict.fromkeys(valid)), dropped


def is_num_id(pid: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)*", pid))


def build_context(hits: list[Hit]) -> str:
    parts = []
    for h in hits:
        pages = f", стр. {h.page}" + (f"–{h.page_end}" if h.page_end and h.page_end != h.page else "") if h.page else ""
        label = f"п. {h.point}" if is_num_id(h.point) else h.point
        parts.append(f"[{label}] ({h.chapter}{pages})\n{h.text}")
    return "\n\n".join(parts)


class ChatService:
    def __init__(self, cfg: Settings, searcher: Searcher, llm: Chat, strict_citations: bool | None = None) -> None:
        self.cfg, self.searcher, self.llm = cfg, searcher, llm
        self.strict = strict_citations if strict_citations is not None else os.getenv("STRICT_CITATIONS", "1") == "1"
        self.calls = 0

    def _llm(self, messages: list[dict[str, str]], **kw: Any) -> str:
        self.calls += 1
        return self.llm.chat(messages, **kw).text

    def rewrite(self, question: str, history: list[dict[str, str]] | None) -> str:
        """Only when there is history; the first turn never costs an LLM call."""
        if not history:
            return question
        convo = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in history[-6:])
        try:
            out = self._llm([{"role": "system", "content": REWRITE},
                             {"role": "user", "content": f"{convo}\nuser: {question}"}], max_tokens=160, temperature=0)
            return out.strip().strip('"«»') or question
        except Exception as e:  # noqa: BLE001
            log.warning("rewrite failed, using the raw question: %s", e)
            return question

    def answer(self, question: str, history: list[dict[str, str]] | None = None, max_access: int = 1) -> ChatAnswer:
        t0, tm = time.perf_counter(), {}
        self.calls = 0
        question = question.strip()[:self.cfg.query_max_len]

        ctx: list[str] = []

        def done(**kw: Any) -> ChatAnswer:
            tm["total"] = int((time.perf_counter() - t0) * 1000)
            return ChatAnswer(llm_calls=self.calls, timings_ms=tm, context=ctx, **kw)

        if not question:
            return done(answer=REFUSAL, refused=True, reason="empty_question", query="", sources=[])
        q = self.rewrite(question, history)
        tm["rewrite"] = int((time.perf_counter() - t0) * 1000)

        r = self.searcher.search(q, max_access=max_access)
        tm["search"] = r.timings_ms.get("total", 0)
        ix = self.searcher.index
        src = [{"point": h.point, "doc": ix.point_chunk(h.point).get("doc", "instruction"),
                "doc_title": ix.point_chunk(h.point).get("doc_title"), "chapter": h.chapter, "page": h.page,
                "source": h.source, "relevance": round(h.relevance, 3)} for h in r.hits]

        ctx.extend(f"{h.point}[{h.source[0]}]" for h in r.hits)

        # refusal without the LLM: direct point lookups are never refused; otherwise the best CORE hit must clear the threshold
        if r.method != "direct" and (not r.hits or r.max_relevance < self.cfg.rel_threshold or r.max_relevance <= 0):
            return done(answer=REFUSAL, refused=True, reason="below_threshold", query=q, sources=src,
                        max_relevance=r.max_relevance)

        t1 = time.perf_counter()
        raw = self._llm([{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": f"Контекст:\n{build_context(r.hits)}\n\nВопрос: {q}"}])
        tm["llm"] = int((time.perf_counter() - t1) * 1000)

        allowed = {h.point for h in r.hits} | {cid.split("#", 1)[0] for h in r.hits for cid in h.chunk_ids}
        text, valid, dropped = check_citations(raw, allowed)
        if dropped:
            log.warning("dropped unsupported citations: %s", dropped)
        if REFUSAL[:30] in raw:
            return done(answer=REFUSAL, refused=True, reason="llm_refused", query=q, sources=src,
                        max_relevance=r.max_relevance, dropped_refs=dropped)
        if self.strict and not valid:
            return done(answer=REFUSAL, refused=True, reason="no_valid_citation", query=q, sources=src,
                        max_relevance=r.max_relevance, dropped_refs=dropped)
        used = set(valid)
        return done(answer=text, refused=False, reason=None, query=q, sources=[s for s in src if s["point"] in used] or src,
                    max_relevance=r.max_relevance, dropped_refs=dropped)
