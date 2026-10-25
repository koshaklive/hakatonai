from __future__ import annotations

from scripts.run_dialog_eval import _check_step, _expected_points, _load_scenarios


def test_dialog_scenarios_file_is_present_and_multistep():
    from pathlib import Path

    scenarios = _load_scenarios(
        Path(__file__).resolve().parents[1] / "eval" / "dialog_scenarios.json"
    )

    assert scenarios
    assert any(len(scenario["steps"]) > 1 for scenario in scenarios)


def test_eval_checks_regex_points_word_limit_and_clarification():
    failures = _check_step(
        {
            "regex": "Уточните.*виде документа",
            "points": ["10.3"],
            "max_words": 10,
            "asks_clarification": True,
        },
        "Уточните, пожалуйста, о каком виде документа идет речь? [п. 10.3]",
        asks_clarification=True,
    )

    assert failures == []


def test_eval_reports_each_failed_criterion():
    failures = _check_step(
        {
            "regex": "не найдено",
            "points": ["8.16"],
            "max_words": 1,
            "asks_clarification": True,
        },
        "Краткий ответ без ссылки.",
        asks_clarification=False,
    )

    assert len(failures) == 4
    assert any("regex" in failure for failure in failures)
    assert any("points" in failure for failure in failures)
    assert any("max_words" in failure for failure in failures)
    assert any("asks_clarification" in failure for failure in failures)


def test_numeric_point_is_normalized_to_instruction_citation():
    assert _expected_points("8.16") == ["[п. 8.16]"]
