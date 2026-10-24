"""Search quality: hit@1 / hit@5 / MRR without and with anchors, who pulled each expected point, and out-of-base relevance.

  python scripts/eval_search.py [--gold gold.json] [--no-dense] [--mode hybrid|lexical|dense|rerank]
"""
from __future__ import annotations

import argparse
import collections
from pathlib import Path

from evallib import Settings, build_world, load_gold, metrics, rank_of, searcher  # noqa: F401 (sys.path set in evallib)
from app.search.tokenize import stemmer_name

# 6 queries that the instruction cannot answer (the full calibration set lives in tests/ood.json)
OOD = ["командировочные", "какая погода завтра во Франкфурте", "как приготовить борщ",
       "курс доллара к рублю сегодня", "как настроить VPN на домашнем роутере", "кто выиграл чемпионат мира по футболу"]


def table(rows: list[tuple]) -> None:
    w = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print(" | ".join(str(c).ljust(w[i]) for i, c in enumerate(r)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=None, help="gold json [{q, expect:[points]}]; default tests/gold_search.json")
    ap.add_argument("--no-dense", action="store_true")
    ap.add_argument("--mode", default="hybrid", choices=["lexical", "dense", "hybrid", "rerank"])
    a = ap.parse_args()
    cfg = Settings()
    mode = "lexical" if a.no_dense or not cfg.dense_enabled else a.mode
    w = build_world(cfg, dense=mode != "lexical", rerank=mode == "rerank")
    gold = load_gold(a.gold)
    s_off, s_on = searcher(w, mode, anchors=False), searcher(w, mode, anchors=True)

    rows = [("query", "expect", "method", "rank −anchors", "rank +anchors", "pulled by", "top (+anchors)", "rel")]
    r_off, r_on, r_core, who = [], [], [], collections.Counter()
    for g in gold:
        exp = set(g["expect"])
        a0, a1 = s_off.search(g["q"], max_access=3), s_on.search(g["q"], max_access=3)
        k0, k1 = rank_of([h.point for h in a0.hits], exp), rank_of([h.point for h in a1.hits], exp)
        kc = rank_of([h.point for h in a1.hits if h.source in ("direct", "hybrid")], exp)
        src = next((h.source for h in a1.hits if h.point in exp), "-")
        r_off.append(k0); r_on.append(k1); r_core.append(kc); who[src] += 1
        rows.append((g["q"][:50], ",".join(sorted(exp)), a1.method, k0 or "-", k1 or "-", src,
                     " ".join(f"{h.point}[{h.source[0]}]" for h in a1.hits), f"{a1.max_relevance:.2f}"))
    table(rows)

    def line(name: str, ranks: list) -> str:
        m = metrics(ranks)
        return f"{name:<24} hit@1={m['hit1']:.2f}  hit@5={m['hit5']:.2f}  MRR={m['mrr']:.3f}  (n={m['n']})"
    print(f"\nmode={mode} stemmer={stemmer_name()} dense={'on' if mode != 'lexical' else 'off'}")
    print(line("без якорей", r_off))
    print(line("с якорями", r_on))
    print(line("с якорями, только core", r_core))
    print("кто вытащил ожидаемый пункт:", dict(who))

    print("\n--- запросы вне базы: max relevance (порог REL_THRESHOLD=%.2f) ---" % cfg.rel_threshold)
    rows = [("query", "method", "hits", "max_rel", "top", "отказ при пороге")]
    for q in OOD:
        r = s_off.search(q, max_access=3)
        top = r.hits[0].point if r.hits else "-"
        rows.append((q, r.method, len(r.hits), f"{r.max_relevance:.3f}", top,
                     "да" if r.method != "direct" and r.max_relevance < cfg.rel_threshold else "нет"))
    table(rows)


if __name__ == "__main__":
    main()
