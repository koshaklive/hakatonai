.PHONY: install run eval offline-check

install:
	python -m pip install -r requirements.txt

run:
	python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000

eval:
	python eval/run_eval.py --gold eval/gold.json

offline-check:
	python eval/run_eval.py --offline-check --gold eval/gold.json
