# DOU RAG service — stage 1 (indexing + /search)

Put your accepted `llm_layer/` (llm.py, embeddings.py, prompts/) next to `app/`.

    pip install -r requirements.txt
    cp .env.example .env
    python -m app.ingest --file data/instruction_chunks.json      # idempotent; --no-dense for BM25 only
    AUTH_MODE=dev uvicorn app.api.main:app --port 8000            # dev: skips JWT check
    python scripts/eval_search.py                                 # hit@1 / hit@5 / MRR on tests/gold_search.json
    python -m pytest tests                                        # (tests are plain asserts)

| Endpoint | Purpose |
|---|---|
| GET /health | PocketBase, LLM, index version, chunk count, stemmer, dense on/off |
| POST /ingest {version_id} | 202, runs in background; admin/methodologist JWT or `X-Ingest-Key` |
| POST /search {query, top_k, filters} | access_level taken from the verified JWT |
| GET /chunks/{id} | full point text (parts glued) |
| GET /versions | registry of indexed versions |
| POST /modules/route, /modules/fill | 501, contract only |

Anchors and related refs: edit `anchors.yaml`, no code changes.
