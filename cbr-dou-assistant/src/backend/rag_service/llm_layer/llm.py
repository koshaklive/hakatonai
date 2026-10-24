"""OpenAI-compatible LLM adapter (LM Studio / Ollama / vLLM) — switch backend via .env only."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Sequence, TypeVar

from dotenv import load_dotenv
from openai import (APIConnectionError, APITimeoutError, BadRequestError, InternalServerError,
                    OpenAI, RateLimitError)

load_dotenv()
log = logging.getLogger("llm")
T = TypeVar("T")
Messages = list[dict[str, str]]
_RETRYABLE = (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)


class LLMError(RuntimeError):
    """Backend failure after retries."""


class LLMJSONError(LLMError):
    """Model did not return valid JSON after fallback + retry."""


@dataclass
class LLMConfig:
    """Settings loaded from environment (.env)."""
    base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "http://localhost:1234/v1"))
    api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", "lm-studio"))
    model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "qwen3.5-9b"))
    temperature: float = field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.1")))
    max_tokens: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_TOKENS", "1024")))
    timeout: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT", "120")))
    retries: int = field(default_factory=lambda: int(os.getenv("LLM_RETRIES", "3")))
    context_tokens: int = field(default_factory=lambda: int(os.getenv("LLM_CONTEXT_TOKENS", "8192")))
    json_mode: str = field(default_factory=lambda: os.getenv("LLM_JSON_MODE", "json_schema"))
    extra_body: dict[str, Any] = field(default_factory=lambda: json.loads(os.getenv("LLM_EXTRA_BODY", "{}") or "{}"))
    no_think_suffix: bool = field(default_factory=lambda: os.getenv("LLM_NO_THINK_SUFFIX", "0") == "1")


@dataclass
class ChatResult:
    """Non-streaming result."""
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency: float = 0.0
    tps: float = 0.0
    finish_reason: str | None = None


@dataclass
class StreamStats:
    """Filled by chat_stream after the generator is exhausted."""
    ttft: float | None = None
    latency: float = 0.0
    completion_tokens: int = 0
    prompt_tokens: int = 0
    tps: float = 0.0
    text: str = ""


def strip_think(text: str) -> str:
    """Remove <think>…</think> (also a lone '</think>' or an unclosed '<think>')."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    if "</think>" in text:
        text = text.split("</think>")[-1]
    text = re.sub(r"<think>.*\Z", "", text, flags=re.S)
    return text.strip()


class ThinkStripper:
    """Incremental <think> filter for streamed chunks."""
    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self.buf, self.inside = "", False

    def feed(self, chunk: str) -> str:
        """Consume a chunk, return text that is safe to show."""
        self.buf += chunk
        out: list[str] = []
        while True:
            if self.inside:
                i = self.buf.find(self.CLOSE)
                if i < 0:
                    self.buf = self.buf[-(len(self.CLOSE) - 1):]
                    break
                self.buf, self.inside = self.buf[i + len(self.CLOSE):], False
                continue
            i = self.buf.find(self.OPEN)
            if i >= 0:
                out.append(self.buf[:i])
                self.buf, self.inside = self.buf[i + len(self.OPEN):], True
                continue
            keep = next((k for k in range(min(len(self.OPEN) - 1, len(self.buf)), 0, -1)
                         if self.OPEN.startswith(self.buf[-k:])), 0)
            out.append(self.buf[:len(self.buf) - keep])
            self.buf = self.buf[len(self.buf) - keep:]
            break
        return "".join(out)

    def flush(self) -> str:
        """Return remaining buffered text."""
        out = "" if self.inside else self.buf
        self.buf = ""
        return out


