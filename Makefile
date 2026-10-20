.PHONY: validate test status

validate:
	python3 scripts/validate.py

test:
	python3 -m pytest tests -q

status:
	git status --short --branch
