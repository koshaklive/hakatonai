"""Versioned prompt loader. Files live in prompts/<PROMPT_VERSION>/<name>.md; placeholders: {{var}}."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

NO_ANSWER = "В базе знаний информации нет, обратитесь в Департамент ДОУ"
_ROOT = Path(__file__).parent


def version() -> str:
    """Active prompt version (env PROMPT_VERSION, default v1)."""
    return os.getenv("PROMPT_VERSION", "v1")


def load(name: str, ver: str | None = None) -> str:
    """Read raw prompt text."""
    return (_ROOT / (ver or version()) / f"{name}.md").read_text(encoding="utf-8")


def render(name: str, **variables: Any) -> str:
    """Load prompt and substitute {{var}} placeholders."""
    text = load(name)
    for key, val in variables.items():
        text = text.replace("{{" + key + "}}", str(val))
    return text.replace("{{NO_ANSWER}}", NO_ANSWER)


def format_fragments(fragments: Sequence[dict[str, str]], limit: int | None = None) -> str:
    """Format fragments [{'point': '10.6', 'text': '...'}] as '[п. 10.6] text'; capped at MAX_FRAGMENTS."""
    cap = limit or int(os.getenv("MAX_FRAGMENTS", "5"))
    return "\n\n".join(f"[п. {f['point']}] {f['text']}" for f in list(fragments)[:cap])


def rag_messages(question: str, fragments: Sequence[dict[str, str]],
                 history: Sequence[dict[str, str]] = ()) -> list[dict[str, str]]:
    """Build chat messages for rag_answer."""
    system = render("rag_answer", fragments=format_fragments(fragments))
    return [{"role": "system", "content": system}, *history, {"role": "user", "content": question}]


def json_messages(name: str, user: str, **variables: Any) -> list[dict[str, str]]:
    """Build messages for a JSON prompt (clarify, module_router, field_extractor, draft_checker)."""
    return [{"role": "system", "content": render(name, **variables)}, {"role": "user", "content": user}]
