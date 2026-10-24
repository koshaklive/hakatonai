"""/chat pipeline: clarify(rules) → rewrite → search → refuse/gray-zone WITHOUT the LLM → generate → citation post-check."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Protocol

from app.clarify import clarify_by_rules, detect_doc_type
from app.core.chunks import strip_prefix
from app.core.config import Settings
from app.core.intent import analyze_intent
from app.search.hybrid import Hit, Searcher

log = logging.getLogger("chat")

REFUSAL = "В действующей Инструкции нет ответа на этот вопрос. Попробуйте переформулировать вопрос или уточнить тему."
GRAY_NOTE = ("⚠ Найденные фрагменты лишь частично соответствуют вопросу: ответ может быть неполным, "
             "проверьте указанные пункты.\n\n")
SYSTEM = (
    "Ты отвечаешь на вопросы по Инструкции по документационному обеспечению управления. "
    "Используй ТОЛЬКО фрагменты из блока «Контекст». Не добавляй сведений, которых там нет. "
    "Каждое утверждение подтверждай ссылкой в квадратных скобках ровно в том виде, как она стоит в заголовке фрагмента: "
    "[п. 6.4], [п. 10.3, 10.6] для Инструкции и, например, [MTX.int.6] или [MR.4.2] для остальных документов. "
    "Ссылайся только на фрагменты из контекста. Если в контексте нет ответа, ответь ровно: «" + REFUSAL + "» "
    "Отвечай кратко, на русском языке, цифры и сроки приводи как в тексте пункта.")
MODE_PROMPTS = {
    "explain": "Объясни найденные пункты простыми словами без канцелярита. Строго на основе фрагментов. В самом конце ответа с новой строки напиши: «Дословно в Инструкции: п. [номера пунктов]».",
    "summarize": "Сделай краткий маркированный конспект (до 7 пунктов) на основе найденных фрагментов. Не теряй числа, сроки и ответственных лиц. Запрещено использовать информацию вне фрагментов.",
    "checklist": "Опиши алгоритм действий в виде нумерованных шагов. К каждому шагу обязательно добавляй ссылку на соответствующий пункт инструкции. Строго на основе фрагментов.",
    "compare": "Сравни запрошенные сущности на основе найденных фрагментов. Сформируй ответ в виде Markdown-таблицы (2-3 строки) с указанием пунктов-источников.",
    "default": "Ответь на вопрос пользователя, опираясь только на предоставленные фрагменты. Обязательно указывай ссылки на пункты. Запрещено придумывать информацию."
}
REWRITE = ("Перепиши последний вопрос пользователя в самостоятельный вопрос, понятный без истории диалога. "
           "Сохрани все числа, даты и номера пунктов. Верни только текст вопроса, без пояснений.")
CLARIFY_SYS = ("Определи, можно ли однозначно ответить на вопрос по Инструкции по ДОУ без уточнения "
               "(вид документа, внутренний/внешний документ, подразделение). Если нельзя — need_clarification=true и "
               "один короткий уточняющий вопрос в поле question, иначе need_clarification=false и question=\"\".")
CLARIFY_SCHEMA = {"type": "object", "properties": {"need_clarification": {"type": "boolean"}, "question": {"type": "string"}},
                  "required": ["need_clarification", "question"], "additionalProperties": False}
_BRACKET = re.compile(r"\[([^\[\]]*)\]")
_TOKEN = re.compile(r"[A-Za-z][\w.\-]*|\d+(?:\.\d+)*")
PREVIEW = 300


class Chat(Protocol):
    def chat(self, messages: list[dict[str, str]], **kw: Any) -> Any: ...


@dataclass
class ChatAnswer:
    answer: str
    refused: bool
    reason: str | None
    query: str
    sources: list[dict[str, Any]]
    llm_calls: int
    max_relevance: float = 0.0
    dropped_refs: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)
    timings_ms: dict[str, int] = field(default_factory=dict)
    clarification: dict[str, Any] | None = None
    gray_zone: bool = False


class Run:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.calls = 0
        self.tm: dict[str, int] = {}
        self.ctx: list[str] = []


def to_api(a: ChatAnswer) -> dict[str, Any]:
    no_answer = a.refused
    srcs = [] if no_answer or a.clarification else [
        {k: s.get(k) for k in ("point", "doc", "chapter", "page", "relevance", "version", "text_preview")} for s in a.sources]
    return {"answer": a.answer, "sources": srcs, "no_answer": no_answer, "clarification": a.clarification,
            "query_used": a.query, "latency_ms": a.timings_ms.get("total", 0), "gray_zone": a.gray_zone}


def load_calibration(cfg: Settings) -> tuple[float, float]:
    low = high = cfg.rel_threshold
    p = Path(cfg.calibration_file)
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        low, high = float(d["gray_low"]), float(d["gray_high"])
    return low, high


def check_citations(answer: str, allowed: set[str]) -> tuple[str, list[str], list[str]]:
    valid: list[str] = []
    dropped: list[str] = []

    def fix(m: re.Match[str]) -> str:
        body = m.group(1).strip()
        has_p = bool(re.match(r"(п|пп|пункт\w*)\b", body, re.I))
        toks = _TOKEN.findall(re.sub(r"^(?:пп|пункт\w*|п)\.?\s*", "", body, flags=re.I))
        if not toks or not (has_p or any(not is_num_id(t) or "." in t for t in toks)):
            return m.group(0)
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
    def __init__(self, cfg: Settings, searcher: Searcher, llm: Any, strict_citations: bool | None = None) -> None:
        self.cfg, self.searcher, self.llm = cfg, searcher, llm
        self.strict = strict_citations if strict_citations is not None else os.getenv("STRICT_CITATIONS", "1") == "1"
        self.low, self.high = load_calibration(cfg)

    def _llm(self, run: Run, messages: list[dict[str, str]], **kw: Any) -> str:
        run.calls += 1
        return self.llm.chat(messages, **kw).text

    def _done(self, run: Run, **kw: Any) -> ChatAnswer:
        run.tm["total"] = int((time.perf_counter() - run.t0) * 1000)
        return ChatAnswer(llm_calls=run.calls, timings_ms=run.tm, context=run.ctx, **kw)

    def rewrite(self, run: Run, question: str, history: list[dict[str, str]] | None) -> str:
        if not history:
            return question
        convo = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in history[-6:])
        try:
            out = self._llm(run, [{"role": "system", "content": REWRITE},
                                  {"role": "user", "content": f"{convo}\nuser: {question}"}], max_tokens=160, temperature=0)
            return out.strip().strip('"«»') or question
        except Exception as e:  # noqa: BLE001
            log.warning("rewrite failed: %s", e)
            return question

    def clarify_llm(self, run: Run, q: str, hits: list[Hit]) -> dict[str, Any] | None:
        try:
            run.calls += 1
            heads = "\n".join(f"п. {h.point}: {strip_prefix(h.text)[:160]}" for h in hits[:3])
            d = self.llm.chat_json([{"role": "system", "content": CLARIFY_SYS},
                                    {"role": "user", "content": f"Вопрос: {q}\nНайденные фрагменты:\n{heads}"}],
                                   CLARIFY_SCHEMA, name="clarify", max_tokens=120, temperature=0)
            if d["need_clarification"] and d["question"].strip():
                return {"reason": "llm_doubt", "intent": None, "question": d["question"].strip(), "options": []}
        except Exception as e:  # noqa: BLE001
            log.warning("clarify llm failed: %s", e)
        return None

    def prepare(self, run: Run, question: str, history: list[dict[str, str]] | None, max_access: int
                ) -> tuple[ChatAnswer | None, dict[str, Any]]:
        question = question.strip()[:self.cfg.query_max_len]
        if not question:
            return self._done(run, answer=REFUSAL, refused=True, reason="empty_question", query="", sources=[]), {}
        cl = clarify_by_rules(question, history)
        if cl:
            return self._done(run, answer=cl["question"], refused=False, reason="clarification", query=question,
                              sources=[], clarification=cl), {}
        q = self.rewrite(run, question, history)
        run.tm["rewrite"] = int((time.perf_counter() - run.t0) * 1000)
        r = self.searcher.search(q, max_access=max_access)
        run.tm["search"] = r.timings_ms.get("total", 0)
        ix = self.searcher.index
        src = [{"point": h.point, "doc": ix.point_chunk(h.point).get("doc", "instruction"), "chapter": h.chapter,
                "page": h.page, "relevance": round(h.relevance, 3), "version": h.version,
                "text_preview": strip_prefix(h.text)[:PREVIEW]} for h in r.hits]
        run.ctx.extend(f"{h.point}[{h.source[0]}]" for h in r.hits)
        direct = r.method == "direct"
        if not direct and (not r.hits or r.max_relevance < self.low or r.max_relevance <= 0):
            return self._done(run, answer="В базе знаний информации нет, обратитесь в Департамент ДОУ.",
                              refused=True, reason="below_threshold", query=q, sources=[],
                              max_relevance=r.max_relevance), {}
        gray = not direct and r.max_relevance < self.high
        if gray:
            closest = [h.point for h in r.hits[:3] if h.point]
            pts = ", ".join(closest)
            ans = f"Точного ответа не нашёл. Возможно, вам подойдут пункты: {pts}. Пожалуйста, уточните запрос."
            return self._done(run, answer=ans, refused=True, reason="gray_zone", query=q, sources=src[:3],
                              max_relevance=r.max_relevance), {}
        intent_data = analyze_intent(question)
        mode = intent_data.get("mode", "default")
        sys_prompt = MODE_PROMPTS.get(mode, MODE_PROMPTS["default"])
        messages = [{"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"Контекст:\n{build_context(r.hits)}\n\nВопрос: {q}"}]
        return None, {"q": q, "r": r, "src": src, "gray": gray, "messages": messages, "mode": mode}

    def finalize(self, run: Run, st: dict[str, Any], raw: str) -> ChatAnswer:
        r, q, src, gray = st["r"], st["q"], st["src"], st["gray"]
        allowed = {h.point for h in r.hits} | {cid.split("#", 1)[0] for h in r.hits for cid in h.chunk_ids}
        text, valid, dropped = check_citations(raw, allowed)
        if dropped:
            log.warning("dropped unsupported citations: %s", dropped)
        kw = dict(query=q, max_relevance=r.max_relevance, dropped_refs=dropped, gray_zone=gray)
        if REFUSAL[:30] in raw:
            return self._done(run, answer=REFUSAL, refused=True, reason="llm_refused", sources=[], **kw)
        if self.strict and not valid:
            return self._done(run, answer=REFUSAL, refused=True, reason="no_valid_citation", sources=[], **kw)
        used = set(valid)
        return self._done(run, answer=(GRAY_NOTE if gray else "") + text, refused=False, reason=None,
                          sources=[s for s in src if s["point"] in used] or src, **kw)

    def answer(self, question: str, history: list[dict[str, str]] | None = None, max_access: int = 0) -> ChatAnswer:
        run = Run()
        fin, st = self.prepare(run, question, history, max_access)
        if fin:
            return fin

        t1 = time.perf_counter()

        mode = st.get("mode", "default")
        r = st.get("r")

        if mode == "summarize" and r and len(r.hits) > 5:
            chunks = [r.hits[i:i+5] for i in range(0, len(r.hits), 5)]
            part_summaries = []
            for chunk in chunks:
                chunk_ctx = build_context(chunk)
                msg = [{"role": "system", "content": "Сделай краткую выжимку фактов из фрагментов, строго сохраняя все числа, сроки и ответственных. Ничего не придумывай."},
                       {"role": "user", "content": f"Контекст:\n{chunk_ctx}\n\nВопрос: {st['q']}"}]
                part_summaries.append(self._llm(run, msg))

            combined_ctx = "\n\n".join(part_summaries)
            final_msg = [{"role": "system", "content": st["messages"][0]["content"]},
                         {"role": "user", "content": f"Объедини эти промежуточные выжимки в финальный конспект.\n\nЧасти:\n{combined_ctx}\n\nВопрос: {st['q']}"}]
            raw = self._llm(run, final_msg)
        else:
            raw = self._llm(run, st["messages"])

        run.tm["llm"] = int((time.perf_counter() - t1) * 1000)
        return self.finalize(run, st, raw)

    def stream_events(self, question: str, history: list[dict[str, str]] | None = None,
                      max_access: int = 1) -> Iterator[tuple[str, dict[str, Any]]]:
        """Order: sources → delta* → done. `done` carries the final (citation-checked) response."""
        run = Run()
        fin, st = self.prepare(run, question, history, max_access)
        if fin:
            yield "sources", {"sources": []}
            yield "delta", {"text": fin.answer}
            yield "done", to_api(fin)
            return
        yield "sources", {"sources": [{k: s[k] for k in ("point", "doc", "chapter", "page", "relevance", "version", "text_preview")}
                                      for s in st["src"]], "query_used": st["q"]}
        if st["gray"]:
            yield "delta", {"text": GRAY_NOTE}
        run.calls += 1
        t1 = time.perf_counter()
        buf: list[str] = []
        for d in self.llm.chat_stream(st["messages"]):
            buf.append(d)
            yield "delta", {"text": d}
        run.tm["llm"] = int((time.perf_counter() - t1) * 1000)
        yield "done", to_api(self.finalize(run, st, "".join(buf)))