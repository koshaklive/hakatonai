from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from lxml import etree
from docx.oxml.ns import qn

from . import docxutil as X
from .common import MODULE_CODES, SRC_FILES, AnomalyLog, norm_ws, sha256
from .specs import SPECS

NOTES_HEAD = "Примечания по заполнению"
RULES_HEAD = "Общие правила"
NOTE_LEAD_RE = re.compile(r"^(\d+)\.\s+(.*)$")
EXAMPLE_RE = re.compile(r"[Нн]апример:?\s*(«[^»]+»)")


# ───────────────────────── разбор DOCX ─────────────────────────
def _marker_text(p: etree._Element) -> str:
    out = []
    for r in p.iter(qn("w:r")):
        out.append("\x00" if X.is_marker_run(r) else X.run_text(r))
    s = "".join(out)

    def sub(m: re.Match[str]) -> str:
        a = s[m.start() - 1] if m.start() > 0 else ""
        b = s[m.end()] if m.end() < len(s) else ""
        if a == "" or a.isspace() or b == "" or b.isspace() or b in ".,;:)":
            return ""
        return " "

    return re.sub(r"\x00+", sub, s)


def parse_module(path: Path) -> dict[str, Any]:
    doc = X.load(path)
    els = X.body_children(doc)
    texts = [X.para_text(p) if p.tag == qn("w:p") else X.cell_text(p.find(".//" + qn("w:tc"))) for p in els]
    i_msk = next(i for i, e in enumerate(els) if e.tag == qn("w:p") and X.para_text(e).strip() == "г. Москва")
    i_notes = next(i for i, e in enumerate(els) if e.tag == qn("w:p") and X.para_text(e).startswith(NOTES_HEAD))
    approver = ""
    if els[0].tag == qn("w:tbl"):
        cells = [X.para_text(p) for p in els[0].iter(qn("w:p"))]
        approver = next((c for c in cells if c.strip() and c.strip() != "УТВЕРЖДАЮ" and "_" not in c and "«" not in c), "")
    doc_kind = next(X.para_text(e).strip().lower() for e in els[:i_msk] if e.tag == qn("w:p")
                    and X.para_text(e).strip() in ("ПРИКАЗ", "РАСПОРЯЖЕНИЕ"))
    form = els[i_msk + 1:i_notes]
    # примечания
    notes: dict[int, dict[str, str]] = {}
    general: list[str] = []
    intro = ""
    mode = "notes"
    for e in els[i_notes + 1:]:
        if e.tag != qn("w:p"):
            continue
        t = X.para_text(e).strip()
        if not t:
            continue
        if t == RULES_HEAD:
            mode = "rules"
            continue
        if mode == "rules":
            general.append(re.sub(r"^•\s*", "", t).rstrip(";.").strip())
            continue
        runs = [r for r in e.iter(qn("w:r"))]
        m = NOTE_LEAD_RE.match(t)
        if m and len(runs) >= 2:
            lead = X.run_text(runs[0]).strip()           # «N. Метка.»
            label = NOTE_LEAD_RE.match(lead).group(2).rstrip(".").strip() if NOTE_LEAD_RE.match(lead) else m.group(2)
            hint = norm_ws("".join(X.run_text(r) for r in runs[1:]))
            notes[int(m.group(1))] = {"label": label, "hint": hint}
        elif not intro:
            intro = t
    # маркеры и их положение
    markers: dict[int, list[str]] = {}
    section, point = "header", None
    for e in form:
        if e.tag == qn("w:tbl"):
            txt = " ".join(X.para_text(p) for p in e.iter(qn("w:p")))
            loc = "signature" if ("ВИЗУАЛИЗАЦИЯ ЭП" in txt and "Фамилия" in txt) else (
                f"table@{point}" if point else "table")
            for p in e.iter(qn("w:p")):
                for n in X.markers_in(p):
                    markers.setdefault(n, []).append(loc)
            continue
        t = X.para_text(e).strip()
        if t.startswith(("ПРИКАЗЫВАЮ", "ОБЯЗЫВАЮ")):
            section, point = "operative", None
            continue
        if section == "header" and re.match(r"^О[б]?\s", t):
            section = "title"
            loc = "title"
        elif section == "title" and not re.match(r"^О[б]?\s", t):
            section = "preamble"
        if section == "operative":
            m = re.match(r"^(\d+(?:\.\d+)?)\.\s", t)
            if m:
                point = "point_" + m.group(1).replace(".", "_")
            loc = point or "operative"
        elif section in ("title", "preamble"):
            loc = section
        else:
            loc = "header"
        if "ВИЗУАЛИЗАЦИЯ ЭП" in t:
            loc = "signature"
        for n in X.markers_in(e):
            markers.setdefault(n, []).append(loc)
    title_p = next(e for e in form if e.tag == qn("w:p") and re.match(r"^О[б]?\s", X.para_text(e).strip()))
    has_sig_table = any(e.tag == qn("w:tbl") and "Фамилия" in " ".join(X.para_text(p) for p in e.iter(qn("w:p")))
                        for e in form)
    return {"doc": doc, "els": els, "i_msk": i_msk, "i_notes": i_notes, "form": form, "notes": notes,
            "general_rules": general, "intro": intro, "markers": markers, "approver": approver,
            "doc_kind": doc_kind, "title_text": norm_ws(_marker_text(title_p)), "has_sig_table": has_sig_table}


