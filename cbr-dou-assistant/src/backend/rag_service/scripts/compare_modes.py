"""Compare lexical / dense / hybrid-RRF / hybrid+rerank on one gold set and pick a mode by data.

Measured on pure retrieval: anchors OFF, only 'hybrid' source counted (no related/anchor padding), direct-match queries
excluded (they bypass retrieval in every mode). Latency = full Searcher.search incl. query embedding (uncached), after warm-up.

  python scripts/compare_modes.py [--gold gold.json] [--repeats 3] [--max-p95-ms 2000] [--min-gain 0.02]
"""
from __future__ import annotations

import argparse
import statistics

from evallib import MODES, Settings, build_world, load_gold, metrics, pct, rank_of, searcher, timed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=None)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--max-p95-ms", type=float, default=2000, help="latency budget for the chosen mode")
    ap.add_argument("--min-gain", type=float, default=0.02, help="MRR gain a slower mode must show to be preferred")
    ap.add_argument("--modes", nargs="+", default=list(MODES), choices=MODES)
    a = ap.parse_args()
    cfg = Settings()
    w = build_world(cfg, dense=any(m != "lexical" for m in a.modes), rerank="rerank" in a.modes)
    gold = load_gold(a.gold)
    # drop direct-match queries once, using the lexical searcher
    s_lex = searcher(w, "lexical", anchors=False)
    gold = [g for g in gold if s_lex.search(g["q"], max_access=3).method != "direct"]

    res: dict[str, dict] = {}
    for mode in a.modes:
        s = searcher(w, mode, anchors=False)
        timed(s, gold[0]["q"])  # warm-up (model load, caches)
        ranks, lat = [], []
        for g in gold:
            ms = []
            for _ in range(a.repeats):
                r, t = timed(s, g["q"])
                ms.append(t)
            lat.append(statistics.median(ms))
            ranks.append(rank_of([h.point for h in r.hits if h.source == "hybrid"], set(g["expect"])))
        res[mode] = {**metrics(ranks), "p50": pct(lat, 50), "p95": pct(lat, 95)}

    print(f"gold: {len(gold)} запросов (без direct), repeats={a.repeats}, rerank_pool={cfg.rerank_pool}\n")
    print(f"{'mode':<10} {'hit@1':>6} {'hit@5':>6} {'MRR':>6} {'p50 ms':>8} {'p95 ms':>8}")
    for m, x in res.items():
        print(f"{m:<10} {x['hit1']:>6.2f} {x['hit5']:>6.2f} {x['mrr']:>6.3f} {x['p50']:>8.0f} {x['p95']:>8.0f}")

    # choice: best MRR within the latency budget; a slower mode must beat the cheaper one by --min-gain MRR (then hit@5)
    ok = [m for m in res if res[m]["p95"] <= a.max_p95_ms] or list(res)
    best = None
    for m in sorted(ok, key=lambda m: res[m]["p50"]):
        if best is None or res[m]["mrr"] - res[best]["mrr"] >= a.min_gain:
            best = m
    why = f"p95 ≤ {a.max_p95_ms:.0f} ms, прирост MRR ≥ {a.min_gain} относительно более быстрых режимов"
    print(f"\nвыбор: {best}  ({why})")
    if len(gold) < 30:
        print(f"ВНИМАНИЕ: в наборе {len(gold)} запросов; разница в одном запросе = {1/len(gold):.3f} hit@k. Выводы ориентировочные.")


if __name__ == "__main__":
    main()
