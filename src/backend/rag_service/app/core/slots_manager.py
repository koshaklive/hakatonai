"""Lightweight topic and slot state handling for chat sessions."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

SLOTS_CONFIG = Path(__file__).with_name("slots.yaml")
_FILLER_WORDS = re.compile(r"\b(?:а|для|по|тогда|если|то|же|в|на|с|о|об)\b", re.I)
_SLOT_QUESTIONS = {
    "вид_документа": "Уточните, пожалуйста, о каком виде документа идет речь?",
    "объем_страниц": "Уточните, пожалуйста, какой объем пояснительной записки в страницах?",
}


def load_slot_config(path: Path = SLOTS_CONFIG) -> dict[str, Any]:
    """Load and validate topic requirements and slot extractors."""
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("topics"), dict) or not isinstance(
        config.get("slots"), dict
    ):
        raise ValueError(f"Invalid slot configuration: {path}")
    for topic, definition in config["topics"].items():
        if not isinstance(definition, dict) or not isinstance(definition.get("required_slots"), list):
            raise ValueError(f"Invalid slot requirements for topic: {topic}")
        for pattern in definition.get("patterns", []):
            re.compile(pattern, re.I)
    return config


def _detect_topic(message: str, config: dict[str, Any]) -> str | None:
    priority = ("хранение", "пояснительная_записка", "адресат", "срок", "визирование")
    topics = config["topics"]
    ordered_topics = [topic for topic in priority if topic in topics]
    ordered_topics.extend(topic for topic in topics if topic not in ordered_topics)
    for topic in ordered_topics:
        definition = topics[topic]
        if any(re.search(pattern, message, re.I) for pattern in definition.get("patterns", [])):
            return topic
    return None


def _contains_slot_value(slot: str, message: str, config: dict[str, Any]) -> bool:
    definition = config["slots"][slot]
    values = definition.get("values", {})
    if slot == "объем_страниц":
        pattern = values.get("pattern")
        return isinstance(pattern, str) and re.search(pattern, message, re.I) is not None
    return any(
        re.search(pattern, message, re.I)
        for patterns in values.values()
        for pattern in patterns
    )


def _extract_slots(message: str, config: dict[str, Any]) -> dict[str, str]:
    found: dict[str, str] = {}
    for slot, definition in config["slots"].items():
        values = definition.get("values", {})
        if slot == "объем_страниц":
            pattern = values.get("pattern")
            match = re.search(pattern, message, re.I) if isinstance(pattern, str) else None
            if match:
                found[slot] = f"{match.group(1)} страниц"
            continue

        for value, patterns in values.items():
            if any(re.search(pattern, message, re.I) for pattern in patterns):
                found[slot] = value
                break
    return found


def _is_slot_only(message: str, extracted: dict[str, str], config: dict[str, Any]) -> bool:
    if not extracted:
        return False
    remaining = message.lower()
    for definition in config["slots"].values():
        values = definition.get("values", {})
        for patterns in values.values():
            if isinstance(patterns, list):
                for pattern in patterns:
                    remaining = re.sub(pattern, " ", remaining, flags=re.I)
    remaining = re.sub(r"\b\d+\s*(?:страниц\w*|стр\.?|лист\w*)\b", " ", remaining, flags=re.I)
    remaining = _FILLER_WORDS.sub(" ", remaining)
    return not re.sub(r"[\W_]+", "", remaining, flags=re.UNICODE)


def update_slot_state(session: dict[str, Any], message: str) -> dict[str, Any]:
    """Update session topic/slots and return a possible clarification or enriched query."""
    config = load_slot_config()
    session.setdefault("slots", {})
    session.setdefault("last_topic", None)
    if not isinstance(session["slots"], dict):
        session["slots"] = {}

    topic = _detect_topic(message, config)
    extracted = _extract_slots(message, config)
    continuation = topic is None and bool(session["last_topic"]) and _is_slot_only(message, extracted, config)
    active_topic = topic or (session["last_topic"] if continuation else None)

    session["slots"].update(extracted)
    if topic:
        session["last_topic"] = topic

    if not active_topic:
        return {"topic": None, "missing_slot": None, "query": message}

    definition = config["topics"].get(active_topic)
    if not isinstance(definition, dict):
        return {"topic": active_topic, "missing_slot": None, "query": message}

    required_slots = definition["required_slots"]
    missing_slot = next((slot for slot in required_slots if not session["slots"].get(slot)), None)
    if missing_slot:
        return {
            "topic": active_topic,
            "missing_slot": missing_slot,
            "question": _SLOT_QUESTIONS[missing_slot],
            "query": message,
        }

    slot_values = [session["slots"][slot] for slot in required_slots]
    if continuation:
        query = " ".join([definition.get("search_term", active_topic), *slot_values])
    else:
        query = message
        for value in slot_values:
            required_slot = next(slot for slot in required_slots if session["slots"][slot] == value)
            if not _contains_slot_value(required_slot, message, config):
                query = f"{query} {value}"
    return {"topic": active_topic, "missing_slot": None, "query": query.strip()}
