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

from app.core.docx_chunks import detect, parse_module, parse_numbered, read_blocks

_DEADLINE = re.compile(r"\b(?:до|не позднее|срок|дата)\b", re.I)


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


def validate_kb_file(file_bytes: bytes, filename: str) -> dict[str, Any]:
    """Inspect a DOCX knowledge-base source and return structural issues."""
    blocks = _blocks(file_bytes)
    kind = detect(blocks)
    metadata = {"source": filename, "title": Path(filename).stem, "version": "", "prefix": "VALIDATION", "kind": "document"}
    errors: list[dict[str, str]] = []
    if kind == "numbered":
        _, warnings = parse_numbered(blocks, metadata)
        errors.extend({"type": "numbering", "point": filename, "message": warning} for warning in warnings)
    elif kind == "module":
        _, warnings = parse_module(blocks, metadata)
        errors.extend({"type": "numbering", "point": filename, "message": warning} for warning in warnings)

    for block_index, (block_kind, value) in enumerate(blocks, start=1):
        if block_kind != "t":
            continue
        for row_index, row in enumerate(value, start=1):
            for column, _, text in row:
                if not text.strip():
                    errors.append({
                        "type": "empty_table_cell",
                        "point": filename,
                        "message": (f"{filename}: пустая ячейка в таблице "
                                    f"(блок {block_index}, строка {row_index}, столбец {column + 1})"),
                    })

    return {
        "filename": filename,
        "kind": kind,
        "errors": errors,
        "diff": {"added": [], "changed": [], "removed": []},
        "broken_links": [],
    }


def _raw_text_blocks(document: Document) -> list[str]:
    texts: list[str] = []
    for element in document.element.body.iterchildren():
        if element.tag == qn("w:p"):
            texts.append(Paragraph(element, document).text)
        elif element.tag == qn("w:tbl"):
            table = Table(element, document)
            texts.extend(cell.text for row in table.rows for cell in row.cells)
    return texts


def _quote(text: str, start: int, end: int, radius: int = 60) -> str:
    return text[max(0, start - radius):min(len(text), end + radius)].strip()


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
