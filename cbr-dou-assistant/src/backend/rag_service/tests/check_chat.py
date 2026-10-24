"""Three /chat acceptance checks. Default: scripted fake LLM (verifies retrieval + refusal + call counting);
--live: real LLM from .env (also checks the wording of the answer).

  python tests/check_chat.py [--live] [--mode hybrid]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from evallib import Settings, build_world, searcher  # noqa: E402
from app.chat import ChatService  # noqa: E402


class CountingLLM:
    """Wraps a real LLM or, without one, echoes a cited answer built from the first context point."""
    def __init__(self, real=None) -> None:
        self.real, self.calls, self.raws = real, 0, []

    def chat(self, messages, **kw):
        self.calls += 1
        if self.real:
            res = self.real.chat(messages, **kw)
            self.raws.append(res.text)
            return res
        ctx = messages[-1]["content"]
        first = ctx.split("[п. ", 1)[1].split("]", 1)[0]
        return SimpleNamespace(text=f"(заглушка LLM) см. [п. {first}]")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--mode", default="hybrid")
    a = ap.parse_args()
    cfg = Settings()
    w = build_world(cfg, dense=a.mode != "lexical", rerank=a.mode == "rerank")
    real = None
    if a.live:
        from llm_layer.llm import LLM
        real = LLM()
    llm = CountingLLM(real)
    svc = ChatService(cfg, searcher(w, a.mode, anchors=True), llm)
    print(f"mode={a.mode} llm={'live' if a.live else 'fake'} REL_THRESHOLD={cfg.rel_threshold}\n")
    fails = 0

    def show(title: str, res, ok: bool, extra: str = "") -> None:
        nonlocal fails
        fails += not ok
        print(f"[{'OK' if ok else 'FAIL'}] {title}\n  query: {res.query}\n  context: "
              + " ".join(res.context)
              + f"\n  refused={res.refused} reason={res.reason} max_rel={res.max_relevance:.2f} llm_calls={res.llm_calls} {extra}")
        print("  timings_ms:", res.timings_ms)
        print("  sources:", res.sources)
        if not res.refused:
            print("  answer:", res.answer.replace("\n", " "))
        if a.live and llm.raws and not res.refused:
            raw = llm.raws[-1]
            print("  raw LLM:", raw.replace("\n", " "))
            print("  postcheck changed answer:", raw.strip() != res.answer.strip())
        print()

    def has(res, point: str) -> bool:
        return point in [c.split("[")[0] for c in res.context]

    q1 = "Срок исполнения «до 14 октября» и «не позднее 14 октября»: какой последний день в каждом случае?"
    r1 = svc.answer(q1)
    ok1 = has(r1, "6.4") and (not a.live or "13" in r1.answer)
    show("1. «до» / «не позднее»: п. 6.4 в контексте", r1, ok1)

    q2 = "Какой срок рассмотрения приказа по основной деятельности?"
    r2 = svc.answer(q2)
    ok2 = has(r2, "10.3") and (not a.live or "10 рабочих дней" in r2.answer)
    show("2. срок рассмотрения приказа: п. 10.3 → «10 рабочих дней»", r2, ok2)

    before = llm.calls
    r3 = svc.answer("командировочные")
    show("3. отказ на «командировочные» без вызова LLM", r3, r3.refused and r3.reason == "below_threshold" and llm.calls == before)
    if cfg.rel_threshold == 0.0:
        print("  подсказка: REL_THRESHOLD=0.0 — порог не откалиброван (scripts/calibrate.py)")
    print("итого:", "все проверки пройдены" if not fails else f"провалено: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
