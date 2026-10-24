from __future__ import annotations

import re
from collections import Counter

from .common import norm_ws

RANGE_SEP = r"\s*[–—-]\s*"
NUM = r"\d+(?:\.\d+)*"
ITEM = rf"{NUM}(?:{RANGE_SEP}{NUM})?"
LIST_RE = rf"{ITEM}(?:\s*(?:,|и)\s*{ITEM})*"
PUNKT_RE = re.compile(rf"(?:\bпункт\w*|\bпп?\.)\s+({LIST_RE})", re.IGNORECASE)
CHAPTER_RE = re.compile(r"\bглав(?:а|ы|е|у|ой)\s+(\d+)\b", re.IGNORECASE)
APPX_RE = re.compile(r"\bприложени\w*\s+№\s*(\d+)\b", re.IGNORECASE)


def expand_refs(text: str) -> list[str]:
    """Достаёт внутренние ссылки и разворачивает диапазоны. Порядок сохраняется, дубли убираются."""
    out: list[str] = []

    def add(x: str) -> None:
        if x not in out:
            out.append(x)

    for m in PUNKT_RE.finditer(text):
        for part in re.split(r"\s*(?:,|\bи\b)\s*", m.group(1)):
            part = part.strip()
            if not part:
                continue
            rm = re.fullmatch(rf"({NUM}){RANGE_SEP}({NUM})", part)
            if rm:
                a, b = rm.group(1), rm.group(2)
                pa, pb = a.split("."), b.split(".")
                if len(pa) == len(pb) and pa[:-1] == pb[:-1] and int(pa[-1]) <= int(pb[-1]):
                    for k in range(int(pa[-1]), int(pb[-1]) + 1):
                        add(".".join(pa[:-1] + [str(k)]))
                else:  # диапазон с разной глубиной/префиксом — берём только концы
                    add(a)
                    add(b)
            else:
                add(part)
    for m in CHAPTER_RE.finditer(text):
        add(f"ch:{m.group(1)}")
    for m in APPX_RE.finditer(text):
        add(f"A{m.group(1)}")
    return out


STOP = set("""
который которые которых которая которое этого этой этих такие такой также если либо или при для без над под про между
через после перед должен должны должна должно может могут быть быть являются является является настоящей настоящей
настоящего настоящим настоящая иные иной иных иное иных свои своих своей своего своем которым которого которой
пределах порядке случаях случае связи части целях виде установленном установленных установленным указанных указанным
следующие следующих следующим следующей работы работе работу работник работники работников документ документы документов
документа документе документом документам организации организацию организация подразделения подразделений подразделение
подразделению подразделением инструкции инструкция инструкцией инструкцию
""".split())
ABBR_RE = re.compile(r"\b[А-ЯЁ]{2,}(?:\s[А-ЯЁ]{2,})?\b")
WORD_RE = re.compile(r"[а-яёА-ЯЁ]{5,}")


def keywords(text: str, glossary_terms: list[str], k: int = 8) -> list[str]:
    """Детерминированные ключевые слова: термины глоссария + аббревиатуры + частотные слова."""
    low = text.lower()
    out: list[str] = []
    for t in glossary_terms:
        base = re.sub(r"\s*\([^)]*\)", "", t).strip().lower()
        abbr = re.findall(r"\(([^)]+)\)", t)
        if len(base) > 4 and base in low and base not in out:
            out.append(base)
        for a in abbr:
            if re.search(rf"\b{re.escape(a)}\b", text) and a not in out:
                out.append(a)
    for a in ABBR_RE.findall(text):
        if a not in out and a not in {"ПРИКАЗЫВАЮ", "ОБЯЗЫВАЮ"}:
            out.append(a)
    cnt: Counter[str] = Counter()
    surface: dict[str, str] = {}
    for w in WORD_RE.findall(low):
        if w in STOP:
            continue
        stem = w[:6]
        cnt[stem] += 1
        surface.setdefault(stem, w)
    for stem, c in cnt.most_common(30):
        if c >= 2 and surface[stem] not in out:
            out.append(surface[stem])
    return out[:k]


def prefix(chapter: str, ids: list[str]) -> str:
    return f"{chapter} > п. {ids[-1]}"


__all__ = ["expand_refs", "keywords", "prefix", "norm_ws"]
