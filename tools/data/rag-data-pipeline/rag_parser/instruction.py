from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber

from .common import (DEFAULT_ACCESS_LEVEL, INSTRUCTION_EFFECTIVE, INSTRUCTION_VERSION,
                     AnomalyLog, norm_ws, words)
from .textutil import expand_refs, keywords, prefix

MAX_WORDS = 350
WATERMARK_FONT = "Arial"          # диагональный гриф «УЧЕБНЫЙ ПРИМЕР…» набран Arial-Bold; текст — Times New Roman
WATERMARK_TEXT = "УЧЕБНЫЙ ПРИМЕР ДЛЯ ИТ-СОРЕВНОВАНИЙ. НЕ ЯВЛЯЕТСЯ ДЕЙСТВУЮЩИМ ДОКУМЕНТОМ"
INDENT_X = 118.0                  # красная строка (x0≈120.5); продолжение строки x0≈85.1; маркер x0≈106.5
ITEM_RE = re.compile(r"^(\d+(?:\.\d+)+)\.\s+(.*)$")
CHAPTER_RE = re.compile(r"^Глава\s+(\d+)\.\s+(.*)$")
NUMLIST_RE = re.compile(r"^\d+\)\s")
# «склейки», которые могла бы дать другая библиотека извлечения (в pdfplumber дефис на конце строки сохраняется)
GLUE_FIXES = {
    "организационнораспорядительн": "организационно-распорядительн",
    "официальноделов": "официально-делов",
    "актправопреемник": "акт-правопреемник",
}


@dataclass
class Line:
    page: int
    x0: float
    text: str
    bold: bool


@dataclass
class Block:
    """Структурный элемент внутри пункта: абзац / элемент списка."""
    kind: str                 # para | bullet | num
    text: str
    page: int
    page_end: int


@dataclass
class Item:
    id: str
    first_line: str
    page: int
    page_end: int
    blocks: list[Block] = field(default_factory=list)


def read_lines(pdf_path: Path) -> list[Line]:
    lines: list[Line] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, pg in enumerate(pdf.pages, start=1):
            f = pg.filter(lambda o: o.get("object_type") != "char" or WATERMARK_FONT not in o["fontname"])
            for l in f.extract_text_lines(return_chars=True):
                t = l["text"].strip()
                if not t:
                    continue
                bold = "Bold" in l["chars"][0]["fontname"]
                lines.append(Line(i, float(l["x0"]), t, bold))
    return lines


def join_lines(parts: list[str], log: AnomalyLog, where: str) -> str:
    """Склейка строк абзаца. Дефис на конце строки сохраняется (составное слово), факт логируется."""
    out = parts[0]
    for nxt in parts[1:]:
        if re.search(r"[А-Яа-яЁёA-Za-z]-$", out):
            log.add("hyphen_eol", where, f"{out[-25:]}⏎{nxt[:20]}",
                    "дефис на границе строк PDF сохранён, слово склеено без пробела")
            out = out + nxt
        else:
            out = out + " " + nxt
    for bad, good in GLUE_FIXES.items():
        n = out.count(bad)
        if n:
            log.add("glued_word_fixed", where, f"{bad} → {good}", f"{n} вхожд.")
            out = out.replace(bad, good)
    return out


