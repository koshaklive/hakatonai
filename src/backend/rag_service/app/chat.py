"""/chat pipeline: clarify(rules) → rewrite → search → refuse/gray-zone WITHOUT the LLM → generate → citation post-check."""
from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Protocol

from app.clarify import clarify_by_rules, detect_doc_type
from app.core.chunks import strip_prefix
from app.core.config import Settings
from app.core.intent import analyze_intent
from app.core.search import normalize_query, passes_hybrid_filter, query_evidence
from app.search.hybrid import Hit, Searcher

log = logging.getLogger("chat")

REFUSAL = "В действующей Инструкции нет ответа на этот вопрос. Попробуйте переформулировать вопрос или уточнить тему."
GRAY_NOTE = ("⚠ Найденные фрагменты лишь частично соответствуют вопросу: ответ может быть неполным, "
             "проверьте указанные пункты.\n\n")
SYSTEM = (Path(__file__).resolve().parents[1] / "llm_layer" / "prompts" / "rag_answer.md").read_text(
    encoding="utf-8"
).strip()
DETERMINISTIC_RESPONSES = {
    "smalltalk": [
        "Здравствуйте! Задайте вопрос о сроке, согласовании или оформлении документа.",
        "Здравствуйте! Чем могу помочь по Инструкции? Напишите, какой документ или пункт вас интересует.",
        "Постараюсь помочь с вопросами по Инструкции. Уточните нужный документ или процедуру.",
    ],
    "emotion": [
        "Жаль, что вам сейчас тяжело. Если на душе тяжело, поговорите с близкими или руководителем; по работе помогу — уточните, какой документ нужен.",
        "Понимаю, что ситуация может расстраивать. Если на душе тяжело, поговорите с близкими или руководителем; я помогу по работе — напишите ваш вопрос по документам.",
    ],
    "off_topic": [
        "Я не могу советовать по вопросам здоровья или денег. Могу помочь со сроками приказа, согласованием документа и регистрацией письма; выберите тему.",
        "По здоровью и личным финансам я не консультирую. Зато подскажу про оформление приказа, визирование документа и регистрацию входящего письма — с чего начнём?",
        "Не буду давать советы о здоровье или деньгах. Могу объяснить порядок согласования, регистрации или хранения документов; напишите, что нужно.",
    ],
    "out_of_domain": [
        "В Инструкции по документообороту про это нет. Лучше уточнить в Департаменте ДОУ. С документами помогу: например, подскажу, как согласовать приказ.",
        "В Инструкции по документообороту про это нет. Лучше уточнить в Департаменте ДОУ. С документами помогу: например, разберём регистрацию входящего письма.",
        "В Инструкции по документообороту про это нет. Лучше уточнить в Департаменте ДОУ. С документами помогу: например, расскажу, кто визирует распоряжение.",
    ],
    "partial_match": [
        "В базе сказано, что доверенность может быть основанием права подписи [п. 8.19.5], а печать заверяет подпись на бумажной доверенности [п. 8.23]. Порядок выдачи доверенности не описан. Хотите узнать, кто вправе подписывать документы?",
        "Инструкция упоминает доверенность как основание права подписи [п. 8.19.5] и указывает, что печать заверяет подпись на бумажной доверенности [п. 8.23]. Порядок оформления или выдачи доверенности не описан. Могу пояснить правила о праве подписи.",
    ],
    "rudeness": [
        "Постараюсь помочь по Инструкции. Напишите вопрос о сроке, согласовании или оформлении документа.",
        "Давайте вернёмся к задаче по Инструкции. Уточните, какой документ или пункт нужно разобрать.",
    ],
    "gratitude": [
        "Пожалуйста! Если появится вопрос по документам, напишите его здесь.",
        "Пожалуйста! Можете прислать следующий вопрос по Инструкции.",
    ],
}


def deterministic_response(intent_data: dict[str, Any]) -> str:
    """Return a randomized canned reply, or the legacy short-query prompt."""
    intent = intent_data.get("intent")
    if intent in DETERMINISTIC_RESPONSES:
        return random.choice(DETERMINISTIC_RESPONSES[intent])
    text = intent_data.get("text")
    if isinstance(text, str):
        return text
    raise ValueError(f"No deterministic response configured for intent: {intent!r}")


CLARIFY_ANSWER = (
    "Объясни этот ответ проще, на бытовом примере из текста фрагмента. Ничего не придумывай. "
    "В конце обязательно спроси: «Стало понятнее?»"
)


def _ensure_clarification_ending(answer: str) -> str:
    answer = answer.strip().rstrip(" \t\n\"'«»")
    if answer.lower().endswith("стало понятнее?"):
        return answer
    answer = answer.rstrip("?!。.")
    return f"{answer}\nСтало понятнее?" if answer else "Стало понятнее?"


