"""docx → chunks (same contract as instruction_chunks.json). Handles: visa-matrix tables, modular documents
(template + numbered fill-in notes), numbered-point documents (methodics), and a generic paragraph fallback.

Ids never collide with the Instruction: its points are plain numbers ("6.4"); everything else carries a prefix
("MTX.int.6", "MR.4.2", "MOD.<slug>.n8"). The id is also the citation token shown to the LLM.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

Chunk = dict[str, Any]
Block = tuple[str, Any]                      # ("p", text) | ("t", rows) ; rows = [[(col, span, text), ...], ...]

_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               "a b v g d e e zh z i y k l m n o p r s t u f h c ch sh sch _ y _ e yu ya".split()))
_SKIP_WORDS = {"о", "об", "в", "и", "для", "по", "на", "за", "модуль", "приказа", "распоряжения"}
_DECOR = {"МОДУЛЬНЫЙ ДОКУМЕНТ", "НАИМЕНОВАНИЕ ОРГАНИЗАЦИИ", "ДАТА / РЕГИСТРАЦИОННЫЙ НОМЕР (НЕ УДАЛЯТЬ)", "г. Москва"}
_DECOR_TABLE = ("УТВЕРЖДАЮ", "ГЕРБ", "ВИЗУАЛИЗАЦИЯ ЭП")


def translit(s: str) -> str:
    return "".join(_TR.get(c, c) for c in s.lower())


def slug_of(stem: str, words: int = 2) -> str:
    """Stable ascii slug from a file name: 'Модуль_приказа_о_вводе_в_эксплуатацию_...' → 'vvode_ekspluatatsiyu_...'"""
    ws = [w for w in re.split(r"[\W_]+", stem.lower()) if w]
    keep = [w for w in ws if w not in _SKIP_WORDS] or ws
    return re.sub(r"[^a-z0-9_]+", "", "_".join(translit(w).replace("_", "")[:8] for w in keep[:words]))


def clean(s: str) -> str:
    s = re.sub(r"_{3,}", "…", s.replace("\u200b", "").replace("\xa0", " "))
    return re.sub(r"[ \t]+", " ", s).strip()


# ---------------------------------------------------------------- reading
def read_blocks(path: Path) -> list[Block]:
    d, out = docx.Document(str(path)), []
    for el in d.element.body.iterchildren():
        if el.tag == qn("w:p"):
            t = clean(Paragraph(el, d).text)
            if t:
                out.append(("p", t))
        elif el.tag == qn("w:tbl"):
            rows = []
            for tr in Table(el, d)._tbl.tr_lst:
                col, cells = 0, []
                for tc in tr.tc_lst:                       # grid-aware: merged cells keep their column
                    span = tc.grid_span
                    txt = " / ".join(clean("".join(x.text or "" for x in p.iter(qn("w:t")))) for p in tc.findall(qn("w:p")))
                    cells.append((col, span, re.sub(r"( / )+$|^( / )+", "", txt).strip()))
                    col += span
                rows.append(cells)
            out.append(("t", rows))
    return out


def _chunk(cid: str, text: str, *, doc: str, doc_title: str, source: str, version: str, chapter: str,
           level: str = "point", title: str | None = None, refs: list[str] | None = None,
           keywords: list[str] | None = None) -> Chunk:
    return {"id": cid, "level": level, "chapter": chapter, "chapter_no": None, "title": title, "text": text,
            "parent_id": None, "children": [], "page": None, "page_end": None, "doc": doc, "doc_title": doc_title,
            "source_file": source, "version": version, "effective_date": None, "access_level": 1,
            "refs": refs or [], "keywords": keywords or []}


# ---------------------------------------------------------------- matrix
def parse_matrix(blocks: list[Block], m: dict[str, Any]) -> tuple[list[Chunk], list[str]]:
    warn: list[str] = []
    tbl = next(rows for k, rows in blocks if k == "t" and any("Вид документа" in c[2] for c in rows[0]))
    header = [(c, t) for c, _, t in tbl[0]]
    names = {c: t for c, t in header}
    pre = [t for k, t in blocks[:next(i for i, (k, _) in enumerate(blocks) if k == "t")] if k == "p"]
    post = [t for k, t in blocks[blocks.index(("t", tbl)) + 1:] if k == "p"]
    kw = dict(doc="matrix", doc_title=m["title"], source=m["source"], version=m["version"], refs=["10.6", "10.11"])
    out = [_chunk(f"{m['prefix']}.rules", f"{m['title']} > Правила применения Матрицы. " + " ".join(pre[2:] + post),
                  chapter=m["title"], level="rules", title="Правила применения", keywords=["матрица", "визирование"], **kw)]
    section, sec_code = "", ""
    ncols = len(tbl[0]) + 1
    for cells in tbl[1:]:
        if len(cells) == 1 and cells[0][1] >= ncols - 1:            # section row
            section = cells[0][2].capitalize()
            sec_code = "int" if section.lower().startswith("внутр") else "ext" if section.lower().startswith("внеш") else f"s{len(out)}"
            continue
        first = cells[0][2]
        mm = re.match(r"^(\d+)\.\s*(.*)$", first, re.S)
        num, what = (mm.group(1), mm.group(2)) if mm else (str(len(out)), first)
        parts = []
        for col, _, txt in cells[1:]:
            name = names.get(col, f"колонка {col}")
            if not txt:
                warn.append(f"{m['source']}: строка «{section}, {num}», колонка «{name}» пуста в источнике")
                txt = "не указано в источнике"
            parts.append(f"{name}: {txt.lower() if txt in ('Да', 'Нет') else txt}")
        text = (f"{m['title']} > {section}, строка {num}. Вид документа и условия применения: {what} "
                f"Обязательное визирование по Матрице: " + "; ".join(parts).rstrip(".") + ".")
        out.append(_chunk(f"{m['prefix']}.{sec_code}.{num}", text, chapter=f"{m['title']} — {section.lower()}",
                          level="row", title=what[:90], keywords=[section.lower(), "визирование", "кто визирует"], **kw))
    return out, warn


# ---------------------------------------------------------------- modules (template + notes)
def parse_module(blocks: list[Block], m: dict[str, Any]) -> tuple[list[Chunk], list[str]]:
    warn: list[str] = []
    i = next(k for k, (t, v) in enumerate(blocks) if t == "p" and v.startswith("Примечания по заполнению"))
    body: list[str] = []
    for kind, v in blocks[:i]:
        if kind == "p":
            if v not in _DECOR:
                body.append(v)
        else:
            flat = [" | ".join(t for _, _, t in r if t) for r in v]
            if flat and flat[0].startswith(_DECOR_TABLE):
                continue
            body += [r for r in flat if r and not r.startswith(_DECOR_TABLE)]
    kw = dict(doc="module", doc_title=m["title"], source=m["source"], version=m["version"])
    base = f"{m['prefix']}"
    out = [_chunk(f"{base}.tpl", f"{m['title']} > Текст шаблона модуля. Постоянные формулировки и поля для заполнения; "
                  f"номера в квадратных скобках — это номера примечаний по заполнению.\n" + "\n".join(body),
                  chapter=m["title"], level="template", title="Текст шаблона", keywords=["модуль", "шаблон", "образец"], **kw)]
    tail = [v for k, v in blocks[i + 1:] if k == "p"]
    notes, rules, intro, in_rules = [], [], [], False
    for t in tail:
        if t.lower().startswith("общие правила"):
            in_rules = True
            continue
        mm = re.match(r"^(\d+)\.\s+(.*)$", t, re.S)
        if mm and not in_rules:
            notes.append((int(mm.group(1)), mm.group(2)))
        elif in_rules:
            rules.append(t)
        elif notes:
            notes[-1] = (notes[-1][0], notes[-1][1] + " " + t)
        else:
            intro.append(t)
    for n, t in notes:
        label = t.split(". ", 1)[0][:80]
        out.append(_chunk(f"{base}.n{n}", f"{m['title']} > Примечание {n} к шаблону ({label}). {t}",
                          chapter=m["title"], level="note", title=f"Примечание {n}: {label}", keywords=[label.lower()], **kw))
    if intro or rules:
        out.append(_chunk(f"{base}.rules", f"{m['title']} > Общие правила заполнения модуля. " + " ".join(intro) + " " + " ".join(rules),
                          chapter=m["title"], level="rules", title="Общие правила", keywords=["заполнение", "правила"], **kw))
    markers = {int(x) for x in re.findall(r"\[(\d+)\]", "\n".join(body))}
    have = {n for n, _ in notes}
    if markers - have:
        warn.append(f"{m['source']}: маркеры {sorted(markers - have)} есть в шаблоне, но нет примечаний")
    if have - markers:
        warn.append(f"{m['source']}: примечания {sorted(have - markers)} без маркера в шаблоне")
    if sorted(have) != list(range(1, len(have) + 1)):
        warn.append(f"{m['source']}: нумерация примечаний не сплошная: {sorted(have)}")
    return out, warn


# ---------------------------------------------------------------- numbered documents (methodics etc.)
_HEAD = re.compile(r"^(\d+)\.\s+([А-ЯЁ][^.;:]{2,100})$")
_POINT = re.compile(r"^(\d+(?:\.\d+)+)\.?\s+(.*)$", re.S)
_LISTITEM = re.compile(r"^(\d+)\.\s+\S")


def parse_numbered(blocks: list[Block], m: dict[str, Any]) -> tuple[list[Chunk], list[str]]:
    warn: list[str] = []
    kw = dict(doc=m["kind"], doc_title=m["title"], source=m["source"], version=m["version"])
    pts: list[dict[str, Any]] = []
    chap = ("", "")
    for kind, v in blocks:
        if kind != "p":
            continue
        if (h := _HEAD.match(v)):
            chap = (h.group(1), h.group(2))
        elif (p := _POINT.match(v)):
            pts.append({"num": p.group(1), "chap": chap, "lines": [p.group(2)]})
        elif pts:
            pts[-1]["lines"].append(v)
    out = []
    for p in pts:
        items = [int(x.group(1)) for ln in p["lines"] if (x := _LISTITEM.match(ln))]
        if items and items != list(range(items[0], items[0] + len(items))) or (items and items[0] != 1):
            warn.append(f"{m['source']}: в п. {p['num']} нумерованный список идёт как {items} — возможно, пропущен пункт в источнике")
        body = "\n".join(p["lines"])
        ref_ch = [f"ch:{x}" for x in re.findall(r"(?:главе|главой|глав[аы])\s+(\d+)", body)]
        level = "subpoint" if p["num"].count(".") > 1 else "point"
        out.append(_chunk(f"{m['prefix']}.{p['num']}",
                          f"{m['title']} > раздел {p['chap'][0]}. {p['chap'][1]} > пункт {p['num']}. {body}",
                          chapter=f"Раздел {p['chap'][0]}. {p['chap'][1]}", level=level, title=None,
                          refs=list(dict.fromkeys(ref_ch)), **kw))
    return out, warn


def parse_generic(blocks: list[Block], m: dict[str, Any], limit: int = 900) -> tuple[list[Chunk], list[str]]:
    kw = dict(doc="document", doc_title=m["title"], source=m["source"], version=m["version"])
    paras = [v for k, v in blocks if k == "p"] + [" | ".join(t for _, _, t in r if t) for k, rows in blocks if k == "t" for r in rows]
    out, cur = [], ""
    for p in paras + [""]:
        if p and len(cur) + len(p) < limit:
            cur += ("\n" if cur else "") + p
            continue
        if cur:
            out.append(_chunk(f"{m['prefix']}.s{len(out) + 1}", f"{m['title']} > фрагмент {len(out) + 1}. {cur}",
                              chapter=m["title"], level="point", **kw))
        cur = p
    return out, [f"{m['source']}: структура не распознана, документ разбит на фрагменты по ~{limit} символов"]


# ---------------------------------------------------------------- entry point
def detect(blocks: list[Block]) -> str:
    for k, v in blocks:
        if k == "t" and any("Вид документа" in c[2] for c in v[0]) and any("Юридическ" in c[2] for c in v[0]):
            return "matrix"
    if any(k == "p" and v.startswith("Примечания по заполнению") for k, v in blocks):
        return "module"
    if sum(1 for k, v in blocks if k == "p" and _POINT.match(v)) >= 3:
        return "numbered"
    return "generic"


def docx_to_chunks(path: str | Path, version: str, used_prefixes: set[str] | None = None) -> tuple[list[Chunk], list[str], str]:
    """Returns (chunks, warnings, kind)."""
    path = Path(path)
    blocks = read_blocks(path)
    kind = detect(blocks)
    stem = re.sub(r"_\d+$", "", path.stem).replace("_", " ")          # 'Матрица ..._1' → same title
    slug = slug_of(path.stem)
    prefix = {"matrix": "MTX", "module": f"MOD.{slug}",
              "numbered": "MR" if "методическ" in stem.lower() else f"DOC.{slug}",
              "generic": f"DOC.{slug}"}[kind]
    if used_prefixes is not None:
        if prefix in used_prefixes:
            raise ValueError(f"id prefix {prefix!r} already used by another file ({path.name})")
        used_prefixes.add(prefix)
    m = {"title": stem, "source": path.name, "version": version, "prefix": prefix,
         "kind": "methodics" if prefix == "MR" else "document"}
    chunks, warn = {"matrix": parse_matrix, "module": parse_module, "numbered": parse_numbered, "generic": parse_generic}[kind](blocks, m)
    return chunks, warn, kind
