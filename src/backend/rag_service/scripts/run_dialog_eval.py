"""Run multi-turn chat scenarios and produce a manual tone-evaluation sheet.

Usage: python scripts/run_dialog_eval.py [--live] [--mode lexical|hybrid|dense|rerank]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SERVICE_ROOT))

from app.chat import ChatService, deterministic_response  # noqa: E402
from app.core.intent import analyze_intent  # noqa: E402
from app.core.slots_manager import update_slot_state  # noqa: E402
from evallib import Settings, build_world, searcher  # noqa: E402

DEFAULT_SCENARIOS = SERVICE_ROOT / "eval" / "dialog_scenarios.json"
DEFAULT_TONE_OUTPUT = SERVICE_ROOT / "eval" / "tone_evaluation.md"
_CITATION_PATTERN = re.compile(r"\[(?:п\.\s*)?[\w.-]+(?:,\s*[\w.-]+)*\]", re.I)


class ScenarioLLM:
    """Offline LLM substitute that returns references found in the supplied context."""

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> SimpleNamespace:
        system = messages[0]["content"]
        user = messages[-1]["content"]
        if "Перепиши последний вопрос пользователя" in system:
            return SimpleNamespace(text=user.rsplit("\nuser: ", 1)[-1].strip())
        citations = list(dict.fromkeys(_CITATION_PATTERN.findall(user)))
        text = "Ответ основан на найденных фрагментах."
        if citations:
            text += " " + " ".join(citations)
        return SimpleNamespace(text=text)


def _load_scenarios(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Файл сценариев не найден: {path}")
    scenarios = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError(f"Ожидался непустой JSON-массив сценариев: {path}")
    for index, scenario in enumerate(scenarios, start=1):
        if not isinstance(scenario, dict) or not isinstance(scenario.get("steps"), list) or not scenario["steps"]:
            raise ValueError(f"Сценарий #{index} должен содержать непустой массив steps")
        for step_index, step in enumerate(scenario["steps"], start=1):
            if not isinstance(step, dict) or not isinstance(step.get("user"), str):
                raise ValueError(f"Шаг {step_index} сценария #{index} должен содержать строковое поле user")
    return scenarios


def _expected_points(value: Any) -> list[str]:
    values = [value] if isinstance(value, (str, int, float)) else value
    if not isinstance(values, list) or not all(isinstance(point, (str, int, float)) for point in values):
        raise ValueError("Поле points должно быть строкой, числом или массивом пунктов")
    points = []
    for point in values:
        normalized = str(point).strip()
        if not normalized.startswith("["):
            normalized = f"[п. {normalized}]" if re.fullmatch(r"\d+(?:\.\d+)*", normalized) else f"[{normalized}]"
        points.append(normalized)
    return points


def _check_step(step: dict[str, Any], answer: str, asks_clarification: bool) -> list[str]:
    failures: list[str] = []

    if "regex" in step:
        patterns = step["regex"] if isinstance(step["regex"], list) else [step["regex"]]
        if not all(isinstance(pattern, str) for pattern in patterns):
            raise ValueError("Поле regex должно быть строкой или массивом строк")
        for pattern in patterns:
            if re.search(pattern, answer, re.I) is None:
                failures.append(f"regex: ответ не соответствует /{pattern}/")

    if "points" in step:
        for point in _expected_points(step["points"]):
            if point.casefold() not in answer.casefold():
                failures.append(f"points: не найдена ожидаемая ссылка {point}")

    if "max_words" in step:
        maximum = step["max_words"]
        if not isinstance(maximum, int) or maximum < 0:
            raise ValueError("Поле max_words должно быть неотрицательным целым числом")
        actual = len(answer.split())
        if actual > maximum:
            failures.append(f"max_words: {actual} слов, лимит {maximum}")

    if "asks_clarification" in step:
        expected = step["asks_clarification"]
        if not isinstance(expected, bool):
            raise ValueError("Поле asks_clarification должно быть логическим")
        if asks_clarification is not expected:
            outcome = "задан" if asks_clarification else "не задан"
            failures.append(f"asks_clarification: уточняющий вопрос {outcome}, ожидалось {expected}")

    return failures


def _run_step(service: ChatService, session: dict[str, Any], message: str, max_access: int) -> dict[str, Any]:
    slot_state = update_slot_state(session, message)
    intent = analyze_intent(message)

    if slot_state["missing_slot"]:
        answer = slot_state["question"]
        clarification = {"slot": slot_state["missing_slot"], "topic": slot_state["topic"]}
        context_text = ""
    elif intent["action"] == "reply" and slot_state["topic"] is None:
        answer = deterministic_response(intent)
        clarification = None
        context_text = ""
    else:
        result = service.answer(
            slot_state["query"],
            history=session["history"],
            max_access=max_access,
            last_context=session.get("last_context", ""),
        )
        answer = result.answer
        clarification = result.clarification
        context_text = result.context_text
        if not result.refused and context_text and intent["action"] != "clarify":
            session["last_context"] = context_text
            session["last_sources"] = result.sources

    session["history"].extend([
        {"role": "user", "content": message},
        {"role": "assistant", "content": answer},
    ])
    session["history"] = session["history"][-6:]
    return {
        "answer": answer,
        "clarification": clarification,
        "context_text": context_text,
    }


def _markdown_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\r", "").replace("\n", "<br>")


def _write_tone_sheet(path: Path, rows: list[tuple[str, int, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "| Сценарий | Шаг | Реплика пользователя | Ответ бота | Оценка тона (пустое поле для ручного ввода) |",
        "|---|---:|---|---|---|",
    ]
    lines.extend(
        f"| {_markdown_cell(name)} | {step} | {_markdown_cell(user)} | {_markdown_cell(answer)} | |"
        for name, step, user, answer in rows
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--tone-output", type=Path, default=DEFAULT_TONE_OUTPUT)
    parser.add_argument("--mode", choices=("lexical", "dense", "hybrid", "rerank"), default="lexical")
    parser.add_argument("--live", action="store_true", help="Use configured LLM instead of the offline test substitute")
    args = parser.parse_args(argv)

    scenarios = _load_scenarios(args.scenarios)
    cfg = Settings()
    world = build_world(
        cfg,
        dense=args.mode != "lexical",
        rerank=args.mode == "rerank",
    )
    llm: Any
    if args.live:
        from llm_layer.llm import LLM

        llm = LLM()
    else:
        llm = ScenarioLLM()
    service = ChatService(cfg, searcher(world, args.mode, anchors=True), llm)
    print(f"mode={args.mode} LLM={'live' if args.live else 'offline test substitute'}\n")

    scenario_results: list[tuple[str, bool]] = []
    failures: list[str] = []
    tone_rows: list[tuple[str, int, str, str]] = []

    for scenario_index, scenario in enumerate(scenarios, start=1):
        name = str(scenario.get("name") or f"Сценарий {scenario_index}")
        session: dict[str, Any] = {
            "history": [],
            "last_context": "",
            "last_sources": [],
            "slots": {},
            "last_topic": None,
        }
        scenario_failed = False

        for step_index, step in enumerate(scenario["steps"], start=1):
            user_message = step["user"]
            try:
                result = _run_step(service, session, user_message, cfg.dev_access_level)
                answer = result["answer"]
                asks_clarification = result["clarification"] is not None or bool(
                    re.search(r"\b(?:уточните|подскажите)\b[^?]*\?", answer, re.I)
                )
                step_failures = _check_step(step, answer, asks_clarification)
            except Exception as exc:  # A broken step should not prevent later scenarios from running.
                answer = f"Ошибка выполнения: {type(exc).__name__}: {exc}"
                step_failures = [f"execution: {type(exc).__name__}: {exc}"]

            tone_rows.append((name, step_index, user_message, answer))
            if step_failures:
                scenario_failed = True
                failures.extend(
                    f"- {name}, реплика {step_index} ({user_message!r}), {failure}"
                    for failure in step_failures
                )

        scenario_results.append((name, not scenario_failed))

    _write_tone_sheet(args.tone_output, tone_rows)

    print("Сводка сценариев")
    print(f"{'Название сценария':<42} | Результат")
    print("-" * 56)
    for name, passed in scenario_results:
        print(f"{name:<42} | {'Пройдено' if passed else 'Нет'}")

    if failures:
        print("\nПровалы:")
        print("\n".join(failures))
    else:
        print("\nПровалов нет.")

    passed_count = sum(passed for _, passed in scenario_results)
    failed_count = len(scenario_results) - passed_count
    print(f"\nИтого: пройдено {passed_count}/{len(scenario_results)} сценариев; упало {failed_count}.")
    print(f"Файл для ручной разметки тона: {args.tone_output}")
    return 1 if failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
