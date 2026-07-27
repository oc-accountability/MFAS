"""Integrity gates for the published data.

These are the checks that stop this project from doing the one thing it must never
do: publish a confidently wrong number about a real public official.

Run with: make test
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DATASETS = REPO / "data" / "datasets"

# Extraction methods fit to publish. Anything read off a scanned page's OCR
# layer is deliberately absent — see docs/EXTRACTION_NOTES.md.
PUBLISHABLE = {"digital-text", "transcribed", "derived", "stated"}


def load(name):
    with open(DATASETS / name, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def facts():
    return load("facts.json")["facts"]


@pytest.fixture(scope="module")
def documents():
    return load("documents.json")


@pytest.fixture(scope="module")
def metrics():
    return load("metrics.json")["metrics"]


# --------------------------------------------------------------- repo hygiene
def test_no_source_documents_are_tracked():
    """Source PDFs/spreadsheets must never be committed.

    Two of them exceed GitHub's hard 100 MB per-file limit, so a stray `git add -f`
    would produce a repo that cannot be pushed at all.
    """
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                         text=True).stdout.split()
    bad = [f for f in out
           if f.lower().endswith((".pdf", ".xlsx", ".xls", ".docx", ".zip"))
           or f.startswith("sources/")]
    assert not bad, f"source documents must not be tracked: {bad}"


def test_no_tracked_file_is_near_the_github_limit():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                         text=True).stdout.split()
    big = []
    for f in out:
        p = REPO / f
        if p.is_file() and p.stat().st_size > 50 * 1024 * 1024:
            big.append((f, p.stat().st_size))
    assert not big, f"tracked files over 50 MB: {big}"


# ------------------------------------------------------------ fact integrity
def test_every_fact_cites_a_known_document(facts, documents):
    ids = {d["id"] for d in documents["documents"]}
    missing = sorted({f["source_doc"] for f in facts if f.get("source_doc") not in ids})
    assert not missing, f"facts cite unknown documents: {missing}"


def test_every_fact_uses_a_registered_metric(facts, metrics):
    unknown = sorted({f["metric"] for f in facts if f["metric"] not in metrics})
    assert not unknown, f"unregistered metrics: {unknown}"


def test_no_fact_has_a_null_value(facts):
    """A blank rendered as 0 on a chart reads as a factual claim of zero."""
    bad = [f for f in facts if f.get("value") is None]
    assert not bad, f"{len(bad)} facts have null values"


def test_units_match_the_registry(facts, metrics):
    bad = [(f["metric"], f["unit"], metrics[f["metric"]]["unit"])
           for f in facts if f["unit"] != metrics[f["metric"]]["unit"]]
    assert not bad, f"unit mismatches vs registry: {set(bad)}"


def test_tax_rates_are_never_labelled_as_percent(facts):
    """51.3 cents per $100 is 0.513%, not 51.3%. Mislabelling overstates it ~19.5x."""
    bad = [f for f in facts
           if "tax_rate" in f["metric"] and "cent" in f["metric"].replace("_", "")
           and f["unit"] == "percent"]
    assert not bad, f"cents-per-$100 metrics marked as percent: {bad}"


# ------------------------------------------------- the scanned-document gate
def test_no_published_fact_comes_from_a_scanned_document(facts, documents):
    """The load-bearing check.

    The FY2018-FY2025 annual financial reports are scans whose OCR text layer
    transposes digits (4,610,003 -> 460,100,3). Nothing published may originate
    there without a human having transcribed it from the page image.
    """
    scans = {d["id"] for d in documents["documents"] if d.get("text_layer") == "scan"}
    offenders = [(f["metric"], f["source_doc"], f["extraction"])
                 for f in facts
                 if f["source_doc"] in scans and f["extraction"] != "transcribed"]
    assert not offenders, (
        "facts sourced from scanned documents without transcription: " + repr(offenders))


def test_every_extraction_method_is_publishable(facts):
    bad = sorted({f["extraction"] for f in facts if f["extraction"] not in PUBLISHABLE})
    assert not bad, f"unpublishable extraction methods present: {bad}"


def test_scans_are_flagged_unextractable(documents):
    bad = [d["id"] for d in documents["documents"]
           if d.get("text_layer") == "scan" and d.get("values_extractable")]
    assert not bad, f"scanned documents marked extractable: {bad}"


def test_scans_carry_an_extraction_warning(documents):
    bad = [d["id"] for d in documents["documents"]
           if d.get("text_layer") == "scan" and not d.get("extraction_warning")]
    assert not bad, f"scanned documents missing extraction_warning: {bad}"


# ----------------------------------------------------------- derived datasets
def test_projection_comparisons_have_at_least_two_readings():
    for c in load("projections.json")["comparisons"]:
        assert len(c["readings"]) >= 2, c
        vals = [r["value"] for r in c["readings"]]
        assert c["min"] == min(vals) and c["max"] == max(vals), c


def test_request_scoreboard_arithmetic():
    r = load("requests.json")
    s = r["summary"]
    assert s["data_cells_provided"] == sum(t["cells_provided"] for t in r["tables"])
    assert s["data_cells_requested"] == sum(t["cells_expected"] for t in r["tables"])
    assert s["data_cells_provided"] <= s["data_cells_requested"]
    counts = s["tables_unanswered"] + s["tables_partial"] + s["tables_answered"]
    assert counts == s["tables_requested"]
    for t in r["tables"]:
        assert t["cells_provided"] <= t["cells_expected"], t["sheet"]


def test_interpreted_spreadsheet_values_are_auditable():
    """Where the ETL interpreted an ambiguous cell, it must keep the raw text and
    show the arithmetic holds."""
    for p in load("requests.json")["projects_with_cost_changes"]:
        assert p["raw_cells"], p["project"]
        if p.get("note"):
            assert p["arithmetic_consistent"] is True, (
                f"{p['project']}: interpreted a cell but the row does not reconcile")


def test_documents_summary_matches_the_document_list(documents):
    docs = documents["documents"]
    s = documents["summary"]
    assert s["unique_documents"] == len(docs)
    assert s["pdf_scanned_ocr"] == sum(1 for d in docs if d.get("text_layer") == "scan")
    assert s["pdf_digital_text"] == sum(1 for d in docs if d.get("text_layer") == "digital")


def test_index_counts_are_consistent(facts, documents):
    with open(REPO / "data" / "index.json", encoding="utf-8") as fh:
        idx = json.load(fh)
    assert idx["counts"]["facts"] == len(facts)
    assert idx["counts"]["documents"] == len(documents["documents"])