def parse(pdf_path: Path, log: AnomalyLog) -> dict[str, Any]:
    lines = read_lines(pdf_path)
    cover = [l for l in lines if l.page == 1]
    body = [l for l in lines if l.page >= 2]

    chapters: dict[int, str] = {}
    items: list[tuple[int, Item]] = []     # (chapter_no, item)
    appendix_lines: list[Line] = []
    cur_ch = 0
    cur_item: Item | None = None
    cur_parts: list[str] = []
    cur_kind = ""
    cur_page0 = 0
    in_appendix = False
    last_line_ended = True
    i = 0

    def flush_block(page_end: int) -> None:
        nonlocal cur_parts, cur_kind
        if cur_item is not None and cur_parts:
            txt = join_lines(cur_parts, log, f"п. {cur_item.id}")
            cur_item.blocks.append(Block(cur_kind, txt, cur_page0, page_end))
            cur_item.page_end = max(cur_item.page_end, page_end)
        cur_parts, cur_kind = [], ""

    last_page = 2
    expected: dict[str, int] = {}
    while i < len(body):
        ln = body[i]
        last_page = ln.page
        if ln.text.startswith("Приложение №") and ln.bold is False and ln.page >= 50 and not in_appendix:
            flush_block(ln.page)
            in_appendix = True
        if in_appendix:
            appendix_lines.append(ln)
            i += 1
            continue
        m = CHAPTER_RE.match(ln.text)
        if m and ln.bold:
            flush_block(ln.page)
            cur_item = None
            title = ln.text
            j = i + 1
            while j < len(body) and body[j].bold and not CHAPTER_RE.match(body[j].text):
                title += " " + body[j].text
                j += 1
            cur_ch = int(m.group(1))
            chapters[cur_ch] = norm_ws(title)
            i = j
            continue
        im = ITEM_RE.match(ln.text)
        is_para_start = ln.x0 >= INDENT_X and not (cur_kind in ("bullet", "num") and not re.search(r"[;.:]$", cur_parts[-1]))
        seq_ok = False
        if im and int(im.group(1).split(".")[0]) == cur_ch:
            _nid = im.group(1)
            _par = ".".join(_nid.split(".")[:-1])
            _key = _par if "." in _par else f"ch{cur_ch}"
            seq_ok = int(_nid.split(".")[-1]) == expected.get(_key, 0) + 1 and (_par == "" or "." not in _par or _par in expected)
        if im and int(im.group(1).split(".")[0]) == cur_ch and (seq_ok or is_para_start):
            if ln.x0 < INDENT_X:
                log.add("layout", f"п. {im.group(1)}", "пункт набран без красной строки (x0=%.1f вместо ≈120.5)" % ln.x0,
                        f"стр. {ln.page}; распознан по последовательности номеров")
            flush_block(ln.page)
            nid = im.group(1)
            parent = ".".join(nid.split(".")[:-1])
            last = expected.get(parent if "." in parent else f"ch{cur_ch}", 0)
            if int(nid.split(".")[-1]) != last + 1:
                log.add("numbering_gap", f"п. {nid}", f"ожидался номер {last + 1} на уровне «{parent}»",
                        f"стр. {ln.page}")
            expected[parent if "." in parent else f"ch{cur_ch}"] = int(nid.split(".")[-1])
            expected[nid] = 0
            cur_item = Item(nid, ln.text, ln.page, ln.page)
            items.append((cur_ch, cur_item))
            cur_parts, cur_kind, cur_page0 = [im.group(2)], "para", ln.page
            i += 1
            continue
        if cur_item is None:
            i += 1
            continue
        if ln.text.startswith("•"):
            flush_block(ln.page)
            cur_parts, cur_kind, cur_page0 = [ln.text[1:].strip()], "bullet", ln.page
        elif NUMLIST_RE.match(ln.text) and ln.x0 < INDENT_X + 5:
            flush_block(ln.page)
            cur_parts, cur_kind, cur_page0 = [ln.text], "num", ln.page
        elif ln.x0 >= INDENT_X and is_para_start:
            flush_block(ln.page)
            cur_parts, cur_kind, cur_page0 = [ln.text], "para", ln.page
        else:
            cur_parts.append(ln.text)
        i += 1
    flush_block(last_page)
    return {"cover": cover, "chapters": chapters, "items": items, "appendix": appendix_lines}


def _groups(blocks: list[Block]) -> list[list[Block]]:
    """Неразрывные группы: вводная фраза + её список; «Например.» + пример."""
    groups: list[list[Block]] = []
    for b in blocks:
        if b.kind == "para":
            if groups and len(groups[-1]) == 1 and groups[-1][0].kind == "para" and groups[-1][0].text.strip() == "Например.":
                groups[-1].append(b)
            else:
                groups.append([b])
        else:
            if not groups:
                groups.append([])
            groups[-1].append(b)
    return groups


def _render(group: list[Block]) -> str:
    return "\n".join(("• " + b.text) if b.kind == "bullet" else b.text for b in group)


def pack(blocks: list[Block]) -> list[tuple[str, int, int]]:
    """Разбиение на части ≤ MAX_WORDS слов; возвращает (text, page, page_end)."""
    gs = _groups(blocks)
    total = sum(words(_render(g)) for g in gs)
    if total <= MAX_WORDS:
        return [("\n".join(_render(g) for g in gs), blocks[0].page, blocks[-1].page_end)]
    parts: list[list[list[Block]]] = [[]]
    cnt = 0
    for g in gs:
        w = words(_render(g))
        if parts[-1] and cnt + w > MAX_WORDS:
            parts.append([])
            cnt = 0
        parts[-1].append(g)
        cnt += w
    res = []
    for p in parts:
        flat = [b for g in p for b in g]
        res.append(("\n".join(_render(g) for g in p), flat[0].page, flat[-1].page_end))
    return res


