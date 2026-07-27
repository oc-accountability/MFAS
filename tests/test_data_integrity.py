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


# ------------------------------------------- account-level line items (stage 50)
@pytest.fixture(scope="module")
def lineitems():
    return load("lineitems.json")


@pytest.fixture(scope="module")
def validation():
    return load("lineitem_validation.json")


def test_line_items_reconcile_to_the_towns_own_totals(validation):
    """The load-bearing proof for the spending breakdown.

    Account detail must add up to the category totals the town publishes on its
    own Financial Summary pages. A breakdown that contradicts the summary would
    be worse than no breakdown at all.
    """
    assert validation["summary"]["unexplained"] == 0, (
        "unexplained reconciliation failures: "
        + repr([c for c in validation["checks"] if c["status"] == "UNEXPLAINED"]))


def test_the_headline_year_is_fully_verified(validation):
    """FY2027 budget is the year the site leads with; it must reconcile outright."""
    fy27 = [c for c in validation["checks"]
            if c["fiscal_year"] == 2027 and c["basis"] == "budget"]
    assert fy27, "no FY2027 budget checks ran"
    bad = [c for c in fy27 if not c["reconciles"]]
    assert not bad, f"FY2027 budget does not reconcile: {bad}"


def test_unverified_slices_are_explicitly_flagged(validation):
    """Every slice is labelled verified or not, so the site can refuse to present
    an unreconciled slice as if it were checked."""
    for s in validation["verified_slices"]:
        assert isinstance(s["verified"], bool), s
    for c in validation["checks"]:
        assert "verified" in c, c
        if not c["reconciles"]:
            assert c["verified"] is False, c
            assert c.get("explanation"), f"undisclosed variance: {c}"


def test_line_items_have_no_null_or_blank_dimensions(lineitems):
    C = {c: i for i, c in enumerate(lineitems["columns"])}
    for r in lineitems["rows"][:5000]:
        assert r[C["value"]] is not None
        for dim in ("fund", "department", "account"):
            assert str(r[C[dim]]).strip(), f"blank {dim} in {r}"
        assert isinstance(r[C["fiscal_year"]], int)
        assert r[C["basis"]]


def test_line_items_never_come_from_a_scanned_document(lineitems, documents):
    scans = {d["id"] for d in documents["documents"] if d.get("text_layer") == "scan"}
    C = {c: i for i, c in enumerate(lineitems["columns"])}
    bad = sorted({r[C["source_doc"]] for r in lineitems["rows"]
                  if r[C["source_doc"]] in scans})
    assert not bad, f"line items sourced from scanned documents: {bad}"


def test_line_item_totals_are_not_mixed_into_the_account_data(lineitems):
    """Subtotal rows must live in their own file — summing them with their own
    children would double every department."""
    C = {c: i for i, c in enumerate(lineitems["columns"])}
    bad = [r[C["account"]] for r in lineitems["rows"]
           if r[C["account"]].upper().endswith("TOTAL")]
    assert not bad, f"total rows present in the account data: {sorted(set(bad))[:10]}"


# --------------------------------------- audited statement (stage 60)
@pytest.fixture(scope="module")
def audited():
    return load("audited_general_fund.json")


def test_audited_statement_adds_up(audited):
    """Every column of the audited statement must sum to its printed total."""
    bad = [c for c in audited["arithmetic_checks"] if not c["reconciles"]]
    assert not bad, f"audited statement does not add up as parsed: {bad}"
    assert audited["arithmetic_checks"], "no arithmetic checks ran"


def test_audited_agrees_with_the_budget_document(audited):
    """Two independent documents, two independent parsers, one answer.

    The audited statement treats interfund transfers as other financing uses
    while the budget document counts them as expenses; adjusted for that, the
    FY2025 totals must agree. This is the closest thing the project has to an
    external check on its own extraction.
    """
    x = audited.get("cross_document_check")
    assert x, "cross-document check did not run"
    assert x["agree"], (
        f"audited {x['audited_total_expenditures']:,} vs budget-document "
        f"{x['adjusted']:,} (diff {x['difference']:+,})")