MODE_PROMPTS = {
    "explain": "Объясни найденные пункты простыми словами без канцелярита. Строго на основе фрагментов. В самом конце ответа с новой строки напиши: «Дословно в Инструкции: п. [номера пунктов]».",
    "summarize": "Сделай краткий маркированный конспект (до 7 пунктов) на основе найденных фрагментов. Не теряй числа, сроки и ответственных лиц. Запрещено использовать информацию вне фрагментов.",
    "checklist": "Опиши алгоритм действий в виде нумерованных шагов. К каждому шагу обязательно добавляй ссылку на соответствующий пункт инструкции. Строго на основе фрагментов.",
    "compare": "Сравни запрошенные сущности на основе найденных фрагментов. Сформируй ответ в виде Markdown-таблицы (2-3 строки) с указанием пунктов-источников.",
    "frustration": "Ответь в 1–2 предложениях, без извинений. Спокойно перейди к сути вопроса или кратко уточни вид документа.",
    "default": "Ответь на вопрос пользователя, опираясь только на предоставленные фрагменты. Обязательно указывай ссылки на пункты. Запрещено придумывать информацию. Твой ответ по умолчанию должен быть не длиннее 4 предложений или 80 слов. Сначала пиши сам ответ, а затем указывай ссылки в формате [п. X.Y]. Более подробный ответ давай, только если пользователь явно об этом просит."
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
    context_text: str = ""
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
    p = Path(cfg.calibration_file)
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        return float(d["gray_low"]), float(d["gray_high"])
    thr = float(os.getenv("REL_THRESHOLD", cfg.rel_threshold or 0.574))
    return round(thr - 0.15, 4), round(thr, 4)


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

    def prepare(
        self,
        run: Run,
        question: str,
        history: list[dict[str, str]] | None,
        max_access: int,
        last_context: str = "",
    ) -> tuple[ChatAnswer | None, dict[str, Any]]:
        question = normalize_query(question.strip()[:self.cfg.query_max_len])
        if not question:
            return self._done(run, answer=REFUSAL, refused=True, reason="empty_question", query="", sources=[]), {}
        intent_data = analyze_intent(question)
        if intent_data["action"] == "reply":
            return self._done(
                run,
                answer=deterministic_response(intent_data),
                refused=False,
                reason=intent_data["intent"],
                query=question,
                sources=[],
            ), {}
        if intent_data["action"] == "clarify":
            previous_answer = next(
                (message["content"] for message in reversed(history or []) if message["role"] == "assistant"),
                "",
            )
            if not previous_answer or not last_context:
                return self._done(
                    run,
                    answer="Не вижу предыдущего ответа вместе с текстом фрагмента. Задайте вопрос по документам, и я объясню его проще.",
                    refused=False,
                    reason="clarification",
                    query=question,
                    sources=[],
                ), {}
            messages = [
                {"role": "system", "content": CLARIFY_ANSWER},
                {
                    "role": "user",
                    "content": f"Текст фрагмента:\n{last_context}\n\nПредыдущий ответ:\n{previous_answer}",
                },
            ]
            return None, {
                "action": "clarify",
                "messages": messages,
                "query": question,
                "context_text": last_context,
            }
        if intent_data.get("intent") == "frustration":
            previous_question = next((message["content"] for message in reversed(history or [])
                                      if message["role"] == "user"), "")
            if not previous_question:
                return self._done(run, answer="Уточните, пожалуйста, вид документа или вопрос по Инструкции.",
                                  refused=False, reason="frustration", query=question, sources=[]), {}
            question_for_search = previous_question
        else:
            question_for_search = question
        cl = clarify_by_rules(question, history)
        if cl:
            return self._done(run, answer=cl["question"], refused=False, reason="clarification", query=question,
                              sources=[], clarification=cl), {}
        q = self.rewrite(run, question_for_search, history)
        run.tm["rewrite"] = int((time.perf_counter() - run.t0) * 1000)
        r = self.searcher.search(q, max_access=max_access)
        run.tm["search"] = r.timings_ms.get("total", 0)
        ix = self.searcher.index
        src = [{"point": h.point, "doc": ix.point_chunk(h.point).get("doc", "instruction"), "chapter": h.chapter,
                "page": h.page, "relevance": round(h.relevance, 3), "version": h.version,
                "text_preview": strip_prefix(h.text)[:PREVIEW]} for h in r.hits]
        run.ctx.extend(f"{h.point}[{h.source[0]}]" for h in r.hits)
        direct = r.method == "direct"
        dense_score, bm25_score, keyword_overlap = query_evidence(q, r.hits, ix.abbrevs)
        gray = not direct and self.low <= r.max_relevance < self.high
        passes_filter = passes_hybrid_filter(
            dense_score,
            bm25_score,
            keyword_overlap,
            dense_min=self.cfg.dense_min_relevance,
            bm25_min=self.cfg.bm25_min_relevance,
            overlap_min=self.cfg.keyword_overlap_min,
        )
        if not direct and (not r.hits or (not passes_filter and not gray)):
            return self._done(run, answer="В базе знаний информации нет, обратитесь в Департамент ДОУ.",
                              refused=True, reason="below_threshold", query=q, sources=[],
                              max_relevance=r.max_relevance), {}
        mode = intent_data.get("mode", "default")
        sys_prompt = SYSTEM + "\n\n" + MODE_PROMPTS.get(mode, MODE_PROMPTS["default"])
        if gray:
            closest = ", ".join(hit.point for hit in r.hits[:3])
            sys_prompt += (
                " Найденные пункты могут не полностью отвечать на вопрос: сформулируй ответ по ним, "
                "обязательно добавь оговорку «возможно, неполно» и укажи 2–3 ближайших пункта: "
                f"{closest}."
            )
        if re.search(r"визир", question, re.I):
            sys_prompt += (
                " Если запрашиваемое подразделение отсутствует в извлеченном контексте Матрицы, "
                "явно укажи, что сведений о нем в базе нет."
            )
        messages = [{"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"Контекст:\n{build_context(r.hits)}\n\nВопрос: {q}"}]
        return None, {"q": q, "r": r, "src": src, "gray": gray, "messages": messages, "mode": mode}

    def finalize(self, run: Run, st: dict[str, Any], raw: str) -> ChatAnswer:
        r, q, src, gray = st["r"], st["q"], st["src"], st["gray"]
        allowed = {h.point for h in r.hits} | {cid.split("#", 1)[0] for h in r.hits for cid in h.chunk_ids}
        text, valid, dropped = check_citations(raw, allowed)
        if dropped:
            log.warning("dropped unsupported citations: %s", dropped)
        kw = dict(query=q, max_relevance=r.max_relevance, dropped_refs=dropped, gray_zone=gray,
                  context_text=build_context(r.hits))
        if REFUSAL[:30] in raw:
            return self._done(run, answer=REFUSAL, refused=True, reason="llm_refused", sources=[], **kw)
        if self.strict and not valid:
            return self._done(run, answer=REFUSAL, refused=True, reason="no_valid_citation", sources=[], **kw)
        used = set(valid)
        gray_note = "Возможно, ответ неполон; ближайшие пункты: " + ", ".join(h.point for h in r.hits[:3]) + ".\n\n" if gray else ""
        return self._done(run, answer=gray_note + text, refused=False, reason=None,
                          sources=[s for s in src if s["point"] in used] or src, **kw)

    def answer(self, question: str, history: list[dict[str, str]] | None = None, max_access: int = 0,
               last_context: str = "") -> ChatAnswer:
        run = Run()
        fin, st = self.prepare(run, question, history, max_access, last_context)
        if fin:
            return fin

        t1 = time.perf_counter()
        if st.get("action") == "clarify":
            raw = self._llm(run, st["messages"])
            answer = _ensure_clarification_ending(raw)
            run.tm["llm"] = int((time.perf_counter() - t1) * 1000)
            return self._done(
                run,
                answer=answer,
                refused=False,
                reason="clarification",
                query=st["query"],
                sources=[],
                context_text=st["context_text"],
            )

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
                      max_access: int = 1, last_context: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
        """Order: sources → delta* → done. `done` carries the final (citation-checked) response."""
        run = Run()
        fin, st = self.prepare(run, question, history, max_access, last_context)
        if fin:
            yield "sources", {"sources": []}
            yield "delta", {"text": fin.answer}
            yield "done", to_api(fin)
            return
        if st.get("action") == "clarify":
            yield "sources", {"sources": []}
            run.calls += 1
            t1 = time.perf_counter()
            parts: list[str] = []
            for delta in self.llm.chat_stream(st["messages"]):
                parts.append(delta)
                yield "delta", {"text": delta}
            run.tm["llm"] = int((time.perf_counter() - t1) * 1000)
            answer = _ensure_clarification_ending("".join(parts))
            result = self._done(
                run,
                answer=answer,
                refused=False,
                reason="clarification",
                query=st["query"],
                sources=[],
                context_text=st["context_text"],
            )
            yield "done", to_api(result)
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
        result = self.finalize(run, st, "".join(buf))
        done = to_api(result)
        done["_context_text"] = result.context_text
        yield "done", done