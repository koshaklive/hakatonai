from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import UTF8JSONResponse, app
from app.core.pb import PocketBase
from llm_layer.llm import LLM


def test_health_json_response_has_utf8_charset_and_index_version(monkeypatch):
    monkeypatch.setattr(PocketBase, "ping", lambda self: False)
    monkeypatch.setattr(LLM, "health", lambda self, ping=True: {"ok": False})

    client = TestClient(app)
    response = client.get("/health")
    missing = client.get("/not-found")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.json()["index_version"] == "ОД-184"
    assert missing.headers["content-type"] == "application/json; charset=utf-8"


def test_json_routes_use_utf8_response_class():
    json_routes = {
        "/health", "/search", "/kb/validate", "/check/draft", "/chat",
        "/chunks/{chunk_id:path}", "/versions", "/ingest", "/modules/route", "/modules/fill",
    }
    routes = {route.path: route for route in app.routes if hasattr(route, "response_class")}

    assert all(routes[path].response_class is UTF8JSONResponse for path in json_routes)
