"""Tokenizer for Russian official text: keeps point numbers and abbreviations, stems the rest."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable

_TOKEN = re.compile(r"\d+(?:\.\d+)+|[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё]+)*|\d+")
_NUM = re.compile(r"\d")
STOP = frozenset("""и в во на по с со к у о об от до из за для при как что это не или а но же ли бы то
 также либо если только его ее их он она они оно мы вы я быть есть который которая которые которых которое
 такой такие такая этот эти этой этих том тех так там тут где когда какой какая какие какое сколько""".split())

try:  # best quality
    import pymorphy3
    _MORPH = pymorphy3.MorphAnalyzer()
except Exception:  # noqa: BLE001
    _MORPH = None
try:
    import snowballstemmer
    _SNOW = snowballstemmer.stemmer("russian")
except Exception:  # noqa: BLE001
    _SNOW = None

_ENDINGS = sorted("""ировать ирование ированию ированием ировании ующего ующему ующий ующих ующим ующей
 ование ования ованию ованием овании ениями ениям ениях ение ения ению енией ении ости остью остей остям
 ыми ими ого его ому ему ной ная ное ные ных ным ном ую юю ая яя ое ее ые ие ых их ым им ом ем ой ей
 ами ями ах ях ов ев ам ям ою ею ия ья ию ью ии а я о е ы и у ю ь й""".split(), key=len, reverse=True)


def _fallback_stem(w: str) -> str:
    for e in _ENDINGS:
        if w.endswith(e) and len(w) - len(e) >= 3:
            return w[: -len(e)]
    return w


@lru_cache(maxsize=50000)
def stem(word: str) -> str:
    """Lemma/stem of a lowercase Russian word (pymorphy3 → snowball → suffix stripper)."""
    if not re.search(r"[а-я]", word):
        return word
    if _MORPH is not None:
        return _MORPH.parse(word)[0].normal_form
    if _SNOW is not None:
        return _SNOW.stemWord(word)
    return _fallback_stem(word)


def stemmer_name() -> str:
    """Name of the active stemming backend (for /health and eval output)."""
    return "pymorphy3" if _MORPH else "snowball" if _SNOW else "fallback-suffix"


def find_abbreviations(texts: Iterable[str], min_df: int) -> set[str]:
    """ALL-CAPS tokens (2+ letters) occurring in at least `min_df` texts → lowercase set."""
    df: dict[str, int] = {}
    for t in texts:
        for w in {m.lower().replace("ё", "е") for m in _TOKEN.findall(t)
                  if m.isupper() and len(m) >= 2 and not _NUM.search(m)}:
            df[w] = df.get(w, 0) + 1
    return {w for w, n in df.items() if n >= min_df}


def tokenize(text: str, abbrevs: frozenset[str] | set[str] = frozenset(), drop_stop: bool = True) -> list[str]:
    """Tokens: point numbers verbatim ('10.6'), abbreviations unstemmed, other words lemmatised."""
    out: list[str] = []
    for raw in _TOKEN.findall(text):
        if _NUM.search(raw):
            out.append(raw)
            continue
        low = raw.lower().replace("ё", "е")
        if (raw.isupper() and len(raw) >= 2) or low in abbrevs:
            out.append(low)
            continue
        if drop_stop and low in STOP:
            continue
        out.append(stem(low))
    return out
