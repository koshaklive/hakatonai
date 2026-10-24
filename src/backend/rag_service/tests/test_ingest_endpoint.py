from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from docx import Document
from fastapi.testclient import TestClient

from app.api import main as api
from app.audit import Audit
from app.core.chunks import load_chunks
from app.core.config import Settings
from app.core.pb import PocketBase
from app.core.registry import Registry
from app.ingest import build_index


class FakeLLM:
    def chat(self, messages, **kwargs):
        return SimpleNamespace(text="ok")

    def health(self, ping=False):
        return {"ok": True}


def _docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def _app_with_active_index(monkeypatch, tmp_path, file_bytes):
    data_path = Path(__file__).resolve().parents[1] / "data" / "instruction_chunks.json"
    raw = load_chunks(data_path)
    cfg = Settings(
        index_dir=tmp_path / "indexes",
        data_file=str(data_path),
        anchors_file=str(Path(__file__).resolve().parents[1] / "anchors.yaml"),
        dense_enabled=False,
        use_qdrant=False,
        auth_mode="dev",
        warmup=False,
    )
    build_index(cfg, raw)
    monkeypatch.setattr(api, "make_embedder", lambda _: None)
    monkeypatch.setattr("llm_layer.llm.LLM", FakeLLM)
    monkeypatch.setattr(Audit, "event", lambda *args, **kwargs: None)

    record = {
        "id": "version-test",
        "file": "uploaded.docx",
        "version_label": "ОД-185",
        "access_level": 1,
        "effective_date": "",
    }
    patches = []
    monkeypatch.setattr(PocketBase, "get", lambda self, collection, record_id: record)
    monkeypatch.setattr(PocketBase, "download", lambda self, rec, field: file_bytes)
    monkeypatch.setattr(
        PocketBase,
        "patch",
        lambda self, collection, record_id, data: patches.append(dict(data)) or {},
    )
    return api.create_app(cfg), cfg, patches


def test_ingest_validation_error_marks_version_failed_and_keeps_old_index(monkeypatch, tmp_path):
    app, cfg, patches = _app_with_active_index(monkeypatch, tmp_path, _docx_bytes("Ссылка на пункт п. 10.16."))
    old_active = Registry(cfg.index_dir).read()["active"]

    with TestClient(app) as client:
        response = client.post("/ingest/version-test")

    assert response.status_code == 422
    assert response.json()["detail"]["validation"][0]["problem"] == "Ссылка на несуществующий пункт Инструкции"
    assert Registry(cfg.index_dir).read()["active"] == old_active
    assert patches[-1]["status"] == "failed"
    assert "10.16" in patches[-1]["comment"]


def test_ingest_builds_then_hot_swaps_and_marks_version_active(monkeypatch, tmp_path):
    app, cfg, patches = _app_with_active_index(monkeypatch, tmp_path, _docx_bytes("Новый документ для индексации."))
    old_active = Registry(cfg.index_dir).read()["active"]

    with TestClient(app) as client:
        response = client.post("/ingest/version-test")
        health = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    registry = Registry(cfg.index_dir).read()
    assert registry["active"] != old_active
    assert health.json()["index_version"] == "ОД-185"
    assert [patch["status"] for patch in patches] == ["indexing", "active"]


def test_ingest_marks_invalid_docx_failed_without_switching_registry(monkeypatch, tmp_path):
    app, cfg, patches = _app_with_active_index(monkeypatch, tmp_path, b"not a docx file")
    old_active = Registry(cfg.index_dir).read()["active"]

    with TestClient(app) as client:
        response = client.post("/ingest/version-test")

    assert response.status_code == 422
    assert Registry(cfg.index_dir).read()["active"] == old_active
    assert patches[-1]["status"] == "failed"
    assert json.loads(patches[-1]["comment"])[0]["severity"] == "error"