def build_chunks(parsed: dict[str, Any], log: AnomalyLog) -> tuple[list[dict[str, Any]], dict[str, str]]:
    chapters: dict[int, str] = parsed["chapters"]
    items: list[tuple[int, Item]] = parsed["items"]
    ids = {it.id for _, it in items}
    children: dict[str, list[str]] = {}
    for _, it in items:
        parent = ".".join(it.id.split(".")[:-1])
        if parent in ids:
            children.setdefault(parent, []).append(it.id)

    # глоссарий
    glossary: dict[str, str] = {}
    for _, it in items:
        if it.id == "1.4":
            for b in it.blocks[1:]:
                if " — " in b.text:
                    term, definition = b.text.split(" — ", 1)
                    glossary[term.strip()] = definition.strip().rstrip(";.").strip()
                else:
                    log.add("glossary_tail", "п. 1.4", b.text[:90], "абзац без « — » после списка терминов; не вошёл в glossary.json")
    gterms = list(glossary)

    chunks: list[dict[str, Any]] = []
    for ch_no, it in items:
        chapter = chapters[ch_no]
        parts = pack(it.blocks)
        parent_id = ".".join(it.id.split(".")[:-1])
        parent_id = parent_id if parent_id in ids else None
        chain = ([parent_id] if parent_id else []) + [it.id]
        level = "subpoint" if parent_id else "point"
        head = prefix(chapter, chain)

        if len(parts) > 1:
            # 1. Создаем виртуального родителя-заглушку
            chunks.append({
                "id": it.id, "virtual": True, "level": level, "chapter": chapter, "chapter_no": ch_no,
                "title": None, "text": "", "parent_id": parent_id,
                "children": [f"{it.id}#{k}" for k in range(1, len(parts) + 1)],
                "page": parts[0][1], "page_end": parts[-1][2], "doc": "instruction",
                "version": INSTRUCTION_VERSION, "effective_date": INSTRUCTION_EFFECTIVE,
                "access_level": DEFAULT_ACCESS_LEVEL, "refs": [], "keywords": []
            })
            # 2. Создаем нарезанные дочерние чанки
            for k, (txt, p0, p1) in enumerate(parts, start=1):
                cid = f"{it.id}#{k}"
                chunk = {
                    "id": cid, "level": level, "chapter": chapter, "chapter_no": ch_no, "title": None,
                    "text": f"{head}. {txt}",  # Заменили \n на .
                    "parent_id": it.id,        # Родитель - виртуальный чанк
                    "children": [],
                    "page": p0, "page_end": p1, "doc": "instruction", "version": INSTRUCTION_VERSION,
                    "effective_date": INSTRUCTION_EFFECTIVE, "access_level": DEFAULT_ACCESS_LEVEL,
                    "refs": [r for r in expand_refs(txt) if r != it.id],
                    "keywords": keywords(txt, gterms),
                    "part": {"base_id": it.id, "index": k, "of": len(parts)}
                }
                chunks.append(chunk)
        else:
            # Обычный чанк, который влез в лимит
            txt, p0, p1 = parts[0]
            chunk = {
                "id": it.id, "level": level, "chapter": chapter, "chapter_no": ch_no, "title": None,
                "text": f"{head}. {txt}",  # Заменили \n на .
                "parent_id": parent_id,
                "children": children.get(it.id, []),
                "page": p0, "page_end": p1, "doc": "instruction", "version": INSTRUCTION_VERSION,
                "effective_date": INSTRUCTION_EFFECTIVE, "access_level": DEFAULT_ACCESS_LEVEL,
                "refs": [r for r in expand_refs(txt) if r != it.id],
                "keywords": keywords(txt, gterms),
            }
            chunks.append(chunk)

    # Приложение 1
    ap = parsed["appendix"]
    if ap:
        chunks.append({
            "id": "A1", "level": "appendix", "chapter": "Приложение № 1", "chapter_no": None,
            "title": "Таблица замечаний",
            "text": f"Приложение № 1 > Таблица замечаний. " + "\n".join(l.text for l in ap[1:] if l.text != "ТАБЛИЦА ЗАМЕЧАНИЙ"),
            "parent_id": None, "children": [], "page": ap[0].page, "page_end": ap[-1].page,
            "doc": "instruction", "version": INSTRUCTION_VERSION, "effective_date": INSTRUCTION_EFFECTIVE,
            "access_level": DEFAULT_ACCESS_LEVEL, "refs": [], "keywords": ["таблица замечаний", "ПД", "повторное рассмотрение"],
        })
    return chunks, glossary
    # Приложение 1
    ap = parsed["appendix"]
    atext = "\n".join(l.text for l in ap)
    head = ap[0].text if ap else "Приложение № 1"
    chunks.append({
        "id": "A1", "level": "appendix", "chapter": "Приложение № 1", "chapter_no": None,
        "title": "Таблица замечаний",
        "text": f"Приложение № 1 > Таблица замечаний\n" + "\n".join(l.text for l in ap[1:] if l.text != "ТАБЛИЦА ЗАМЕЧАНИЙ"),
        "parent_id": None, "children": [], "page": ap[0].page if ap else 51, "page_end": ap[-1].page if ap else 51,
        "doc": "instruction", "version": INSTRUCTION_VERSION, "effective_date": INSTRUCTION_EFFECTIVE,
        "access_level": DEFAULT_ACCESS_LEVEL, "refs": [], "keywords": ["таблица замечаний", "ПД", "повторное рассмотрение"],
    })
    return chunks, glossary