# ───────────────────────── JSON модуля ─────────────────────────
def _description(spec: dict[str, Any], kind: str, chunks: dict[str, dict[str, Any]], log: AnomalyLog, code: str) -> tuple[str, list[str]]:
    parts: list[str] = []
    refs: list[str] = []
    for ref, needle in spec["when"]:
        ch = chunks.get(ref)
        if ch is None:
            log.add("spec_ref_missing", code, f"п. {ref} не найден в чанках")
            continue
        refs.append(ref)
        lines = ch["text"].split("\n")[1:]
        lead = re.sub(r"[:.]$", "", lines[0]).strip() if lines else ""
        m = re.match(r"^(Приказ|Распоряжение)\b", lead)
        if m and m.group(1).lower() != kind:
            log.add("kind_conflict", f"{code} ↔ п. {ref}",
                    f"Инструкция п. {ref} говорит о документе вида «{m.group(1)}», модуль — «{kind}»",
                    lead[:160])
        if needle:
            hit = next((l for l in lines if l.startswith("•") and needle in l), None)
            if hit:
                parts.append(f"{lead}: {hit[1:].strip().rstrip(';.')} (Инструкция, п. {ref}).")
                continue
            log.add("spec_needle_missing", code, f"«{needle}» не найдено в п. {ref}")
        parts.append(f"См. Инструкцию, п. {ref}.")
    return " ".join(parts), refs


