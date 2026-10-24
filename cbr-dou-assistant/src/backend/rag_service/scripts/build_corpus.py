"""Build ONE corpus file for the index: Instruction chunks (from rag-data-pipeline) + every .docx in a folder.

  python scripts/build_corpus.py --instruction data/instruction_chunks.json --docs input_docs --out data/corpus_chunks.json
Idempotent: re-run whenever a document is added or changed, then re-ingest (DATA_FILE=data/corpus_chunks.json).
Identical files (same sha256) are indexed once. Prints a report with warnings about suspicious source content.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.chunks import load_chunks, validate  # noqa: E402
from app.core.docx_chunks import docx_to_chunks  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruction", default="data/instruction_chunks.json")
    ap.add_argument("--docs", default="input_docs", help="folder with .docx files")
    ap.add_argument("--out", default="data/corpus_chunks.json")
    ap.add_argument("--version", default=None, help="corpus version label (default: the Instruction's version)")
    a = ap.parse_args()

    base = load_chunks(a.instruction)
    version = a.version or next(c["version"] for c in base)
    chunks, warnings, seen, prefixes = list(base), [], {}, set()
    print(f"Инструкция: {len(base)} чанков, версия {version}")
    for f in sorted(Path(a.docs).glob("*.docx")):
        if f.name.startswith("~$"):
            continue
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        if h in seen:
            print(f"  дубликат пропущен: {f.name} == {seen[h]}")
            continue
        seen[h] = f.name
        cs, w, kind = docx_to_chunks(f, version, prefixes)
        chunks += cs
        warnings += w
        print(f"  {kind:<9} {len(cs):>3} чанков  {f.name}")
    rep = validate(chunks)["report"]
    per_doc = collections.Counter(c.get("doc", "?") for c in chunks)
    print(f"\nИтого: {rep['indexed']} индексируемых, по документам: {dict(per_doc)}; висячих ссылок: {rep['dangling_refs']}")
    for w in warnings:
        print("  ВНИМАНИЕ:", w)
    Path(a.out).write_text(json.dumps(chunks, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"записано: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
