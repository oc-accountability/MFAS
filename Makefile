PY := ./.venv/bin/python
PORT ?= 8771

.PHONY: help venv etl test test-js verify serve clean check-sources

help:
	@echo "make venv    — create .venv and install etl/requirements.txt"
	@echo "make check-sources — which documents are here and which are not. Run this FIRST."
	@echo "make etl     — rebuild data/ from sources/ (needs the archive unpacked there)"
	@echo "make test-js — run the calculator's unit tests (node, no install needed)"
	@echo "make test    — run every gate: the calculator's, then the data's"
	@echo "make verify — THE RELEASE GATE: full rebuild + every test. Use this before publishing."
	@echo "make serve  — serve the site on http://127.0.0.1:$(PORT)/"

venv:
	python3 -m venv .venv
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -r etl/requirements.txt

# "Did I get all the documents?" answered in ten seconds instead of at the end of a
# fifteen-minute rebuild.
#
# The archive is not in the repository — 945 MiB, one file over GitHub's per-file limit,
# and several sent privately rather than published — so a fresh clone ships the recipe and
# the operator supplies the ingredients. Until this existed, the only way to find out
# whether the ingredients were complete was to run `make etl` and read what it could not
# find. That is the wrong shape for the person this project was handed to: run this first,
# and get a list of filenames rather than a number.
#
# Matches on sha256, never on filename — three "new" files the town sent turned out to be
# byte-identical to files already held under different names.
check-sources:
	@$(PY) scripts/check_sources.py

# Stages run in order; s90 validates and fails the build on bad data.
etl:
	$(PY) etl/s00_manifest.py
	$(PY) etl/s20_xlsx.py
	$(PY) etl/s30_budget_messages.py
	$(PY) etl/s40_household_impact.py
	$(PY) etl/s50_line_items.py
	$(PY) etl/s60_audited.py
	$(PY) etl/s70_ocr.py        # slow; resumable, cached under build/ocr
	$(PY) etl/s71_ocr_layout.py # recognise statement pages WITH word boxes (slow, cached)
	$(PY) etl/s75_ocr_statements.py
	# s61 must follow s60 AND s75: it cross-checks its digital readings against both,
	# and those checks are the reason its figures are believable. Run earlier and the
	# comparison files do not exist yet, so the checks silently skip — passing a build
	# while quietly dropping its own evidence.
	$(PY) etl/s61_audited_digital.py   # the town's digital audits
	# s62 needs s61's output to know which years are held digitally — a scan of such a
	# year is read for measurement but never published. s63 then compares the two
	# routes and FAILS THE BUILD on any disagreement, so it must follow both.
	$(PY) etl/s62_audited_scanned.py   # the same reader, applied to scans
	$(PY) etl/s63_ocr_ground_truth.py  # digital vs recognised, cell by cell
	$(PY) etl/s80_county.py
	$(PY) etl/s85_warehouse.py
	# s81 must follow s85: it verifies Amy's imported county workbook against the
	# audits, and s85 is what imports it.
	$(PY) etl/s81_county_acfr.py       # the county's own ACFRs, FY2018-FY2025 (slow)
	$(PY) etl/s88_mfas_dimensions.py
	$(PY) etl/s89_transfers.py
	$(PY) etl/s92_total_cost.py
	$(PY) etl/s93_utility_rates.py
	$(PY) etl/s94_projects.py
	$(PY) etl/s95_tradeoffs.py
	$(PY) etl/s96_workbook_b.py
	$(PY) etl/s97_context.py
	$(PY) etl/s99_revenue.py
	$(PY) etl/s100_structure.py
	$(PY) etl/s87_fact_financial.py   # the warehouse core — needs s50/s60/s75/s85/s99 outputs
	$(PY) etl/s98_questions.py
	# s90 MERGES the upstream fact files into facts.json and validates them, and the
	# Excel exports READ facts.json. Running the exports first — as this Makefile did
	# until 2026-07-31 — means the downloadable workbook carries the PREVIOUS run's
	# figures while the website carries the new ones, and a second build quietly makes
	# them agree again, so manual review never catches it. Merge and validate first,
	# then export from finalized data.
	$(PY) etl/s90_build.py
	$(PY) etl/s104_coverage.py         # measures the fill; must precede s101, which
	                                   # publishes the Coverage tabs into the export
	$(PY) etl/s102_workbook_audit.py
	$(PY) etl/s101_workbook.py
	$(PY) etl/s103_tab_map.py
	$(PY) etl/s105_acquisition_manifest.py   # how a third party assembles the sources

# The JavaScript half of the gate, added 2026-08-03.
#
# Until then the frontend had ZERO tests, and that is precisely why the out-of-town
# defect shipped: 111 Python tests passed while a $500,000 home outside the limits was
# shown $5,944 instead of $3,379, because the suite validates DATA and never executes
# the CALCULATOR. `assets/domain.js` exists to be runnable without a browser, and this
# is what runs it.
#
# node's own test runner, deliberately: this repo has no package.json and no
# node_modules, and a civic dataset anyone is invited to rebuild should not need a
# toolchain installed to check its arithmetic.
test-js:
	node --test 'tests/js/*.test.js'

# JS first: it is sub-second, and a broken calculation should not wait behind five
# seconds of data gates to say so.
test: test-js
	$(PY) -m pytest tests/ -q

# THE RELEASE GATE. `make etl` alone was the documented rebuild command and it never
# ran the tests, so a maintainer could rebuild, publish, and never learn that an
# integrity gate had failed — the 2026-07-31 audit called this out as the reason
# H-02 through H-04 could coexist with a green suite. Anything that publishes runs
# this, and CI runs it on every push.
# --no-print-directory: make's own "Entering directory '/Users/…/projects/MFAS'" lines are
# noise the operator cannot act on, and they put an absolute path on screen twice per
# recursive call. Found while recording a real run for the handoff guide — the take was
# unusable because it published the operator's own home directory, which is exactly what
# the privacy sweep exists to catch. The gate itself is unchanged.
verify:
	$(MAKE) --no-print-directory etl
	$(MAKE) --no-print-directory test
	@echo ""
	@echo "  VERIFIED — full rebuild and every integrity gate passed."


# Opening index.html from disk does not work — the browser blocks the data fetch.
serve:
	@echo "http://127.0.0.1:$(PORT)/"
	$(PY) -m http.server $(PORT) --bind 127.0.0.1

clean:
	rm -rf build/ .pytest_cache __pycache__ etl/__pycache__
