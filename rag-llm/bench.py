"""Benchmark of the LLM layer: TTFT, tok/s, JSON validity, refusals, VRAM @4k/8k.

Usage: python bench.py [--runs 1] [--skip-vram] [--out bench_results.json]
Test data is synthetic (not the real Instruction).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics as st
import subprocess
from typing import Any

import prompts as P
from llm import LLM, LLMError, StreamStats
from prompts.schemas import ROUTER_SCHEMA, extractor_schema

F = {
    "10.6": "Проект документа направляется на визирование в СЭД. Срок визирования — не более 3 рабочих дней со дня поступления.",
    "4.2": "Входящие документы регистрируются Центром документационного обеспечения в день поступления; поступившие после 16:00 — не позднее следующего рабочего дня.",
    "7.1": "Служебная записка подписывается руководителем структурного подразделения — автора записки.",
    "12.3": "Документы с грифом «Для служебного пользования» хранятся в запираемых шкафах и передаются только под подпись.",
    "15.2": "Срок исполнения поручения — 10 рабочих дней, если в поручении не указан иной срок.",
}
fr = lambda *ks: [{"point": k, "text": F[k]} for k in ks]  # noqa: E731

QA = [  # (question, fragments, expected points)
    ("Сколько времени даётся на визирование проекта?", fr("4.2", "10.6", "7.1"), {"10.6"}),
    ("Когда регистрируют письмо, пришедшее в 17:30?", fr("10.6", "4.2", "15.2"), {"4.2"}),
    ("Кто подписывает служебную записку?", fr("7.1", "12.3"), {"7.1"}),
    ("Как хранить документы с грифом ДСП?", fr("12.3", "10.6", "4.2"), {"12.3"}),
    ("Какой срок исполнения, если в поручении он не указан?", fr("15.2", "7.1", "10.6"), {"15.2"}),
]
REFUSE = [
    ("Сколько дней отпуска положено сотруднику?", fr("10.6", "4.2")),
    ("Как оформить командировочные расходы?", fr("7.1", "15.2")),
    ("Где в здании парковка для сотрудников?", fr("12.3", "10.6")),
]
MODULES = [("SZ", "Служебная записка", "записка, докладная, внутреннее обращение"),
           ("ORD", "Приказ", "приказ, распоряжение, назначить, утвердить"),
           ("LET", "Исходящее письмо", "письмо внешнему адресату, ответ организации"),
           ("PRT", "Протокол совещания", "протокол, совещание, поручения по итогам")]
ROUTE = [("Нужно написать начальнику отдела, что у нас сломался принтер", "SZ"),
         ("Надо ответить ООО «Ромашка» на их запрос", "LET"),
         ("Оформить итоги вчерашнего совещания у директора", "PRT")]
SZ_FIELDS = {"type": "object", "properties": {
    "addressee": {"type": ["string", "null"], "description": "кому адресован документ (должность или ФИО)"},
    "subject": {"type": ["string", "null"], "description": "тема документа"},
    "deadline": {"type": ["string", "null"], "description": "срок, ДД.ММ.ГГГГ"},
    "urgent": {"type": ["boolean", "null"], "description": "срочность"}},
    "required": ["addressee", "subject", "deadline", "urgent"], "additionalProperties": False}
EXTRACT = [("Служебка Иванову И.И. по поводу замены принтера, срочно, до 25.11.2026", {"addressee": "иванов", "deadline": "25.11.2026"}),
           ("Напиши Петровой про отпуск в декабре", {"addressee": "петров"}),
           ("Записка о закупке картриджей, адресат — начальник АХО", {"addressee": "ахо", "subject": "картридж"}),
           ("Нужна докладная директору, срок 01.12.2026, не срочно", {"addressee": "директор", "deadline": "01.12.2026"})]


def vram_mb() -> int | None:
    """Used GPU memory (MB) via nvidia-smi, or None."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], text=True)
        return int(out.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return None


def run_stream(llm: LLM, msgs: list[dict[str, str]]) -> StreamStats:
    """Stream one completion and return stats."""
    s = StreamStats()
    for _ in llm.chat_stream(msgs, stats=s):
        pass
    return s


def ctx_test(llm: LLM, target: int) -> dict[str, Any]:
    """Send a ~target-token prompt; report prompt tokens, TTFT, tok/s, VRAM."""
    filler = "Порядок визирования и согласования документов определяется настоящей Инструкцией. "
    msgs = [{"role": "user", "content": filler * (target * 6 // len(filler)) + "\nОтветь одним словом: ОК."}]
    s = StreamStats()
    for _ in llm.chat_stream(msgs, stats=s, max_tokens=16):
        pass
    return {"ctx": target, "prompt_tokens": s.prompt_tokens, "ttft": s.ttft, "tps": s.tps, "vram_mb": vram_mb()}


def table(rows: list[list[Any]], head: list[str]) -> str:
    """Plain-text table."""
    rows = [[("-" if c is None else f"{c:.2f}" if isinstance(c, float) else str(c)) for c in r] for r in [head, *rows]]
    w = [max(len(r[i]) for r in rows) for i in range(len(head))]
    line = lambda r: " | ".join(c.ljust(w[i]) for i, c in enumerate(r))  # noqa: E731
    return "\n".join([line(rows[0]), "-+-".join("-" * x for x in w), *map(line, rows[1:])])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--allow-thinking", action="store_true")
    ap.add_argument("--skip-vram", action="store_true")
    ap.add_argument("--out", default="bench_results.json")
    a = ap.parse_args()
    llm = LLM()
    h = llm.health()
    print("health:", h)
    if not h["ok"]:
        raise SystemExit("LLM server/model unavailable")
    if llm.thinking_active() and not a.allow_thinking:
        raise SystemExit(
            "Thinking is ON: the model burns max_tokens on reasoning.\n"
            "LM Studio -> My Models -> qwen3.5-9b (gear) -> Inference -> Prompt Template: add as the FIRST line\n"
            "  {%- set enable_thinking = false %}\n"
            "then Eject and Load Model again. Re-run (or use --allow-thinking to skip this check).")
    base_vram = vram_mb()
    ttfts: list[float] = []
    tpss: list[float] = []
    rows: list[list[Any]] = []
    json_total = json_valid = json_first = 0
    qa_ok = ref_ok = route_ok = ext_ok = 0

    for _ in range(a.runs):
        for q, frs, exp in QA:
            s = run_stream(llm, P.rag_messages(q, frs))
            cited = set(re.findall(r"\[п\.\s*([\d.]+?)\.?\]", s.text))
            ok = exp <= cited and cited <= {f["point"] for f in frs} and P.NO_ANSWER not in s.text
            qa_ok += ok
            ttfts.append(s.ttft or 0); tpss.append(s.tps)
            rows.append(["QA", q[:42], "OK" if ok else "FAIL", s.ttft, s.tps])
        for q, frs in REFUSE:
            s = run_stream(llm, P.rag_messages(q, frs))
            ok = s.text.strip().rstrip(".") == P.NO_ANSWER
            ref_ok += ok
            ttfts.append(s.ttft or 0); tpss.append(s.tps)
            rows.append(["REFUSE", q[:42], "OK" if ok else "FAIL", s.ttft, s.tps])
        mods = "\n".join(" | ".join(m) for m in MODULES)
        for q, code in ROUTE:
            json_total += 1
            try:
                d = llm.chat_json(P.json_messages("module_router", q, modules=mods), ROUTER_SCHEMA, "module_router")
                json_valid += 1; json_first += llm.last_json_meta["attempts"] == 1
                ok = d["module_code"] == code
            except LLMError:
                ok = False
            route_ok += ok
            rows.append(["ROUTE", q[:42], "OK" if ok else "FAIL", None, None])
        schema = extractor_schema(SZ_FIELDS)
        for q, exp in EXTRACT:
            json_total += 1
            try:
                d = llm.chat_json(P.json_messages("field_extractor", q, schema=json.dumps(SZ_FIELDS, ensure_ascii=False)), schema, "field_extractor")
                json_valid += 1; json_first += llm.last_json_meta["attempts"] == 1
                norm = lambda x: str(x or "").lower().replace("ё", "е")  # noqa: E731
                ok = all(v in norm(d["fields"].get(k)) for k, v in exp.items())
                if not ok:
                    print(f"  EXTRACT FAIL: {q!r}\n    expected~{exp}\n    got={json.dumps(d, ensure_ascii=False)}")
            except LLMError:
                ok = False
            ext_ok += ok
            rows.append(["EXTRACT", q[:42], "OK" if ok else "FAIL", None, None])

    print("\n" + table(rows, ["task", "case", "result", "ttft,s", "tok/s"]))
    n = a.runs
    summary = {
        "ttft_median_s": st.median(ttfts), "tps_median": st.median(tpss),
        "json_valid_%": 100 * json_valid / json_total, "json_first_try_%": 100 * json_first / json_total,
        "refusal_correct_%": 100 * ref_ok / (3 * n), "qa_correct_%": 100 * qa_ok / (5 * n),
        "route_correct_%": 100 * route_ok / (3 * n), "extract_correct_%": 100 * ext_ok / (4 * n),
    }
    vram = []
    if not a.skip_vram:
        vram = [ctx_test(llm, 4000), ctx_test(llm, 7000)]
    print("\n" + table([[k, v] for k, v in summary.items()], ["metric", "value"]))
    if vram:
        print("\nVRAM baseline (before requests), MB:", base_vram)
        print(table([[v["ctx"], v["prompt_tokens"], v["ttft"], v["tps"], v["vram_mb"]] for v in vram],
                    ["ctx target", "prompt tok", "ttft,s", "tok/s", "VRAM MB"]))
        print("NOTE: LM Studio reserves KV-cache at model load. For true 4k/8k VRAM, reload the model "
              "with Context Length 4096 / 8192 and run: python bench.py --runs 1 each time.")
    json.dump({"summary": summary, "ctx": vram, "rows": rows}, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