def build_module_json(code: str, path: Path, pm: dict[str, Any], chunks: dict[str, dict[str, Any]],
                      log: AnomalyLog, matrix_map: dict[str, Any]) -> dict[str, Any]:
    spec = SPECS[code]
    notes = pm["notes"]
    kind = pm["doc_kind"]
    desc, refs = _description(spec, kind, chunks, log, code)
    fields_out: list[dict[str, Any]] = []
    locs = pm["_slot_locs"]
    for f in spec["fields"]:
        n = f["note_no"]
        note = notes.get(n) if n else None
        out = {
            "id": f["id"], "note_no": n,
            "label": (note["label"] if note else None) or f.get("label") or f["id"],
            "type": f["type"], "required": f["required"],
            "conditional": f.get("conditional"), "choices": f.get("choices", []),
            "hint": ((note["hint"] if note else "") + (" " + f["hint_extra"] if f.get("hint_extra") else "")).strip() or None,
            "example": None, "appears_in": sorted(set(locs.get(f["id"], []))) or (
                [f"table@{pm['_table_loc']}"] if f.get("table") else []),
            "same_as": f.get("same_as"),
        }
        if note:
            m = EXAMPLE_RE.search(note["hint"])
            out["example"] = m.group(1) if m else None
        for k in ("fmt", "must_match", "table", "item_type", "date_part", "default", "slot_kind"):
            if k in f:
                out[k] = f[k]
        if f["id"] == "title_act":
            out["label"] = "Заголовок: вид и наименование утверждаемого документа"
        if n is None and f["id"] in ("process_names_title", "topic_title", "title_act"):
            out["note_no"] = None
            out["label"] = "Заголовок (повтор наименования)" if f["id"] != "title_act" else out["label"]
        fields_out.append(out)
    # метки для полей, делящих примечание
    labels_override = {"committee_chair": "Председатель Комитета", "committee_deputy": "Заместитель председателя Комитета",
                       "committee_secretary": "Секретарь Комитета", "committee_members": "Члены Комитета",
                       "wg_lead": "Руководитель рабочей группы", "wg_secretary": "Секретарь рабочей группы",
                       "wg_members": "Члены рабочей группы", "audit_lead": "Руководитель аудиторской группы",
                       "auditors": "Аудиторы", "date_from": "Дата начала аудита (день, месяц)",
                       "date_to": "Дата окончания аудита", "process_names": "Наименования проверяемых процессов",
                       "report_deadline": "Срок представления отчета", "report_addressee": "Адресат отчета",
                       "plan_owner": "Владелец плана мероприятий", "plan_deadline": "Срок подготовки плана мероприятий",
                       "deadline": "Конечная дата", "action": "Действия рабочей группы",
                       "cancel_date": "Дата отменяемого распоряжения (заголовок)", "cancel_number": "Номер отменяемого распоряжения (заголовок)",
                       "cancel_date_p2": "Дата отменяемого распоряжения (п. 2)", "cancel_number_p2": "Номер отменяемого распоряжения (п. 2)",
                       "cancel_name_p2": "Наименование отменяемого распоряжения", "project_names_p5": "Наименование проекта (преамбула)",
                       "project_names_p1": "Наименование проекта (п. 1)", "control_self": "Контроль оставляет за собой подписант",
                       "control_person": "Контролирующее лицо", "signer_name": "Подписант (И. О. Фамилия)",
                       "short_name_p1": "Сокращенное наименование (п. 1)", "short_name_p2": "Сокращенное наименование (п. 2)",
                       "short_name_p3_1": "Сокращенное наименование (п. 3.1)", "short_name_p3_2": "Сокращенное наименование (п. 3.2)",
                       "commission_date": "Дата ввода", "work_doc": "Документ, определивший работы",
                       "readiness_doc": "Документ о готовности", "unit": "Подразделение",
                       "title_object": "Заголовок: что вводится в эксплуатацию", "source_from": "Источник передачи («от ...»)",
                       "giver": "Сдающее лицо или подразделение", "receiver": "Принимающее лицо или подразделение",
                       "staff": "Ответственные по подразделениям (таблица)", "effective_date": "Дата введения в действие",
                       "cancel_old": "Признать утратившим силу (прежний документ)", "reason": "Основание или причина",
                       "project_names": "Наименования проектов (заголовок, п. 1)"}
    for o in fields_out:
        if o["id"] in labels_override:
            o["label"] = labels_override[o["id"]]
    sig_default = pm["approver"] or None
    # таблицы
    tables_out = []
    for t in spec["tables"]:
        tt = dict(t)
        tt["location"] = pm["_table_loc"]
        tables_out.append(tt)
    # опциональные блоки: Инструкция «renumber» уже в спецификации
    general = pm["general_rules"]
    out = {
        "code": code, "title": pm["title_text"], "doc_kind": kind, "signer_default": sig_default,
        "signature_block": "table" if pm["has_sig_table"] else "absent_in_table",
        "description": desc, "instruction_refs": refs,
        "keywords": spec["keywords"], "trigger_phrases": spec["trigger_phrases"],
        "trigger_phrases_source": "authored (в источниках нет примеров запросов)",
        "fields": fields_out, "optional_blocks": spec["optional_blocks"], "variants": spec["variants"],
        "tables": tables_out, "validation_rules": spec["validation"], "general_rules": general,
        "visa_matrix": matrix_map.get(code),
        "source_file": SRC_FILES[code], "sha256": sha256(path),
        "template": f"templates/{code}.docx",
        "markers_in_docx": sorted(pm["markers"]),
        "intro": pm["intro"],
    }
    return out


# ───────────────────────── шаблон DOCX ─────────────────────────
def _tag_para(tag: str) -> etree._Element:
    p = etree.Element(qn("w:p"))
    r = etree.SubElement(p, qn("w:r"))
    t = etree.SubElement(r, qn("w:t"))
    t.text = tag
    return p


def _clear_cell(tc: etree._Element, text: str = "") -> None:
    ps = tc.findall(qn("w:p"))
    for extra in ps[1:]:
        tc.remove(extra)
    X.set_paragraph_text(ps[0], text)


