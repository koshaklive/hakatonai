"""Rule-based clarification (no LLM): deadline/visa questions need a document kind."""
from __future__ import annotations

import re
from typing import Any

DOC_TYPES = [
    ("приказ", r"приказ"), ("распоряжение", r"распоряжен"), ("письмо", r"письм"), ("соглашение", r"соглашен"),
    ("методические рекомендации", r"методическ\w*\s+рекомендац|методичк"),
    ("положение", r"\bположени\w*\s+(?:о|об)\b"), ("регламент", r"регламент"), ("порядок", r"\bпорядок\b|\bпорядка\b"),
    ("правила", r"\bправил\w*\b"), ("протокол", r"протокол"), ("официальное разъяснение", r"разъяснени"),
    ("модуль документа", r"модул"), ("аналитический документ / концепция", r"концепц|аналитическ"),
    ("постановление", r"постановлен"), ("записка", r"записк"),
]
_DOC_RE = [(n, re.compile(p, re.I)) for n, p in DOC_TYPES]
DEADLINE_RE = re.compile(r"срок\w*.{0,40}(рассмотр|согласован|визир)|(рассмотр|согласован|визир)\w*.{0,40}срок|за сколько.{0,30}(рассмотр|согласов|визир)", re.I)
VISA_RE = re.compile(r"\bвиз(а|ир\w*|у|ы|ой)\b|кто (согласовыва|визиру)|согласующ|матриц\w*\s+визир", re.I)
POINT_RE = re.compile(r"\bп(?:ункт\w*|п)?\.?\s*\d+(?:\.\d+)+", re.I)
ALL_RE = re.compile(r"все\w*\s+вид|по\s+видам|любо\w+\s+(?:документ|вид)|каждого\s+вида", re.I)
OPTIONS = ["приказ", "распоряжение", "письмо", "методические рекомендации", "положение / регламент / порядок / правила",
           "протокол", "иной документ"]
TEXT = {
    "deadline": "Срок рассмотрения зависит от вида документа (п. 10.3). Какой документ вы имеете в виду?",
    "visa": "Состав визирующих по Матрице обязательного визирования зависит от вида документа. Какой документ вы согласовываете?",
}


def detect_doc_type(text: str) -> str | None:
    return next((n for n, rx in _DOC_RE if rx.search(text)), None)


def clarify_by_rules(question: str, history: list[dict[str, str]] | None) -> dict[str, Any] | None:
    if POINT_RE.search(question) or ALL_RE.search(question):
        return None
    intent = "deadline" if DEADLINE_RE.search(question) else "visa" if VISA_RE.search(question) else None
    if not intent:
        return None
    past = " ".join(m["content"] for m in (history or [])[-6:] if m.get("role") == "user")
    if detect_doc_type(question) or detect_doc_type(past):
        return None
    return {"reason": "missing_doc_type", "intent": intent, "question": TEXT[intent], "options": OPTIONS}