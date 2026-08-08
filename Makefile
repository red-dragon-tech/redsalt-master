.PHONY: validate test status rdt-llm-eval

validate:
	python3 scripts/validate.py

test:
	python3 -m pytest tests -q

rdt-llm-eval:
	evals/rdt_llm/run_full_eval.sh

status:
	git status --short --branch
