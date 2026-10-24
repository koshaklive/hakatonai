"""REL_THRESHOLD calibration: relevance distribution for answerable vs out-of-base queries + suggested threshold.

  python scripts/calibrate.py --mode hybrid [--gold gold.json] [--ood tests/ood.json]
Relevance scale depends on the mode (mixed dense/BM25 vs reranker sigmoid): calibrate for the mode you deploy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from evallib import MODES, ROOT, Settings, build_world, load_gold, pct, rank_of, searcher


def dist(name: str, x: list[float]) -> None:
    if not x:
        print(f"{name:<34} —")
        return
    print(f"{name:<34} n={len(x):<3} min={min(x):.3f} p10={pct(x, 10):.3f} p50={pct(x, 50):.3f} p90={pct(x, 90):.3f} max={max(x):.3f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="hybrid", choices=MODES)
    ap.add_argument("--gold", default=None)
    ap.add_argument("--ood", default=str(ROOT / "tests" / "ood.json"))
    ap.add_argument("--min-recall", type=float, default=0.95, help="share of answerable queries that must pass the threshold")
    a = ap.parse_args()
    cfg = Settings()
    w = build_world(cfg, dense=a.mode != "lexical", rerank=a.mode == "rerank")
    s = searcher(w, a.mode, anchors=False)
    good, missed, ood = [], [], []
    for g in load_gold(a.gold):
        r = s.search(g["q"], max_access=3)
        if r.method == "direct":
            continue  # relevance is a constant 1.0, never refused
        found = rank_of([h.point for h in r.hits if h.source == "hybrid"], set(g["expect"]))
        (good if found else missed).append(r.max_relevance)
    for q in json.loads(Path(a.ood).read_text(encoding="utf-8")):
        r = s.search(q, max_access=3)
        ood.append(r.max_relevance)

    print(f"mode={a.mode}  (шкала relevance зависит от режима)\n")
    dist("правильные (пункт найден в top-5)", good)
    dist("правильные, но пункт НЕ найден", missed)
    dist("вне базы", ood)
    answerable = good + missed  # a threshold must not cut off in-domain questions even when retrieval missed
    cand = sorted(set(answerable + ood))
    best = None
    for lo, hi in zip([0.0] + cand, cand + [1.01]):
        t = round((lo + hi) / 2, 3)
        tp = sum(x >= t for x in good)
        fp = sum(x >= t for x in ood)
        rec, prec = tp / max(1, len(good)), tp / max(1, tp + fp)
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        if rec >= a.min_recall and (best is None or (f1, t) > (best[0], best[1])):
            best = (f1, t, rec, prec)
    if best is None:
        print("\nПорог с recall ≥ %.2f не найден: распределения перекрываются слишком сильно." % a.min_recall)
        return
    f1, t, rec, prec = best
    below = [x for x in good if x < t]
    near_ood = max((x for x in ood if x < t), default=float("nan"))
    near_good = min((x for x in good if x >= t), default=float("nan"))
    print(f"\nпредложенный порог: REL_THRESHOLD={t:.3f}   (recall правильных={rec:.2f}, precision={prec:.2f}, F1={f1:.2f})")
    print(f"запас: ближайший внебазовый ниже порога = {near_ood:.3f}, ближайший правильный выше = {near_good:.3f}")
    print(f"правильных запросов ниже порога (ложные отказы): {len(below)} из {len(good)}")
    print(f"внебазовых ВЫШЕ порога (ложные ответы): {sum(x >= t for x in ood)} из {len(ood)}")
    if len(ood) < 20 or len(good) < 20:
        print(f"ВНИМАНИЕ: выборка мала (правильных {len(good)}, внебазовых {len(ood)}); порог считайте предварительным.")
    print("Порог выбирается ПОД КОНКРЕТНЫЙ режим и набор; после смены эмбеддера/режима пересчитать.")


if __name__ == "__main__":
    main()
