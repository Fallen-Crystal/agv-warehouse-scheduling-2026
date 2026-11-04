PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
RUFF ?= $(PYTHON) -m ruff
COVERAGE ?= $(PYTHON) -m coverage

.PHONY: test lint format-check coverage check

test:
	$(PYTHON) -m unittest discover -s tests -t .

lint:
	$(RUFF) check src tests scripts

format-check:
	$(RUFF) format --check src tests scripts

coverage:
	$(COVERAGE) run --source=src/agv -m unittest discover -s tests -t .
	$(COVERAGE) report --fail-under=80

check: lint format-check test
