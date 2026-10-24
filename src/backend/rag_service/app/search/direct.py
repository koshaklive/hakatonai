"""Direct point lookup: 'что в п. 10.6', 'пункт 6.4' → exact chunk, no vector search."""
from __future__ import annotations

import re

_REF = re.compile(r"\bп(?:п|ункт\w*)?\.?\s*(\d[\d.,\s–\-и]{0,40})", re.I)
_NUM = re.compile(r"\d+(?:\.\d+){0,3}")
_BARE = re.compile(r"^\s*(\d+(?:\.\d+){1,3})\s*[?.!]?\s*$")
_APPX = re.compile(r"приложени\w*\s*(?:№|N|no\.?)?\s*(\d+)", re.I)


def extract_points(query: str) -> list[str]:
    """Point numbers explicitly named in the query, in order of appearance."""
    found = [n for m in _REF.finditer(query) for n in _NUM.findall(m.group(1))]
    m = _BARE.match(query)
    if m:
        found.append(m.group(1))
    found += [f"A{m.group(1)}" for m in _APPX.finditer(query)]
    return list(dict.fromkeys(found))
