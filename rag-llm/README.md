# rag-llm — LLM-слой для RAG-ассистента по Инструкции по ДОУ

```
rag-llm/
├─ .env.example        # все настройки; смена бэкенда = смена .env
├─ llm.py              # chat / chat_stream / sse / chat_json / health
├─ embeddings.py       # bge-m3 (CPU) + SQLite-кэш; Reranker (опц.)
├─ bench.py            # бенчмарк 15 запросов + VRAM 4k/8k
├─ prompts/
│  ├─ __init__.py      # load/render/rag_messages/json_messages, NO_ANSWER
│  ├─ schemas.py       # JSON-схемы
│  └─ v1/*.md          # rag_answer, clarify, module_router, field_extractor, draft_checker
└─ tests/mock_server.py  # офлайн-заглушка OpenAI API (проверка обвязки)
```

## Запуск
```
pip install -r requirements.txt
copy .env.example .env
# LM Studio: загрузить Qwen3.5-9B Q4_K_M, Developer -> Start Server (порт 1234)
python bench.py                 # полный прогон
python bench.py --runs 3 --skip-vram
```
Для честного VRAM@4k/8k: перезагрузи модель с Context Length 4096, затем 8192, и запускай `bench.py` каждый раз
(LM Studio резервирует KV-кэш при загрузке модели, а не по факту запроса).

## Как читать результаты
| Метрика | Норма | Тревога |
|---|---|---|
| ttft_median_s | < 2 с | > 5 с |
| tps_median | > 25 tok/s | < 12 tok/s |
| json_valid_% | 100 | < 95 |
| json_first_try_% | > 90 | < 80 (смени LLM_JSON_MODE) |
| refusal_correct_% | 100 | < 80 |
| qa_correct_% | >= 80 | < 60 |
| VRAM @8k | < 7.3 ГБ | >= 7.6 ГБ (своп в RAM, падение tok/s) |
Пороги — ориентиры, не измерения: на 4060 8 ГБ я бенчмарк не гонял.

## Особенности Qwen3.5-9B в LM Studio (источники: issue #1990 LM Studio, доки Qwen/Unsloth/Together; проверь у себя)
1. Thinking: у Qwen3.5 по умолчанию включён; у Unsloth-GGUF малых моделей (0.8–9B) выключен — зависит от GGUF/шаблона.
2. `/no_think` — механизм Qwen3, для Qwen3.5 не работает (поэтому `LLM_NO_THINK_SUFFIX=0`).
3. `chat_template_kwargs: {"enable_thinking": false}` через API LM Studio игнорируется (issue #1990, v0.4.15); vLLM/llama.cpp его принимают.
4. Рабочий способ в LM Studio: My Models -> модель -> Inference -> Prompt Template, первой строкой Jinja:
   `{%- set enable_thinking = false %}`, перезагрузить модель. Запасной: шаблон ChatML (может сломать tool-use/vision).
5. Рассуждения идут в `reasoning_content`, не в `content`; адаптер читает только `content` и вырезает `<think>…</think>` и одиночный `</think>`.
6. При включённом thinking и малом `max_tokens` `content` пустой (`finish_reason=length`) — адаптер пишет warning.
7. JSON: `response_format=json_schema` (strict) работает через grammar; при отказе сервера адаптер уходит в prompt-режим + парсинг + 1 повтор.
8. Сэмплинг в non-thinking по рекомендации Qwen: top_p 0.8, top_k 20 (задаётся в UI LM Studio); temperature держим 0.1.
9. В задании «BAGAI/bge-m3» — опечатка, верно `BAAI/bge-m3`.

## Если результаты плохие
| Симптом | Действие |
|---|---|
| tok/s < 12 или VRAM >= 7.6 ГБ @8k | контекст 8k->4k, KV-кэш q8_0, 5->3 фрагмента |
| json_first_try < 80% | `LLM_JSON_MODE=prompt`, temperature 0 |
| refusal < 80% / галлюцинации | temperature 0, фрагменты <= 3, Q5_K_M/Q6_K если влезает |
| после двух правок всё ещё плохо | запасная Qwen3-8B Q4_K_M (поддерживает /no_think), затем Qwen3-4B |
Критерий переключения: qa_correct < 60% ИЛИ refusal < 80% ИЛИ json_valid < 95% ИЛИ tps < 12 после двух правок.
