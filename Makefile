# Convenience targets. Everything also works as plain commands (see RUNBOOK.md).
PY ?= python
VENV ?= .venv
BREW_PY ?= $(shell brew --prefix python@3.12 2>/dev/null)/bin/python3.12

.PHONY: setup cpp check test run report clean

setup:                      ## create the venv and install the package
	$(BREW_PY) -m venv $(VENV)
	$(VENV)/bin/python -m pip install --upgrade pip
	$(VENV)/bin/python -m pip install -r requirements.txt
	$(VENV)/bin/python -m pip install -e .

cpp:                        ## build the native SEAL driver
	bash scripts/build_cpp.sh

check:                      ## report available backends
	$(PY) scripts/00_check_env.py

test:                       ## fast smoke tests
	$(PY) -m pytest

run:                        ## full pipeline (see RUNBOOK.md for variables)
	bash scripts/run_all.sh

report:
	$(PY) scripts/05_make_report.py

clean:
	rm -rf cpp/build artifacts/embeddings/*.npz artifacts/results/*.json \
	       reports/figures/*.png reports/results.md .pytest_cache