def process_form(code: str, pm: dict[str, Any], log: AnomalyLog) -> dict[str, Any]:
    """Одновременно: (1) определяет положение слотов (для appears_in), (2) строит шаблон на копии документа."""
    spec = SPECS[code]
    doc = pm["doc"]
    body = doc.element.body
    els = pm["els"]
    form = pm["form"]
    field_by_id = {f["id"]: f for f in spec["fields"]}
    slots: list[str] = list(spec["slots"])
    rewrites = [dict(r, used=0) for r in spec["rewrites"]]
    slot_locs: dict[str, list[str]] = {}
    k = 0
    section, point = "header", None
    problems: list[str] = []
    table_loc = None
    for e in form:
        if e.tag == qn("w:tbl"):
            txt = " ".join(X.para_text(p) for p in e.iter(qn("w:p")))
            if "ВИЗУАЛИЗАЦИЯ ЭП" in txt and "Фамилия" in txt:
                # блок подписи
                tr0 = e.findall(qn("w:tr"))[0].findall(qn("w:tc"))
                _clear_cell(tr0[1], "")
                sf = [f for f in spec["fields"] if f["id"] == "signer_name"]
                if sf:
                    _clear_cell(tr0[2], "{{signer_name}}")
                    slot_locs.setdefault("signer_name", []).append("signature")
                continue
            first = X.cell_text(e.find(".//" + qn("w:tc"))).strip()
            tdef = next((t for t in spec["tables"] if t["columns"][0] == first), None)
            if tdef:
                table_loc = point
                _build_table(e, spec["table_layout"][tdef["id"]], problems)
            continue
        raw = X.para_text(e).strip()
        if raw.startswith(("ПРИКАЗЫВАЮ", "ОБЯЗЫВАЮ")):
            section, point = "operative", None
            continue
        if section == "header" and re.match(r"^О[б]?\s", raw):
            section = "title"
        elif section == "title" and not re.match(r"^О[б]?\s", raw):
            section = "preamble"
        loc = section
        if section == "operative":
            m = re.match(r"^(\d+(?:\.\d+)?)\.\s", raw)
            if m:
                point = "point_" + m.group(1).replace(".", "_")
            loc = point or "operative"
        text = _marker_text(e)
        changed = text != X.para_text(e)
        # слоты
        def repl(m: re.Match[str]) -> str:
            nonlocal k
            if k >= len(slots):
                problems.append(f"лишний пробел №{k + 1}: {m.group(0)[:20]!r}")
                k += 1
                return m.group(0)
            fid = slots[k]
            k += 1
            f = field_by_id.get(fid)
            kind = "full" if X.DATE_FULL.fullmatch(m.group(0)) else "dm" if X.DATE_DM.fullmatch(m.group(0)) else "blank"
            want = "blank" if f["type"] != "date" else ("dm" if f.get("date_part") == "day_month" else "full")
            if kind != want:
                problems.append(f"слот {fid}: в DOCX {kind}, в спецификации {want}")
            slot_locs.setdefault(fid, []).append(loc)
            return "{{" + fid + "}}"
        new = X.TOKEN_RE.sub(repl, text)
        if new != text:
            changed = True
        for rw in rewrites:
            n = new.count(rw["old"])
            if n:
                new = new.replace(rw["old"], rw["new"])
                rw["used"] += n
                changed = True
        # абзац «Контроль»
        ctl = spec.get("control")
        if "{{control_person}}" in new and ctl:
            new = _control(new, ctl, spec, problems)
            changed = True
        elif "{{control_person}}" in new and not ctl:
            pass
        if changed:
            X.set_paragraph_text(e, new)
    if k != len(slots):
        problems.append(f"пробелов в форме {k}, в спецификации {len(slots)}")
    for rw in rewrites:
        if rw["used"] != rw.get("count", 1):
            problems.append(f"rewrite «{rw['old'][:40]}»: применён {rw['used']} раз, ожидалось {rw.get('count', 1)}")
    # обёртки {%p if %}
    for w in spec.get("wrap", []):
        hit = [e for e in form if e.tag == qn("w:p") and w["contains"] in X.para_text(e)]
        if len(hit) != 1:
            problems.append(f"wrap «{w['contains'][:30]}»: найдено {len(hit)} абзацев")
            continue
        hit[0].addprevious(_tag_para("{%p if " + w["if"] + " %}"))
        hit[0].addnext(_tag_para("{%p endif %}"))
    pm["_slot_locs"] = slot_locs
    pm["_table_loc"] = table_loc
    pm["_problems"] = problems
    return pm


def _control(text: str, ctl: dict[str, Any], spec: dict[str, Any], problems: list[str]) -> str:
    m = re.match(r"^(\d+)\.\s+(Контроль за исполнением настоящего (?:приказа|распоряжения) возложить на)\s*\{\{control_person\}\}\.(.*)$",
                 text, re.S)
    if not m:
        problems.append("абзац «Контроль» не распознан: " + text[:60])
        return text
    num = ctl["number_expr"]
    num = num if num.startswith("{{") else num
    return (f"{num}. {{% if control_self %}}{ctl['self_text']}{{% else %}}{m.group(2)} {{{{control_person}}}}.{{% endif %}}"
            + m.group(3))


