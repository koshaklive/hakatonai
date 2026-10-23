"""JSON schemas for structured outputs."""
from __future__ import annotations

from typing import Any

CLARIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"need_clarification": {"type": "boolean"}, "question": {"type": "string"}},
    "required": ["need_clarification", "question"],
    "additionalProperties": False,
}

ROUTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"module_code": {"type": "string"}, "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
    "required": ["module_code", "confidence"],
    "additionalProperties": False,
}

DRAFT_CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "compliant": {"type": "boolean"},
        "issues": {"type": "array", "items": {
            "type": "object",
            "properties": {"point": {"type": "string"}, "problem": {"type": "string"}, "fix": {"type": "string"}},
            "required": ["point", "problem", "fix"]}},
    },
    "required": ["compliant", "issues"],
}


def extractor_schema(module_fields: dict[str, Any]) -> dict[str, Any]:
    """Wrap a module's field schema into {fields: {...}, missing: [...]}."""
    return {
        "type": "object",
        "properties": {"fields": module_fields, "missing": {"type": "array", "items": {"type": "string"}}},
        "required": ["fields", "missing"],
    }
