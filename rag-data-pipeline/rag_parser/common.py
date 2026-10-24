from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "input"          # положите сюда исходные файлы (или --src)
DATA_DIR = ROOT / "data"

SRC_FILES = {
    "instruction": "Инструкция_по_ДОУ_учебный_пример.pdf",
    "methodology": "Методические_рекомендации_по_работе_с_модульными_документами.docx",
    "matrix": "Матрица_обязательного_визирования_внутренних_и_внешних_документов.docx",
    "order_commissioning": "Модуль_приказа_о_вводе_в_эксплуатацию_информационной_системы.docx",
    "order_responsible": "Модуль_приказа_о_назначении_ответственных_за_делопроизводство.docx",
    "order_handover": "Модуль_приказа_о_приеме_и_передаче_дел_и_имущества.docx",
    "order_local_act": "Модуль_приказа_об_утверждении_и_введении_в_действие_локального.docx",
    "order_audit": "Модуль_распоряжения_о_проведении_внутреннего_аудита_процессов.docx",
    "order_committee": "Модуль_распоряжения_о_создании_проектного_комитета.docx",
    "order_workgroup": "Модуль_распоряжения_о_создании_рабочей_группы.docx",
}
# ключ -> код модуля (code == ключ SRC_FILES)
MODULE_CODES = [k for k in SRC_FILES if k.startswith("order_")]

INSTRUCTION_VERSION = "ОД-184"
INSTRUCTION_EFFECTIVE = "2026-11-01"
INSTRUCTION_APPROVED = "2026-10-15"
DEFAULT_ACCESS_LEVEL = 1


@dataclass
class Anomaly:
    kind: str
    where: str
    text: str
    detail: str = ""


class AnomalyLog:
    def __init__(self) -> None:
        self.items: list[Anomaly] = []

    def add(self, kind: str, where: str, text: str, detail: str = "") -> None:
        self.items.append(Anomaly(kind, where, text, detail))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def dump_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
