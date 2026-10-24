from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Iterator

import docx
from docx.oxml.ns import qn
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MARKER_RE = re.compile(r"^\s*\[(\d+)\]\s*$")
DATE_FULL = re.compile(r"«_{2,}»\s*_{3,}\s*20_{2,}\s*г\.")
DATE_DM = re.compile(r"«_{2,}»\s*_{3,}")
BLANK = re.compile(r"_{3,}")
TOKEN_RE = re.compile("|".join(x.pattern for x in (DATE_FULL, DATE_DM, BLANK)))


def load(path: Path) -> docx.document.Document:
    return docx.Document(str(path))


def run_text(r: etree._Element) -> str:
    out = []
    for ch in r:
        if ch.tag == qn("w:t"):
            out.append(ch.text or "")
        elif ch.tag == qn("w:br"):
            out.append("\n")
        elif ch.tag == qn("w:tab"):
            out.append("\t")
    return "".join(out)


def para_text(p: etree._Element) -> str:
    return "".join(run_text(r) for r in p.iter(qn("w:r")))


def rpr_xml(r: etree._Element) -> str:
    rp = r.find(qn("w:rPr"))
    return etree.tostring(rp).decode() if rp is not None else ""


def is_superscript(r: etree._Element) -> bool:
    rp = r.find(qn("w:rPr"))
    if rp is None:
        return False
    va = rp.find(qn("w:vertAlign"))
    return va is not None and va.get(qn("w:val")) == "superscript"


def is_red(r: etree._Element) -> bool:
    rp = r.find(qn("w:rPr"))
    if rp is None:
        return False
    c = rp.find(qn("w:color"))
    return c is not None and (c.get(qn("w:val")) or "").upper() == "C00000"


def is_marker_run(r: etree._Element) -> bool:
    """Красный надстрочный маркер примечания «[N]» либо красный пробел рядом с ним."""
    return is_superscript(r) and is_red(r)


def markers_in(p: etree._Element) -> list[int]:
    out = []
    for r in p.iter(qn("w:r")):
        if is_marker_run(r):
            m = MARKER_RE.match(run_text(r))
            if m:
                out.append(int(m.group(1)))
    return out


def merge_runs(p: etree._Element) -> None:
    """Склеивает соседние текстовые run'ы с одинаковым форматированием (в т.ч. «_____» + «_____»)."""
    runs = [r for r in p.findall(qn("w:r"))]
    prev: etree._Element | None = None
    for r in runs:
        simple = all(ch.tag in (qn("w:rPr"), qn("w:t")) for ch in r)
        if prev is not None and simple and prev_simple and rpr_xml(prev) == rpr_xml(r) and not is_marker_run(r):
            t_prev = prev.findall(qn("w:t"))[-1]
            t_new = r.findall(qn("w:t"))
            t_prev.text = (t_prev.text or "") + "".join(t.text or "" for t in t_new)
            t_prev.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            p.remove(r)
            continue
        prev, prev_simple = r, simple


def set_paragraph_text(p: etree._Element, text: str, keep_run: etree._Element | None = None) -> None:
    """Заменяет содержимое абзаца одним run'ом с форматированием первого содержательного run'а; '\n' → <w:br/>."""
    runs = list(p.iter(qn("w:r")))
    base = keep_run
    if base is None:
        for r in runs:
            if not is_marker_run(r) and run_text(r).strip():
                base = r
                break
    if base is None and runs:
        base = runs[0]
    rpr = copy.deepcopy(base.find(qn("w:rPr"))) if base is not None and base.find(qn("w:rPr")) is not None else None
    for r in runs:
        r.getparent().remove(r)
    new = etree.SubElement(p, qn("w:r"))
    if rpr is not None:
        new.append(rpr)
    for k, part in enumerate(text.split("\n")):
        if k:
            etree.SubElement(new, qn("w:br"))
        t = etree.SubElement(new, qn("w:t"))
        t.text = part
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def body_children(doc: docx.document.Document) -> list[etree._Element]:
    return [el for el in doc.element.body if el.tag in (qn("w:p"), qn("w:tbl"))]


def all_paragraphs(el: etree._Element) -> Iterator[etree._Element]:
    if el.tag == qn("w:p"):
        yield el
    else:
        yield from el.iter(qn("w:p"))


def table_rows(tbl: etree._Element) -> list[list[etree._Element]]:
    return [tr.findall(qn("w:tc")) for tr in tbl.findall(qn("w:tr"))]


def cell_text(tc: etree._Element) -> str:
    return "\n".join(para_text(p) for p in tc.findall(qn("w:p")))
