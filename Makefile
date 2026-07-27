PY := ./.venv/bin/python
PORT ?= 8771

.PHONY: help venv etl test serve clean

help:
	@echo "make venv   — create .venv and install etl/requirements.txt"
	@echo "make etl    — rebuild data/ from sources/ (needs the archive unpacked there)"
	@echo "make test   — run the data integrity gates"
	@echo "make serve  — serve the site on http://127.0.0.1:$(PORT)/"

venv:
	python3 -m venv .venv
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -r etl/requirements.txt

# Stages run in order; s90 validates and fails the build on bad data.
etl:
	$(PY) etl/s00_manifest.py
	$(PY) etl/s20_xlsx.py
	$(PY) etl/s30_budget_messages.py
	$(PY) etl/s40_household_impact.py
	$(PY) etl/s50_line_items.py
	$(PY) etl/s60_audited.py
	$(PY) etl/s70_ocr.py        # slow; resumable, cached under build/ocr
	$(PY) etl/s75_ocr_statements.py
	$(PY) etl/s90_build.py

test:
	$(PY) -m pytest tests/ -q

# Opening index.html from disk does not work — the browser blocks the data fetch.
serve:
	@echo "http://127.0.0.1:$(PORT)/"
	$(PY) -m http.server $(PORT) --bind 127.0.0.1

clean:
	rm -rf build/ .pytest_cache __pycache__ etl/__pycache__
