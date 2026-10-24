"""Strict offline validation and HTTP evaluation runner for the gold set."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FIELDS = {
    "id",
    "category",
    "question",
    "needs_clarification",
    "clarifying_question",
    "expected_answer",
    "expected_points",
    "must_include",
    "must_not_include",
    "source_quote",
    "difficulty",
    "trap",
}
ALLOWED_CATEGORIES = {"factual", "trap", "matrix", "module", "ood", "incomplete", "ambiguous"}


def normalize_text(text: str) -> str:
    return text.lower().strip().replace("ё", "е")


def load_gold(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as source_file:
            data = json.load(source_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Не удалось прочитать gold-файл {path}: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("Корень gold.json должен быть JSON-массивом.")
    return data


def validate_gold(data: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if len(data) != 40:
        errors.append(f"Ожидалось ровно 40 кейсов, получено {len(data)}.")

    seen_ids: set[str] = set()
    for index, item in enumerate(data):
        label = f"Элемент #{index + 1}"
        if not isinstance(item, dict):
            errors.append(f"{label}: ожидался JSON-объект.")
            continue

        missing = REQUIRED_FIELDS - item.keys()
        extra = item.keys() - REQUIRED_FIELDS
        if missing:
            errors.append(f"{label}: отсутствуют поля {', '.join(sorted(missing))}.")
        if extra:
            errors.append(f"{label}: неизвестные поля {', '.join(sorted(extra))}.")

        case_id = item.get("id")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"{label}: id должен быть непустой строкой.")
        elif case_id in seen_ids:
            errors.append(f"{label}: повторяющийся id {case_id}.")
        else:
            seen_ids.add(case_id)

        for key in ("category", "question", "expected_answer", "source_quote"):
            if not isinstance(item.get(key), str):
                errors.append(f"{label} ({case_id}): {key} должен быть строкой.")
        if item.get("category") not in ALLOWED_CATEGORIES:
            errors.append(f"{label} ({case_id}): неизвестная category.")
        if not isinstance(item.get("needs_clarification"), bool):
            errors.append(f"{label} ({case_id}): needs_clarification должен быть bool.")
        if item.get("clarifying_question") is not None and not isinstance(
            item.get("clarifying_question"), str
        ):
            errors.append(f"{label} ({case_id}): clarifying_question должен быть строкой или null.")
        if not isinstance(item.get("difficulty"), int) or item.get("difficulty") not in {1, 2, 3}:
            errors.append(f"{label} ({case_id}): difficulty должен быть целым числом 1, 2 или 3.")
        for key in ("expected_points", "must_include", "must_not_include"):
            value = item.get(key)
            if not isinstance(value, list) or any(not isinstance(entry, str) for entry in value):
                errors.append(f"{label} ({case_id}): {key} должен быть массивом строк.")

        quote = item.get("source_quote")
        if isinstance(quote, str) and len(quote.split()) > 15:
            errors.append(f"{label} ({case_id}): цитата длиннее 15 слов.")
        if item.get("needs_clarification") and not item.get("clarifying_question"):
            errors.append(f"{label} ({case_id}): для уточнения нужен clarifying_question.")
        if item.get("category") == "ood" and item.get("expected_points"):
            errors.append(f"{label} ({case_id}): OOD-кейс не должен содержать expected_points.")
    return errors


def offline_check(gold_path: Path) -> bool:
    try:
        data = load_gold(gold_path)
    except ValueError as exc:
        print(f"[ОШИБКА] {exc}", file=sys.stderr)
        return False
    errors = validate_gold(data)
    print("=== Offline-check gold.json ===")
    if errors:
        for error in errors:
            print(f"[ОШИБКА] {error}")
        print(f"Проверка завершена: {len(errors)} ошибок.")
        return False
    print(f"Проверка завершена успешно: {len(data)} кейсов, схема и цитаты валидны.")
    return True


def validate_response(response: Any, case_id: str) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(response, dict):
        return None, f"{case_id}: ответ API должен быть JSON-объектом."
    required = {"answer", "sources", "no_answer", "clarification"}
    if response.keys() != required:
        return None, f"{case_id}: ожидаются поля ответа {sorted(required)}."
    if not isinstance(response["answer"], str):
        return None, f"{case_id}: answer должен быть строкой."
    if not isinstance(response["sources"], list):
        return None, f"{case_id}: sources должен быть массивом."
    if not isinstance(response["no_answer"], bool) or not isinstance(response["clarification"], bool):
        return None, f"{case_id}: no_answer и clarification должны быть bool."
    for source in response["sources"]:
        if not isinstance(source, dict) or source.keys() != {"point", "relevance", "quote"}:
            return None, f"{case_id}: некорректная схема элемента sources."
        if (
            not isinstance(source["point"], str)
            or not isinstance(source["quote"], str)
            or not isinstance(source["relevance"], (int, float))
            or isinstance(source["relevance"], bool)
            or not 0.0 <= source["relevance"] <= 1.0
        ):
            return None, f"{case_id}: некорректные типы/значения элемента sources."
    return response, None


def run_evaluation(url: str, gold_path: Path, report_path: Path) -> bool:
    try:
        import requests
    except ImportError as exc:
        print(
            "Для онлайн-прогона установите зависимости командой: "
            "python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        print(f"Не удалось импортировать requests: {exc}", file=sys.stderr)
        return False

    try:
        gold_data = load_gold(gold_path)
    except ValueError as exc:
        print(f"[ОШИБКА] {exc}", file=sys.stderr)
        return False
    schema_errors = validate_gold(gold_data)
    if schema_errors:
        for error in schema_errors:
            print(f"[ОШИБКА] {error}", file=sys.stderr)
        return False

    results: list[dict[str, Any]] = []
    metrics = {
        "total": len(gold_data),
        "recall_points": 0,
        "must_include": 0,
        "must_not_include_violated": 0,
        "correct_ood": 0,
        "correct_clarification": 0,
        "hallucinations": 0,
        "api_errors": 0,
    }

    for item in gold_data:
        case_id = item["id"]
        try:
            http_response = requests.post(
                url,
                json={"session_id": f"eval_{case_id}", "message": item["question"]},
                timeout=10,
            )
            http_response.raise_for_status()
            payload, validation_error = validate_response(http_response.json(), case_id)
        except (requests.RequestException, ValueError) as exc:
            payload, validation_error = None, f"{case_id}: запрос/JSON ответа завершился ошибкой: {exc}"

        if validation_error:
            metrics["api_errors"] += 1
            results.append(
                {"id": case_id, "question": item["question"], "expected": item["expected_answer"],
                 "got": validation_error, "success": False}
            )
            continue

        assert payload is not None
        answer = normalize_text(payload["answer"])
        returned_points = {source["point"] for source in payload["sources"]}
        expected_points = set(item["expected_points"])
        includes_ok = all(normalize_text(value) in answer for value in item["must_include"])
        exclusions_ok = not any(normalize_text(value) in answer for value in item["must_not_include"])
        points_ok = expected_points.issubset(returned_points)

        metrics["recall_points"] += int(bool(expected_points) and points_ok)
        metrics["must_include"] += int(includes_ok)
        metrics["must_not_include_violated"] += int(not exclusions_ok)
        metrics["hallucinations"] += int(bool(returned_points - expected_points))
        metrics["correct_ood"] += int(item["category"] == "ood" and payload["no_answer"])
        metrics["correct_clarification"] += int(
            item["needs_clarification"] and payload["clarification"]
        )
        success = includes_ok and exclusions_ok and points_ok
        results.append(
            {"id": case_id, "question": item["question"], "expected": item["expected_answer"],
             "got": payload["answer"], "success": success}
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as report:
        report.write("# Отчет автопрогона (Eval Report)\n\n")
        report.write(f"- Всего вопросов: {metrics['total']}\n")
        report.write(f"- Точность источников: {metrics['recall_points']}/{metrics['total']}\n")
        report.write(f"- Успех must_include: {metrics['must_include']}/{metrics['total']}\n")
        report.write(f"- Нарушения must_not_include: {metrics['must_not_include_violated']}\n")
        report.write(f"- Корректные отказы (OOD): {metrics['correct_ood']}\n")
        report.write(f"- Корректные уточнения: {metrics['correct_clarification']}\n")
        report.write(f"- Галлюцинации источников: {metrics['hallucinations']}\n")
        report.write(f"- Ошибки API/схемы: {metrics['api_errors']}\n\n## Ошибки\n")
        failures = [result for result in results if not result["success"]]
        if not failures:
            report.write("Ошибок по критериям нет.\n")
        for result in failures:
            report.write(
                f"\n**{result['id']}**: {result['question']}\n"
                f"> Expected: {result['expected']}\n> Got: {result['got']}\n"
            )
    print(f"Отчет записан: {report_path}")
    print(
        f"Проверено {metrics['total']} кейсов; API/schema errors: "
        f"{metrics['api_errors']}; report failures: {sum(not row['success'] for row in results)}."
    )
    return metrics["api_errors"] == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-check", action="store_true")
    parser.add_argument("--url", default="http://localhost:8000/chat")
    parser.add_argument("--gold", type=Path, default=ROOT / "eval" / "gold.json")
    parser.add_argument(
        "--report", type=Path, default=ROOT / "eval" / "reports" / "eval_report.md"
    )
    args = parser.parse_args()
    gold_path = args.gold if args.gold.is_absolute() else ROOT / args.gold
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    success = offline_check(gold_path) if args.offline_check else run_evaluation(
        args.url, gold_path, report_path
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
