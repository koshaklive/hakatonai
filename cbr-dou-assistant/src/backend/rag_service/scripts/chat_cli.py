"""Интерактивный чат в консоли: python scripts/chat_cli.py [--debug]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evallib import Settings, build_world, searcher  # noqa: E402
from app.chat import ChatService  # noqa: E402
from llm_layer.llm import LLM  # noqa: E402

debug = "--debug" in sys.argv
cfg = Settings()
print("Загрузка индекса и модели (первый запуск ~30 с)...")
svc = ChatService(cfg, searcher(build_world(cfg, dense=True), "hybrid", anchors=True), LLM())
print("Готово. Пустая строка или Ctrl+C для выхода.\n")

while True:
    try:
        q = input("Вы: ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if not q:
        break
    r = svc.answer(q)
    if r.refused:
        print(f"\nБот: В базе знаний информации нет, обратитесь в Департамент ДОУ. (причина: {r.reason}, relevance {r.max_relevance:.2f})\n")
    else:
        print(f"\nБот: {r.answer}\n")
        print("Источники:", ", ".join(f"п. {s['point']} ({s['relevance']:.0%})" for s in r.sources))
        if debug:
            print("Контекст:", " ".join(r.context))
    print(f"[{r.timings_ms}, вызовов LLM: {r.llm_calls}]\n" if debug else "")