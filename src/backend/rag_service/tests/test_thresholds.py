from __future__ import annotations

import json

from app.core.config import Settings
from app.chat import load_calibration


def test_threshold_fallback_uses_configured_base_threshold(monkeypatch):
    monkeypatch.delenv("REL_THRESHOLD", raising=False)
    cfg = Settings(rel_threshold=0.574, calibration_file="missing-calibration.json")

    assert load_calibration(cfg) == (0.424, 0.574)


def test_threshold_fallback_prefers_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("REL_THRESHOLD", "0.8")
    cfg = Settings(rel_threshold=0.574, calibration_file=str(tmp_path / "missing.json"))

    assert load_calibration(cfg) == (0.65, 0.8)


def test_thresholds_load_calibration_file(monkeypatch, tmp_path):
    monkeypatch.setenv("REL_THRESHOLD", "0.8")
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps({"gray_low": 0.31, "gray_high": 0.72}), encoding="utf-8")
    cfg = Settings(calibration_file=str(calibration))

    assert load_calibration(cfg) == (0.31, 0.72)
