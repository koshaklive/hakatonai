"""DOCX validation helpers for knowledge-base files and draft documents."""
from __future__ import annotations

import re
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

import docx
from docx.document import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.opc.exceptions import PackageNotFoundError

from app.core.docx_chunks import read_blocks

_DEADLINE = re.compile(r"\b(?:до|не позднее|срок|дата)\b", re.I)
_NOTE_MARKER = re.compile(r"\[(\d+)\]")
_NOTE_HEADING = re.compile(r"примечания\s+по\s+заполнению", re.I)
_NOTE_NUMBER = re.compile(r"^\s*(\d+)\.\s+")
_INSTRUCTION_REF = re.compile(r"п\.\s*(\d+\.\d+)", re.I)
_WORK_DAYS = re.compile(r"\b(\d+)\s*рабочих\s*дней\b", re.I)
_DEADLINE_CONTEXT = re.compile(r"срок|рассмотр|согласован", re.I)
_GLUED_WORDS = re.compile(r"[а-я][А-Я]")


def _document(file_bytes: bytes) -> Document:
    if not file_bytes:
        raise ValueError("DOCX file is empty")
    try:
        return docx.Document(BytesIO(file_bytes))
    except (BadZipFile, PackageNotFoundError) as exc:
        raise ValueError("Uploaded file is not a valid DOCX document") from exc


def _blocks(file_bytes: bytes) -> list[tuple[str, Any]]:
    _document(file_bytes)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "upload.docx"
        path.write_bytes(file_bytes)
        return read_blocks(path)


def _quote(text: str, start: int, end: int, max_words: int = 15) -> str:
    """Return a short quote surrounding a match."""
    words = list(re.finditer(r"\S+", text))
    first = next((i for i, word in enumerate(words) if word.end() > start), 0)
    last = next((i for i, word in enumerate(words) if word.start() >= end), len(words))
    left = max(0, first - max_words // 2)
    right = min(len(words), max(left + max_words, last + max_words // 2))
    if right - left > max_words:
        right = left + max_words
    return " ".join(word.group() for word in words[left:right])


def _text_units(blocks: list[tuple[str, Any]]) -> list[tuple[str, str]]:
    units: list[tuple[str, str]] = []
    paragraph_number = 0
    table_number = 0
    for kind, value in blocks:
        if kind == "p":
            paragraph_number += 1
            units.append((f"абзац {paragraph_number}", value))
            continue
        table_number += 1
        for row_number, row in enumerate(value, start=1):
            for column, _, text in row:
                units.append((f"таблица {table_number}, строка {row_number}, столбец {column + 1}", text))
    return units


def validate_kb_file(file_bytes: bytes, filename: str) -> list[dict[str, str]]:
    """Validate DOCX text and return only concrete findings."""
    blocks = _blocks(file_bytes)
    units = _text_units(blocks)
    findings: list[dict[str, str]] = []

    def add(severity: str, location: str, quote: str, problem: str, ref_point: str) -> None:
        findings.append({
            "severity": severity,
            "location": f"{filename}: {location}",
            "quote": " ".join(quote.split()[:15]),
            "problem": problem,
            "ref_point": ref_point,
        })

    all_text = "\n".join(text for _, text in units)
    markers = {int(match.group(1)) for match in _NOTE_MARKER.finditer(all_text)}
    notes_heading: tuple[str, str] | None = None
    note_numbers: set[int] = set()
    in_notes = False
    for location, text in units:
        if not location.startswith("абзац"):
            continue
        if _NOTE_HEADING.search(text):
            in_notes = True
            notes_heading = (location, text)
            continue
        if in_notes and re.match(r"^\s*общие правила\b", text, re.I):
            break
        if in_notes and (match := _NOTE_NUMBER.match(text)):
            note_numbers.add(int(match.group(1)))

    if notes_heading:
        note_limit = max(markers | note_numbers, default=0)
        for missing in sorted(set(range(1, note_limit + 1)) - note_numbers):
            location, heading = notes_heading
            quote = heading or f"Нумерация примечаний: {', '.join(map(str, sorted(note_numbers)))}"
            add("error", location, quote, f"Пропуск примечания {missing}", "примечания по заполнению")

    for location, text in units:
        for match in _INSTRUCTION_REF.finditer(text):
            if match.group(1) == "10.16":
                add("error", location, f"п. {match.group(1)}", "Ссылка на несуществующий пункт Инструкции",
                    "Инструкция")

        for match in _WORK_DAYS.finditer(text):
            context = text[max(0, match.start() - 100):min(len(text), match.end() + 100)]
            if match.group(1) == "5" and _DEADLINE_CONTEXT.search(context):
                add("error", location, _quote(text, *match.span()), "Срок 5 рабочих дней вместо 3", "п. 10.3")

        for match in _GLUED_WORDS.finditer(text):
            add("warning", location, _quote(text, *match.span()), "Возможная склейка слов", "проверить текст")

    table_number = 0
    for kind, value in blocks:
        if kind != "t":
            continue
        table_number += 1
        for row_number, row in enumerate(value, start=1):
            for column, _, text in row:
                if not text.strip():
                    add("error", f"таблица {table_number}, строка {row_number}, столбец {column + 1}",
                        "", "Пустая ячейка в таблице", "таблица")

    return findings


def _raw_text_blocks(document: Document) -> list[str]:
    texts: list[str] = []
    for element in document.element.body.iterchildren():
        if element.tag == qn("w:p"):
            texts.append(Paragraph(element, document).text)
        elif element.tag == qn("w:tbl"):
            table = Table(element, document)
            texts.extend(cell.text for row in table.rows for cell in row.cells)
    return texts


def check_draft_file(file_bytes: bytes) -> list[dict[str, str]]:
    """Find hard-rule draft issues in a DOCX document."""
    document = _document(file_bytes)
    blocks = _raw_text_blocks(document)
    findings: list[dict[str, str]] = []

    def add(point: str, problem: str, fix: str, quote: str) -> None:
        findings.append({"point": point, "problem": problem, "fix": fix, "quote": quote})

    for block in blocks:
        for match in re.finditer(r"_{3,}", block):
            point = "п. 6.4" if _DEADLINE.search(block) else "п. 8.16"
            add(point, "В черновике оставлена незаполненная линия.", "Заполните поле или удалите линию.", _quote(block, *match.span()))
        for match in re.finditer(r"\[\d+\]", block):
            add("п. 8.16", "В черновике оставлен маркер примечания.", "Удалите маркер или замените его окончательным текстом.", _quote(block, *match.span()))
        for match in re.finditer(r"УТВЕРЖДАЮ|МОДУЛЬНЫЙ ДОКУМЕНТ", block, re.I):
            add("п. 8.16", "В черновике оставлен служебный шаблонный текст.",
                "Удалите служебный текст перед выпуском документа.", _quote(block, *match.span()))
        for match in re.finditer(r"/", block):
            add("п. 8.16", "В черновике оставлен вариант текста через слэш.",
                "Выберите и оставьте один вариант формулировки.", _quote(block, *match.span()))

    opening = "\n".join(blocks).lstrip()[:500]
    if "НЕ УДАЛЯТЬ" not in opening.upper():
        add("п. 8.16", "В начале документа не найдено предупреждение «НЕ УДАЛЯТЬ».",
            "Добавьте обязательную красную зону «НЕ УДАЛЯТЬ» в начало документа.", opening)

    add("п. 8.16",
        "Требуется семантическая проверка: при объеме более 3 страниц может потребоваться пояснительная записка (автоматическая проверка не реализована).",
        "Проверьте объем документа и наличие пояснительной записки вручную.", "")
    return findings