def test_audited_comes_from_the_digital_not_the_scanned_report(audited, documents):
    d = next(x for x in documents["documents"] if x["id"] == audited["source_doc"])
    assert d["text_layer"] == "digital", (
        "the audited figures must come from the digital twin, not the 61 MB scan")


# ------------------------------------- figures recovered from scans (stage 75)
@pytest.fixture(scope="module")
def ocr_statements():
    return load("ocr_statements.json")


def test_every_ocr_figure_was_proven_by_its_own_page(ocr_statements):
    """The rule that makes recognised figures publishable at all.

    A figure recovered from a scan is only shown when the individual lines on its
    page add up exactly to the total printed beside them. Recognition fails by
    altering a digit, and an altered digit breaks that sum — so this check is
    what stands between a scan and a wrong number on a public site.
    """
    for p in ocr_statements["published"]:
        assert p["extraction"] == "ocr-arithmetic-verified", p
        assert p["component_lines"] >= 2, (
            f"a 'total' derived from {p['component_lines']} line(s) is not a real check: {p}")
        assert p["source_page"] and p["source_doc"], p


def test_ocr_column_roles_are_confirmed_never_assumed(ocr_statements):
    """Charting the wrong column would be a silent, serious error, so a role is
    only recorded when the variance column proves the layout arithmetically."""
    for doc in ocr_statements["documents"]:
        if doc["status"] != "verified":
            continue
        if doc["column_roles"]:
            assert "variance" in doc["column_roles"].values(), doc
            assert "NOT confirmed" not in doc["column_roles_confirmed_by"], doc
    # a published figure may only claim a role if that document confirmed one
    confirmed = {d["document"] for d in ocr_statements["documents"] if d.get("column_roles")}
    for p in ocr_statements["published"]:
        if p.get("column_role"):
            assert p["source_doc"] in confirmed, p


def test_a_digital_original_always_beats_a_scan():
    """Where the same report exists digitally, the scan must not be used."""
    man = load("ocr_manifest.json")
    ocrd = {d["document"] for d in man["documents"]}
    assert "annual-financial-report-year-ended-june-30-2025" not in ocrd, (
        "the FY2025 scan was OCR'd even though its digital original is available")
    assert any("digital original" in s["reason"] for s in man["skipped"])
    assert "digital" in man["best_practice"].lower()


def test_index_counts_are_consistent(facts, documents):
    with open(REPO / "data" / "index.json", encoding="utf-8") as fh:
        idx = json.load(fh)
    assert idx["counts"]["facts"] == len(facts)
    assert idx["counts"]["documents"] == len(documents["documents"])


# ------------------------------------- the imported design warehouse (stage 85)
@pytest.fixture(scope="module")
def warehouse():
    return load("warehouse_county.json")


def test_imported_rows_keep_the_workbook_authors_schema(warehouse):
    """Her field names are the contract; renaming them would break the handoff."""
    for r in warehouse["rows"][:200]:
        for field in ("Entity_ID", "Fiscal_Year_ID", "Source_ID", "Confidence"):
            assert field in r, f"imported row lost the author's field {field}: {r}"
        assert r["Entity_ID"].startswith("ORG_"), r


def test_her_figures_are_verified_against_the_pages_she_cited(warehouse):
    """Imported figures are checked, not trusted. Any row whose citation names a
    page we hold must have every figure present on that page."""
    v = warehouse["verification"]
    assert v["rows_checked_against_source_pdf"] > 0, "verification did not run"
    assert v["figures_not_found_on_cited_page"] == 0, (
        f"figures absent from the page cited: {warehouse['mismatches'][:5]}")
    assert v["every_figure_found"] == v["rows_checked_against_source_pdf"]


def test_the_pipeline_never_writes_to_her_workbook():
    """s85 must read the design workbook, never modify it — she edits in Excel."""
    src = (REPO / "etl" / "s85_warehouse.py").read_text(encoding="utf-8")
    for banned in ("wb.save(", ".save(wbp", "openpyxl.Workbook("):
        assert banned not in src, f"s85 must not write to the design workbook ({banned})"