def _build_table(tbl: etree._Element, layout: list[tuple], problems: list[str]) -> None:
    rows = tbl.findall(qn("w:tr"))
    data = rows[1:]
    if len(layout) > len(data):
        problems.append(f"таблица: строк данных {len(data)}, в раскладке {len(layout)}")
        return
    used = data[:len(layout)]
    for extra in data[len(layout):]:
        tbl.remove(extra)
    for row, item in zip(used, layout):
        cells = row.findall(qn("w:tc"))
        kind = item[0]
        if kind == "fixed":
            _clear_cell(cells[1], "{{" + item[1] + "}}")
        elif kind == "optional":
            _clear_cell(cells[1], "{{" + item[1] + "}}")
            row.addprevious(_tag_row(row, "{%tr if " + item[1] + " %}"))
            row.addnext(_tag_row(row, "{%tr endif %}"))
        elif kind == "repeat":
            var = item[1]
            if item[2]:  # объекты с полями
                for c, fld in zip(cells, item[2]):
                    _clear_cell(c, "{{ r." + fld + " }}")
                loop = "{%tr for r in " + var + " %}"
            else:
                _clear_cell(cells[1], "{{ m }}")
                loop = "{%tr for m in " + var + " %}"
            row.addprevious(_tag_row(row, loop))
            row.addnext(_tag_row(row, "{%tr endfor %}"))


def _tag_row(template_row: etree._Element, tag: str) -> etree._Element:
    r = copy.deepcopy(template_row)
    cells = r.findall(qn("w:tc"))
    for i, c in enumerate(cells):
        _clear_cell(c, tag if i == 0 else "")
    return r


def finalize_template(pm: dict[str, Any], out_path: Path, log: AnomalyLog, code: str) -> None:
    doc = pm["doc"]
    els = pm["els"]
    body = doc.element.body
    # удалить гриф УТВЕРЖДАЮ, пометку «МОДУЛЬНЫЙ ДОКУМЕНТ», блок примечаний и общих правил
    if els[0].tag == qn("w:tbl") and "УТВЕРЖДАЮ" in X.cell_text(els[0].find(".//" + qn("w:tc"))) + " ".join(
            X.para_text(p) for p in els[0].iter(qn("w:p"))):
        body.remove(els[0])
    for e in els:
        if e.tag == qn("w:p") and X.para_text(e).strip() == "МОДУЛЬНЫЙ ДОКУМЕНТ":
            body.remove(e)
    start = pm["i_notes"]
    if start > 0 and els[start - 1].tag == qn("w:p") and not X.para_text(els[start - 1]).strip():
        start -= 1
    for e in els[start:]:
        if e.getparent() is body:
            body.remove(e)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))


TAG_RE = re.compile(r"\{%-?\s*(p|tr)?\s*(if|endif|for|endfor|else|elif)\b")


def check_template(path: Path, module_json: dict[str, Any]) -> list[str]:
    """Проверка: теги сбалансированы, все переменные объявлены в JSON модуля."""
    d = X.load(path)
    text = "\n".join(X.para_text(p) for p in d.element.body.iter(qn("w:p")))
    probs: list[str] = []
    opens = len(re.findall(r"\{%-?\s*(?:p|tr)?\s*(?:if)\b", text))
    ends = len(re.findall(r"\{%-?\s*(?:p|tr)?\s*endif\b", text))
    fo = len(re.findall(r"\{%-?\s*(?:p|tr)?\s*for\b", text))
    fe = len(re.findall(r"\{%-?\s*(?:p|tr)?\s*endfor\b", text))
    if opens != ends:
        probs.append(f"if/endif: {opens}/{ends}")
    if fo != fe:
        probs.append(f"for/endfor: {fo}/{fe}")
    declared = {f["id"] for f in module_json["fields"]} | {v["id"] for v in module_json["variants"]} | {
        o["id"] for o in module_json["optional_blocks"]}
    for t in module_json["tables"]:
        declared |= set(t.get("context_vars", []) + ([t["context_var"]] if t.get("context_var") else []))
    declared |= {"r", "m"}
    for v in re.findall(r"\{\{\s*([A-Za-z_]\w*)", text):
        if v not in declared:
            probs.append(f"переменная {v} не объявлена в JSON модуля")
    for v in re.findall(r"\{%-?\s*(?:p|tr)?\s*(?:if|elif)\s+([A-Za-z_]\w*)", text):
        if v not in declared:
            probs.append(f"условие по {v} не объявлено в JSON модуля")
    if re.search(r"_{3,}", text):
        probs.append("в шаблоне остались линии ____")
    if re.search(r"\[\d+\]", text):
        probs.append("в шаблоне остались номера примечаний")
    return probs
