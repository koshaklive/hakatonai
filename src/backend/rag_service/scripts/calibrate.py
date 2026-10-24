"""Threshold calibration from eval/gold.json (positives) and eval/ood.json (OOD negatives) → data/calibration.json.
  python scripts/calibrate.py [--mode hybrid] [--out data/calibration.json]"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evallib import Settings, build_world, pct, rank_of, searcher, timed
from app.core.search import passes_hybrid_filter, query_evidence

def _q(x: object) -> str:
    if isinstance(x, str):
        return x
    return x.get("query") or x.get("q") or x.get("question") or x.get("message") or x.get("text")


def _exp(x: dict) -> set[str]:
    return set(map(str, x.get("expect") or x.get("expected") or x.get("points")
                    or x.get("expected_points") or []))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="hybrid")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    cfg = Settings()
    gold = json.loads(Path(cfg.gold_file).read_text(encoding="utf-8"))
    ood = json.loads(Path(cfg.ood_file).read_text(encoding="utf-8"))
    s = searcher(build_world(cfg, dense=a.mode != "lexical", rerank=a.mode == "rerank"), a.mode)
    pos, neg = [], []
    gold_results = []
    for g in gold:
        r, _ = timed(s, _q(g))
        matched = rank_of([h.point for h in r.hits], _exp(g)) is not None
        if matched:
            pos.append(r.max_relevance)
        gold_results.append((g, r, matched))
    for o in ood:
        r, _ = timed(s, _q(o))
        neg.append(r.max_relevance)
    pos_low, neg_high = pct(pos, 5), pct(neg, 95)
    margin = pos_low - neg_high
    if margin >= cfg.gray_margin:
        thr = (pos_low + neg_high) / 2
        low = high = thr
    else:
        lo, hi = min(pos_low, neg_high), max(pos_low, neg_high)
        if hi - lo < cfg.gray_margin:
            mid = (lo + hi) / 2
            lo, hi = mid - cfg.gray_margin / 2, mid + cfg.gray_margin / 2
        low, high = max(lo, 0.0), hi
        thr = (low + high) / 2
    classes = {"below_low": 0, "gray_zone": 0, "above_high": 0}
    filtered_classes = {"below_low": 0, "gray_zone": 0, "above_high": 0}
    false_rejects = 0
    for g, r, _ in gold_results:
        score = r.max_relevance
        relevance_class = "below_low" if score < low else "gray_zone" if score < high else "above_high"
        classes[relevance_class] += 1
        dense_score, bm25_score, overlap = query_evidence(_q(g), r.hits, s.index.abbrevs)
        accepted = (r.method == "direct" or
                    passes_hybrid_filter(dense_score, bm25_score, overlap,
                                         dense_min=cfg.dense_min_relevance,
                                         bm25_min=cfg.bm25_min_relevance,
                                         overlap_min=cfg.keyword_overlap_min) or
                    low <= score < high)
        if accepted:
            filtered_classes[relevance_class] += 1
        elif _exp(g) and str(g.get("category", "")).lower() != "ood":
            false_rejects += 1
    positive_gold = sum(bool(_exp(g)) and str(g.get("category", "")).lower() != "ood" for g in gold)
    res = {"mode": a.mode, "n_pos": len(pos), "n_ood": len(neg), "pos_p5": round(pos_low, 4),
           "ood_p95": round(neg_high, 4), "margin": round(margin, 4), "gray_zone": margin < cfg.gray_margin,
           "threshold": round(thr, 4), "gray_low": round(low, 4), "gray_high": round(high, 4),
           "n_positive_gold": positive_gold,
           "gold_false_rejects": false_rejects,
           "relevance_distribution_before_filter": classes,
           "relevance_distribution_after_filter": filtered_classes}
    out = Path(a.out or cfg.calibration_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())