def extract_json(text: str) -> Any:
    """Parse JSON from text: direct, ```json fence, or first balanced {...}/[...]."""
    text = strip_think(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start = next((i for i, c in enumerate(text) if c in "{["), -1)
    if start >= 0:
        opener = text[start]
        closer = "}" if opener == "{" else "]"
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                esc = (c == "\\" and not esc)
                if c == '"' and not esc:
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    raise json.JSONDecodeError("no JSON found", text, 0)


class LLM:
    """Chat / stream / structured-JSON client with retries, timing and health-check."""

    def __init__(self, cfg: LLMConfig | None = None) -> None:
        self.cfg = cfg or LLMConfig()
        self.client = OpenAI(base_url=self.cfg.base_url, api_key=self.cfg.api_key,
                             timeout=self.cfg.timeout, max_retries=0)
        self.last_json_meta: dict[str, Any] = {}

    # ---- internals ----
    def _retry(self, fn: Callable[[], T]) -> T:
        for attempt in range(self.cfg.retries + 1):
            try:
                return fn()
            except _RETRYABLE as e:
                if attempt == self.cfg.retries:
                    raise LLMError(f"{type(e).__name__}: {e}") from e
                delay = min(0.5 * 2 ** attempt, 8)
                log.warning("LLM retry %d/%d in %.1fs: %s", attempt + 1, self.cfg.retries, delay, e)
                time.sleep(delay)
        raise LLMError("unreachable")

    def _params(self, messages: Sequence[dict[str, str]], **kw: Any) -> dict[str, Any]:
        msgs = [dict(m) for m in messages]
        if self.cfg.no_think_suffix and msgs and msgs[-1]["role"] == "user":
            msgs[-1]["content"] += " /no_think"
        est = sum(len(m["content"]) for m in msgs) // 3
        if est > self.cfg.context_tokens:
            log.warning("prompt ≈%d tokens exceeds LLM_CONTEXT_TOKENS=%d", est, self.cfg.context_tokens)
        extra = {**self.cfg.extra_body, **kw.pop("extra_body", {})}
        p: dict[str, Any] = dict(model=self.cfg.model, messages=msgs,
                                 temperature=kw.pop("temperature", self.cfg.temperature),
                                 max_tokens=kw.pop("max_tokens", self.cfg.max_tokens))
        if extra:
            p["extra_body"] = extra
        p.update(kw)
        return p

    # ---- public API ----
    def chat(self, messages: Sequence[dict[str, str]], **kw: Any) -> ChatResult:
        """Single completion; <think> blocks stripped."""
        params = self._params(messages, **kw)
        t0 = time.perf_counter()
        r = self._retry(lambda: self.client.chat.completions.create(**params))
        dt = time.perf_counter() - t0
        ch = r.choices[0]
        text = strip_think(ch.message.content or "")
        ct = r.usage.completion_tokens if r.usage else 0
        res = ChatResult(text, r.usage.prompt_tokens if r.usage else 0, ct, dt, ct / dt if dt else 0.0,
                         ch.finish_reason)
        if not text and ch.finish_reason == "length":
            log.warning("empty content with finish_reason=length: thinking likely consumed max_tokens")
        log.info("chat %.2fs, %d tok, %.1f tok/s", dt, ct, res.tps)
        return res

    def chat_stream(self, messages: Sequence[dict[str, str]], stats: StreamStats | None = None,
                    **kw: Any) -> Iterator[str]:
        """Yield text deltas (thinking stripped). Fills `stats` when exhausted."""
        stats = stats if stats is not None else StreamStats()
        params = self._params(messages, **kw)
        params.update(stream=True, stream_options={"include_usage": True})
        t0 = time.perf_counter()
        stream = self._retry(lambda: self.client.chat.completions.create(**params))
        flt, chunks = ThinkStripper(), 0
        for ev in stream:
            if ev.usage:
                stats.completion_tokens, stats.prompt_tokens = ev.usage.completion_tokens, ev.usage.prompt_tokens
            if not ev.choices:
                continue
            delta = ev.choices[0].delta.content or ""  # reasoning_content is ignored on purpose
            if not delta:
                continue
            chunks += 1
            out = flt.feed(delta)
            if out:
                if stats.ttft is None:
                    stats.ttft = time.perf_counter() - t0
                stats.text += out
                yield out
        tail = flt.flush()
        if tail:
            if stats.ttft is None:
                stats.ttft = time.perf_counter() - t0
            stats.text += tail
            yield tail
        stats.latency = time.perf_counter() - t0
        stats.completion_tokens = stats.completion_tokens or chunks
        gen = stats.latency - (stats.ttft or 0)
        stats.tps = stats.completion_tokens / stats.latency if not gen > 0 else stats.completion_tokens / gen
        log.info("stream ttft=%.2fs total=%.2fs %d tok %.1f tok/s", stats.ttft or -1, stats.latency,
                 stats.completion_tokens, stats.tps)

    def sse(self, messages: Sequence[dict[str, str]], **kw: Any) -> Iterator[str]:
        """SSE-formatted stream for FastAPI StreamingResponse(media_type='text/event-stream')."""
        try:
            for d in self.chat_stream(messages, **kw):
                yield f"data: {json.dumps({'delta': d}, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    def chat_json(self, messages: Sequence[dict[str, str]], json_schema: dict[str, Any],
                  name: str = "response", **kw: Any) -> dict[str, Any]:
        """Structured output: response_format → fallback to text parsing → 1 repeat on error."""
        import jsonschema

        msgs = [dict(m) for m in messages]
        mode = self.cfg.json_mode
        schema_hint = "Ответь только валидным JSON по схеме: " + json.dumps(json_schema, ensure_ascii=False)
        meta = {"attempts": 0, "mode": mode, "errors": []}
        for attempt in (1, 2):
            meta["attempts"] = attempt
            extra: dict[str, Any] = dict(kw)
            if mode == "json_schema":
                extra["response_format"] = {"type": "json_schema",
                                            "json_schema": {"name": name, "strict": True, "schema": json_schema}}
            elif mode == "json_object":
                extra["response_format"] = {"type": "json_object"}
            send = msgs if mode == "json_schema" else [*msgs[:-1], {**msgs[-1], "content": msgs[-1]["content"] + "\n\n" + schema_hint}]
            try:
                text = self.chat(send, **extra).text
            except BadRequestError as e:  # server rejects response_format → text mode
                log.warning("response_format rejected (%s); fallback to prompt mode", e)
                mode, meta["mode"] = "prompt", "prompt"
                continue
            try:
                data = extract_json(text)
                jsonschema.validate(data, json_schema)
                self.last_json_meta = meta
                return data
            except (json.JSONDecodeError, jsonschema.ValidationError) as e:
                meta["errors"].append(str(e)[:200])
                log.warning("invalid JSON (attempt %d): %s", attempt, str(e)[:120])
                msgs = [*msgs, {"role": "assistant", "content": text[:2000]},
                        {"role": "user", "content": "Это невалидный JSON. " + schema_hint}]
        self.last_json_meta = meta
        raise LLMJSONError(f"invalid JSON after retry: {meta['errors']}")

    def thinking_active(self) -> bool:
        """True if the model still emits reasoning (reasoning_content / <think> / empty content at the limit)."""
        r = self.client.chat.completions.create(
            model=self.cfg.model, max_tokens=48, temperature=0,
            messages=[{"role": "user", "content": "Ответь одним словом: да"}],
            extra_body=self.cfg.extra_body or None)
        m, ch = r.choices[0].message, r.choices[0]
        extra = getattr(m, "model_extra", None) or {}
        content = m.content or ""
        return bool(extra.get("reasoning_content") or extra.get("reasoning") or "think>" in content
                    or (not content.strip() and ch.finish_reason == "length"))

    def health(self, ping: bool = True) -> dict[str, Any]:
        """Check server reachability, model availability and (optionally) a 1-token completion."""
        out: dict[str, Any] = {"ok": False, "server": False, "model_found": False, "models": [], "error": None}
        t0 = time.perf_counter()
        try:
            ids = [m.id for m in self.client.models.list().data]
            out.update(server=True, models=ids, model_found=any(self.cfg.model in i or i in self.cfg.model for i in ids))
            if ping and out["model_found"]:
                self.client.chat.completions.create(model=self.cfg.model, max_tokens=1, temperature=0,
                                                    messages=[{"role": "user", "content": "ping"}],
                                                    extra_body=self.cfg.extra_body or None)
            out["ok"] = out["model_found"]
        except Exception as e:  # noqa: BLE001
            out["error"] = f"{type(e).__name__}: {e}"
        out["latency_ms"] = round((time.perf_counter() - t0) * 1000)
        return out
