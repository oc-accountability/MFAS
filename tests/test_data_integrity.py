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
    # The ONE permitted spreadsheet is the generated export (stage 101), which Amy asked for
    # so she has everything in her own schema. It is built from the datasets, not a source,
    # and it is small. Everything else with these extensions is a source document and some
    # exceed GitHub's hard 100 MB limit.
    GENERATED = {"data/exports/MFAS_Data_Warehouse.xlsx",
                 "data/exports/MFAS_Workbook_Tab_Map.xlsx"}
    bad = [f for f in out
           if (f.lower().endswith((".pdf", ".xlsx", ".xls", ".docx", ".zip"))
               or f.startswith("sources/"))
           and f not in GENERATED]
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


# ---------------------------------------------------------------------------
# The rate history and the utility calculator (s92, s93)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tco():
    return load("total_cost_of_ownership.json")


@pytest.fixture(scope="module")
def utility():
    return load("utility_rates.json")


def test_the_county_rate_never_comes_from_the_table_that_is_wrong(tco):
    """ACFR Table 6's county column has a misplaced decimal — it prints 0.086290
    where Table 5 prints 0.8629 for the same year. Published county rates must come
    from Table 5, and the ten-fold relationship must still hold, because if a future
    edition fixes the typo this test should fail loudly rather than double-correct."""
    err = tco["source_error"]
    assert err["verified_exactly_ten_for_all_years"] is True, (
        "the Table 5 / Table 6 relationship no longer holds — re-read both tables "
        "before trusting either")
    assert err["ratio_test"], "the ratio test did not run"
    for r in err["ratio_test"]:
        assert r["exactly_ten"], r


def test_rate_history_agrees_across_every_acfr_edition(tco):
    """The ten-year windows overlap, so most years are published in several reports.
    A disagreement means one of them was misread and nothing should be published."""
    s = tco["summary"]
    assert s["county_rate_disputes"] == [], s["county_rate_disputes"]
    assert s["town_rate_disputes"] == [], s["town_rate_disputes"]
    assert s["years_with_both_rates"] >= 10, s


def test_the_two_governments_rates_are_never_mixed_across_fiscal_years(tco):
    """Both governments publish two forward years, and taking one row per metric
    silently paired FY2026's county rate with FY2027's town rate. Every year that
    reports a combined rate must have both components from that same year."""
    for row in tco["series"]:
        if row.get("combined_rate") is None:
            continue
        assert row["county_rate"] and row["town_rate"], row
        assert abs(row["combined_rate"] - (row["county_rate"] + row["town_rate"])) < 1e-6, row
    years = [r["fiscal_year"] for r in tco["series"] if r.get("combined_rate")]
    assert 2027 in years, "FY2027 dropped out of the combined series"
    assert len(years) == len(set(years)), "a fiscal year appears twice"


def test_a_fixed_home_value_is_never_presented_as_a_bill_history(tco):
    """Applying a constant $400,000 across a revaluation year inverts the story, so
    the caveat has to travel with the data."""
    c = tco["caveat_fixed_home_value"]
    assert c["field"] == "rate_on_fixed_400k"
    assert "bill history" in c["what_it_is_NOT"].lower()
    assert "revaluation" in c["what_it_is_NOT"].lower()
    assert "tax_on_400k_home" not in json.dumps(tco), (
        "the old field name implied a bill; it must stay renamed")


def test_utility_rates_reproduce_every_increase_the_town_published(utility):
    """The whole reason a resident can enter their own consumption is that the rate
    structure reproduces the town's own stated increases. If it stops doing so, the
    structure was misread and no bill should be shown."""
    v = utility["verification"]
    assert v["all_stated_increases_reproduced"] is True, v["checks"]
    assert len(v["checks"]) >= 8, f"expected all eight stated increases, got {len(v['checks'])}"
    for c in v["checks"]:
        assert c["agrees"], c


def test_each_block_rate_set_is_internally_consistent(utility):
    """Block 1 must equal the threshold volume priced at the Block 2 rate. This is
    also what pairs the schedule's two unlabelled rate columns, so if it fails the
    current and recommended figures may have been mixed."""
    assert utility["rate_sets"], "no rate sets were extracted"
    for name, rs in utility["rate_sets"].items():
        for basis in ("current", "recommended"):
            b = rs[basis]
            implied = b["block2_per_1000"] * b["threshold_gallons"] / 1000.0
            assert abs(b["block1_charge"] - implied) <= 0.02, (name, basis, b)
        assert rs["recommended"]["block2_per_1000"] > rs["current"]["block2_per_1000"], (
            f"{name}: the recommended rate is not above the current one — the two "
            f"columns may have been swapped")


def test_the_utility_extraction_reported_no_problems(utility):
    assert utility["problems"] == [], utility["problems"]


def test_water_use_is_a_number_the_reader_controls():
    """Amy asked for this: her household uses ~9,000 gal/month and the page offered
    only the town's 2,000 and 4,000 examples. Guard against a regression to a
    two-option control."""
    app = (REPO / "assets" / "app.js").read_text(encoding="utf-8")
    assert "state.gallons" in app, "water use is no longer a numeric state value"
    assert "galNum" in app and "galSel" in app, "the custom-entry control is missing"
    assert "blockBill" in app, "the bill is no longer computed from the rate structure"


# ---------------------------------------------------------------------------
# Project as a real dimension (s94) — Amy's decision
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def projects():
    return load("projects.json")


def test_every_published_project_reconciles_to_its_printed_totals(projects):
    """Each project's tables print an AMOUNT row; the account rows must sum to it in
    every year column. Checked per column, so one bad column cannot hide inside a
    correct grand total."""
    assert projects["summary"]["projects_published"] > 0, "no projects were published"
    for p in projects["projects"]:
        assert p["reconciliation"], f"{p['project_name']}: no reconciliation was performed"
        for c in p["reconciliation"]:
            assert c["reconciles"], (p["project_name"], c)


def test_a_project_that_does_not_reconcile_is_never_published(projects):
    for p in projects["projects"]:
        assert p["published"] is True, p["project_name"]
    for w in projects["withheld"]:
        assert any(not c["reconciles"] for c in w["reconciliation"]), w


def test_every_project_carries_the_dimensions_that_make_it_useful(projects):
    """A project the reader cannot place in a fund, a department or a year is not a
    dimension — it is a label."""
    seen = set()
    for p in projects["projects"]:
        assert p["project_id"] and p["project_id"] not in seen, f"duplicate id: {p['project_id']}"
        seen.add(p["project_id"])
        assert p["fund"], p["project_name"]
        assert p["department"], p["project_name"]
        assert p["plan_window"], p["project_name"]
        assert p["source_pages"], p["project_name"]
        assert p["total_planned_cost"] is not None, p["project_name"]


def test_follow_on_capital_is_never_counted_as_recurring_cost(projects):
    """The town's Operating Budget Impact tables mix debt service with follow-on
    capital and transfers. Only debt service recurs; summing all three would overstate
    the ongoing commitment a capital decision creates."""
    for p in projects["projects"]:
        q = p.get("operating_budget_impact_quantified")
        if not q:
            assert p["creates_recurring_cost"] is False, p["project_name"]
            continue
        debt = sum(sum(r["amounts"]) for r in q["rows"] if r["recurring"])
        assert abs(q["recurring_portion"] - debt) < 1.0, (p["project_name"], q)
        assert p["creates_recurring_cost"] is (debt != 0), p["project_name"]
        if q["total"] is not None:
            assert q["recurring_portion"] <= q["total"] + 1.0, (p["project_name"], q)


def test_the_project_dimension_is_reported_as_filled(projects):
    """s88 measures this data against Amy's seven dimensions. Project was the one it
    could not fill; once s94 exists, s88 must not still report it missing."""
    mfas = load("mfas_conformance.json")
    assert mfas["dimension_coverage"]["Project"]["status"] == "available", (
        "s88 still reports Project as missing after s94 added it")
    assert mfas["summary"]["missing"] == 0, mfas["summary"]


def test_project_extraction_reported_no_problems(projects):
    assert projects["problems"] == [], projects["problems"]


def test_unnamed_funding_is_reported_not_disguised(projects):
    """The town's document prints "Empty Values" where a funding source label belongs,
    including for the whole of its largest project. The money is real and reconciles,
    so it is published — but the placeholder must never reach a reader as if it were
    the name of a funding source."""
    findings = projects.get("data_quality_findings", [])
    assert findings, "the unnamed-funding finding is missing"
    blob = json.dumps(projects["projects"])
    assert "Empty Values" not in blob, (
        "the source placeholder leaked into published project data")
    for p in projects["projects"]:
        for f in p["funding_by_source"]:
            assert "unnamed_in_source" in f, (p["project_name"], f)
            if f["unnamed_in_source"]:
                assert f["source"] == "Not named in the town's document", f


def test_recurring_cost_counts_maintenance_as_well_as_debt(projects):
    """Maintenance and utilities on a new asset recur exactly as debt service does.
    Counting only debt service understated the tail a capital decision leaves behind."""
    for p in projects["projects"]:
        q = p.get("operating_budget_impact_quantified")
        if not q:
            continue
        for r in q["rows"]:
            assert r["kind"] in {"debt service", "maintenance and utilities",
                                 "transfer to a capital fund", "further capital spending"}, r
            assert r["recurring"] is (r["kind"] in {"debt service",
                                                    "maintenance and utilities"}), r


# ---------------------------------------------------------------------------
# Tradeoffs — what was funded, what was declined (s95)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tradeoffs():
    return load("tradeoffs.json")


def test_request_lists_reconcile_to_their_printed_totals(tradeoffs):
    for lst in tradeoffs["request_lists"]:
        assert lst["reconciles"], (lst["fund"], lst["status"], lst["source_page"])


def test_declined_requests_are_not_double_counted(tradeoffs):
    """Each list is announced twice in the document — a bare banner and a caption naming
    the fund. Matching both counted every request twice and doubled the declined total."""
    names = [r["request"] for r in tradeoffs["declined"]]
    assert len(names) == len(set(names)), f"duplicated declined requests: {names}"
    fy27 = round(sum(r["fy2027"] or 0 for r in tradeoffs["declined"]), 2)
    assert abs(fy27 - tradeoffs["summary"]["fy2027_declined"]) < 1.0
    for lst in tradeoffs["request_lists"]:
        got = [i["request"] for i in lst["items"]]
        assert len(got) == len(set(got)), (lst["fund"], lst["status"], got)


def test_a_missing_form_is_never_reported_as_the_town_saying_nothing(tradeoffs):
    """Two different claims: the town's form states no consequence, versus no form was
    found. Conflating them puts a false statement about the town on the page."""
    for r in tradeoffs["declined"] + tradeoffs["funded"]:
        assert "justification_matched" in r, r["request"]
        assert r["justification_match_basis"], r["request"]
        if r["justification_matched"]:
            assert r["justification_match_basis"] != "no form found", r
        else:
            assert not r.get("impact_if_not_funded"), (
                "an unmatched request must not carry a consequence: " + r["request"])
    app = (REPO / "assets" / "app.js").read_text(encoding="utf-8")
    assert "No justification form was found" in app, (
        "the site no longer distinguishes a missing form from a silent one")


def test_declined_total_is_translated_using_the_towns_own_yield(tradeoffs):
    """Cents on the tax rate must come from the town's published revenue per cent, not
    an estimate, or the headline overstates what residents gave up."""
    rt = tradeoffs["summary"]["declined_in_resident_terms"]
    if "cents_on_the_tax_rate" not in rt:
        pytest.skip("no published revenue-per-cent figure available")
    per_cent = next(f["value"] for f in load("facts.json")["facts"]
                    if f["metric"] == "revenue_per_cent_of_tax_rate")
    # The stored value is rounded to three decimals on purpose; compare at that grain.
    assert abs(rt["cents_on_the_tax_rate"] - rt["dollars"] / per_cent) < 1e-3, rt
    assert "one cent" in rt["basis"].lower()


def test_tradeoff_caveats_state_what_this_cannot_show(tradeoffs):
    """A request never submitted leaves no trace, and these are recommendations rather
    than final decisions. Both must travel with the data."""
    blob = " ".join(tradeoffs["caveats"]).lower()
    assert "never" in blob and "submitted" in blob
    assert "recommend" in blob or "board" in blob
    assert tradeoffs["problems"] == [], tradeoffs["problems"]


# ---------------------------------------------------------------------------
# The initiative's newer analysis workbooks (s96)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def wbb():
    return load("workbook_b.json")


def test_the_pipeline_never_writes_to_her_analysis_workbooks():
    src = (REPO / "etl" / "s96_workbook_b.py").read_text(encoding="utf-8")
    for banned in ("wb.save(", ".save(", "openpyxl.Workbook("):
        assert banned not in src, f"s96 must not write to her workbooks ({banned})"


def test_her_tax_equivalent_arithmetic_is_verified_not_trusted(wbb):
    """A cents-per-$100 figure must equal its dollar amount over the penny assumption."""
    v = wbb["verification"]
    assert v["tax_equivalent_arithmetic"], "the arithmetic check did not run"
    assert v["tax_equivalent_all_consistent"] is True, [
        a for a in v["tax_equivalent_arithmetic"] if not a["agrees"]]
    for a in v["tax_equivalent_arithmetic"]:
        assert abs(a["her_cents"] - a["recomputed"]) < 0.01, a


def test_the_fy29_cliff_total_equals_its_parts(wbb):
    v = wbb["verification"]
    assert v["fy29_cliff_total_reconciles"] is True, (
        f"parts {v['fy29_cliff_parts_sum']} vs stated {v['fy29_cliff_total_stated']}")


def test_her_penny_assumption_matches_the_towns_published_figure(wbb):
    for item in wbb["tax_equivalent_exposure"]:
        if "penny_matches_published" in item:
            assert item["penny_matches_published"] is True, item


def test_a_crosscheck_never_compares_against_a_stale_projection(wbb):
    """The same fiscal year is often reported by several documents — this year's budget
    states FY2027 and last year's PROJECTED it. Comparing against whichever row came
    last accused her of a disagreement on fund balance that was this pipeline's own
    selection bug. Every reading must be carried so a comparison cannot look decisive
    when the documents themselves disagree."""
    checks = wbb["verification"]["cross_checks_against_this_pipeline"]
    assert checks, "no cross-checks ran"
    for c in checks:
        assert "all_readings_this_pipeline_holds" in c, c
        assert c["all_readings_this_pipeline_holds"], c
        # The chosen reading must be one this pipeline actually holds, and must not be a
        # projection when a firmer basis exists for the same year.
        bases = [r["basis"] for r in c["all_readings_this_pipeline_holds"]]
        if c["my_basis"] == "projected":
            assert all(b == "projected" for b in bases), (
                f"{c['her_label']}: compared against a projection while a firmer reading "
                f"exists: {c['all_readings_this_pipeline_holds']}")
    assert wbb["verification"]["cross_checks_all_agree"] is True, [
        c for c in checks if not c["agrees"]]


def test_a_budget_gap_is_never_shown_as_money_returned(wbb):
    """Her drivers sheet includes the projected deficit as a negative. Rendering it beside
    the drivers printed "$-422/yr on your home", which reads as money coming back when
    closing the gap would cost the reader."""
    app = (REPO / "assets" / "app.js").read_text(encoding="utf-8")
    assert "r.amount > 0" in app, (
        "the drivers list no longer excludes negative (gap) rows")
    assert any(r["amount"] and r["amount"] < 0 for r in wbb["material_change_drivers"]), (
        "no negative row present — if her sheet changed, re-check the guard is still needed")


def test_the_sales_tax_caveat_distinguishes_town_revenue_from_a_county_rate(wbb):
    """She asked about a county sales tax for schools. Her sheet holds the TOWN's local
    option sales tax revenue, which is a different thing."""
    assert wbb["sales_tax_history"], "no sales tax history imported"
    c = wbb["sales_tax_caveat"].lower()
    assert "town" in c and "county" in c and "not" in c
    for r in wbb["sales_tax_history"]:
        assert r["source"], r


def test_workbook_import_reported_no_problems(wbb):
    assert wbb["problems"] == [], wbb["problems"]


# ---------------------------------------------------------------------------
# Narrative context: who provides what, and the Finance Director's words (s97)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def context():
    return load("context.json")


def test_every_quotation_appears_verbatim_in_its_source(context):
    """A claim about what a named public official said is at least as damaging to get
    wrong as a figure, and cannot be corrected by re-reading a table. Each quote is
    checked against the document it is attributed to at build time."""
    q = context["finance_director_on_debt"]["quotes"]
    assert q, "no quotations were extracted"
    for item in q:
        assert item["verified_verbatim"] is True, item
        assert item["speaker"] and item["source_doc"] and item["context"], item


def test_the_finance_directors_ramp_up_example_adds_up(context):
    r = context["finance_director_on_debt"]["ramp_up_example"]
    if r is None:
        pytest.skip("the worked example is not present in this revision of the document")
    assert r["arithmetic_consistent"] is True, r
    assert r["ramp_by_year"][-1] == r["target_annual_debt_service"], r
    assert r["ramp_by_year"] == sorted(r["ramp_by_year"]), "a ramp-up must not decrease"


def test_both_governments_service_lists_are_present(context):
    w = context["who_provides_what"]
    assert len(w["Orange County"]) >= 5, w["Orange County"]
    assert len(w["Town of Hillsborough"]) >= 5, w["Town of Hillsborough"]
    # These are service names, not figures — a number here means the parse caught prose.
    for side in ("Orange County", "Town of Hillsborough"):
        for s in w[side]:
            assert not any(ch.isdigit() for ch in s), f"{side}: {s!r} looks like prose"
            assert len(s) <= 60, f"{side}: {s!r} looks like a sentence"


def test_context_extraction_reported_no_problems(context):
    assert context["problems"] == [], context["problems"]


# ---------------------------------------------------------------------------
# Revenue sources (s99), the open-questions register (s98), the structural
# question (s100)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def revenue():
    return load("revenue.json")


@pytest.fixture(scope="module")
def register():
    return load("questions.json")


@pytest.fixture(scope="module")
def structure():
    return load("structure.json")


def test_shares_are_only_published_where_the_parts_make_up_the_total(revenue):
    """A percentage of a total the components do not sum to is not a share. Budget years
    reconcile to the dollar; audited years differ because presentations differ."""
    for y in revenue["years"]:
        if y["shares_publishable"]:
            assert y["reconciles"], y["fiscal_year"]
            assert y["share_of_total"], y["fiscal_year"]
            assert abs(sum(y["share_of_total"].values()) - 100) < 0.5, y["fiscal_year"]
        else:
            assert y["share_of_total"] is None, (
                f"FY{y['fiscal_year']} publishes shares against a total its parts do not make")


def test_missing_component_detail_is_never_reported_as_a_discrepancy(revenue):
    """FY2018 carries only a sales tax figure. Treating that as a variance implied the
    town was out by $8.8M, when the detail simply is not in the sheet."""
    states = {y["fiscal_year"]: y["state"] for y in revenue["years"]}
    assert "components incomplete" in states.values(), (
        "no year is classed incomplete — if the sheet changed, re-check the guard")
    for y in revenue["years"]:
        if y["state"] == "components incomplete":
            assert y["components_populated"] < 5, y
            assert not y["reconciles"], y


def test_revenue_variance_is_reported_not_resolved(revenue):
    r = revenue["reconciliation"]
    assert r["years_reconciling"] >= 2, r
    assert "not resolved here" in r["finding"].lower() or "NOT resolved" in r["finding"]
    for c in r["checks"]:
        assert c["state"] in {"reconciles", "presentation difference",
                              "components incomplete"}, c


def test_every_register_item_has_an_owner_who_could_act(register):
    valid = set(register["owners"])
    assert valid, "no owners are defined"
    for r in register["register"]:
        assert r["owner"] in valid, r
        assert r["question"] and r["topic"], r
        assert r["status"] in {"open", "answered", "in progress", "awaiting upload"}, r
        if r["status"] == "answered":
            assert r.get("answer"), f"{r['id']} is answered with no answer recorded"


def test_the_register_keeps_answered_items(register):
    """A question that quietly vanishes is indistinguishable from one that was forgotten."""
    assert register["summary"]["answered"] > 0, "answered items are being dropped"
    assert register["summary"]["total"] == len(register["register"])
    assert (register["summary"]["open"] + register["summary"]["answered"]
            == register["summary"]["total"])


def test_the_register_has_a_readable_version():
    p = REPO / "docs" / "OPEN_QUESTIONS.md"
    assert p.exists(), "docs/OPEN_QUESTIONS.md was not generated"
    txt = p.read_text(encoding="utf-8")
    assert "Ask the Town" in txt and "Your decision" in txt
    assert "do not edit by hand" in txt


def test_the_structural_question_is_posed_and_not_answered(structure):
    """Amy asked for the insight highlighted AND said: "I don't want my opinion or me to
    tell anybody what is right or wrong." So the dataset must carry the measurements and
    an explicit statement of what it cannot settle — and must publish no cost comparison
    between the two structures."""
    assert structure["what_the_documents_cannot_answer"], "no limits are stated"
    assert len(structure["what_the_documents_cannot_answer"]) >= 3
    sep = structure["run_separately"]
    assert sep["county_equivalent"] is None, (
        "a county administrative figure appeared — half a comparison is worse than none")
    assert sep["county_note"]
    # Both boundary readings must be given rather than one presented as the answer.
    assert sep["administration_broad"]["total"] > sep["administration_narrow"]["total"]
    assert sep["administration_narrow"]["excludes"]
    blob = json.dumps(structure).lower()
    for loaded in ("wasteful", "should be merged", "should consolidate", "bloated"):
        assert loaded not in blob, f"the dataset editorialises: {loaded!r}"


def test_the_shared_service_is_described_including_what_cuts_against_the_thesis(structure):
    """Tax collection is NOT duplicated, and the town pays a third of the peer average.
    Anyone arguing duplicated cost has to see that, including the person who asked."""
    sh = structure["already_shared"]
    assert sh, "the shared-service finding is missing"
    assert sh["current_fee_pct_of_collections"] < sh["county_fee_study_peer_average_pct"]
    assert "not" in sh["why_this_matters_to_the_question"].lower()
    assert sh["source_page"], "the arrangement is published without a page cite"


def test_the_reading_burden_is_counted_not_asserted(structure):
    b = structure["reading_burden"]
    assert b["current_cycle_pages"] > 0 and b["current_cycle_documents"] > 0
    assert b["governments_a_resident_must_read"] == 2
    assert sum(v["pages"] for v in b["by_government"].values()) == b["current_cycle_pages"]
    assert "floors rather than totals" in b["note"]


def test_repo_media_stays_small():
    """The README film lives in the repo, which means every re-encode is committed forever —
    git history keeps the old blob whether or not the file is replaced. GitHub's hard limit is
    100MB per file and it warns at 50MB, but the real constraint is clone time for anyone who
    just wants the data. Keep the whole media budget well under a tenth of that."""
    media = REPO / "docs" / "media"
    if not media.is_dir():
        pytest.skip("no docs/media yet")
        return
    files = [(p.relative_to(REPO), p.stat().st_size) for p in media.iterdir() if p.is_file()]
    assert files, "docs/media exists but is empty"
    for rel, size in files:
        assert size < 8 * 1024 * 1024, f"{rel} is {size / 1e6:.1f} MB — re-encode it smaller"
    total = sum(s for _, s in files)
    assert total < 12 * 1024 * 1024, (
        f"docs/media totals {total / 1e6:.1f} MB across {len(files)} files — "
        f"a data repo should not carry more video than data")



def test_the_excel_export_keeps_amys_schema():
    """Amy asked for everything in the format of her own workbook. Her convention is that
    every Fact tab ends with Source_ID and Confidence, keyed by Fiscal_Year_ID — that is what
    makes a figure checkable rather than merely present. A future change must not quietly
    drop it."""
    openpyxl = pytest.importorskip("openpyxl")
    xl = REPO / "data" / "exports" / "MFAS_Data_Warehouse.xlsx"
    if not xl.exists():
        pytest.skip("export not built yet")
    # Existing on disk is not the same as being IN the repo. .gitignore carries *.xlsx, so
    # `git add -A` skipped this file silently: the README linked it, this test passed against
    # the local copy, and the published URL 404'd. Check what git actually tracks.
    tracked = subprocess.run(["git", "ls-files", "data/exports/MFAS_Data_Warehouse.xlsx"],
                             cwd=REPO, capture_output=True, text=True).stdout.strip()
    assert tracked, ("the export exists locally but is NOT tracked by git — check .gitignore, "
                     "the README links to it and the link will 404")
    wb = openpyxl.load_workbook(xl, read_only=True)
    try:
        assert "README" in wb.sheetnames and "Index" in wb.sheetnames
        assert "Source_Register" in wb.sheetnames
        fact_tabs = [n for n in wb.sheetnames if "Fact_" in n]
        assert len(fact_tabs) >= 6, fact_tabs
        for name in fact_tabs:
            ws = wb[name]
            header = None
            for row in ws.iter_rows(min_row=1, max_row=3, values_only=True):
                vals = [str(v) for v in row if v is not None]
                if "Confidence" in vals:
                    header = vals
                    break
            assert header, f"{name}: no header row carrying Confidence"
            assert "Source_ID" in header, f"{name}: no Source_ID column — a figure with no "\
                                          f"traceable source should not be in here"
    finally:
        wb.close()


def test_the_export_warns_that_it_is_generated():
    """It looks like a workbook, so somebody will type in it. The next build overwrites the
    file, so the warning has to be in the README tab, not only in the docs."""
    openpyxl = pytest.importorskip("openpyxl")
    xl = REPO / "data" / "exports" / "MFAS_Data_Warehouse.xlsx"
    if not xl.exists():
        pytest.skip("export not built yet")
    wb = openpyxl.load_workbook(xl, read_only=True)
    try:
        text = " ".join(str(c) for row in wb["README"].iter_rows(values_only=True)
                        for c in row if c)
    finally:
        wb.close()
    assert "GENERATED" in text.upper()
    assert "DESTROYED" in text.upper() or "OVERWRIT" in text.upper()



def test_the_tab_map_has_a_column_per_tab():
    """Amy asked for one workbook per row with each tab in its own column. A long/tidy table
    would be better for a machine and worse for the thing she wants to do, which is scan
    sixteen files left to right — so the wide shape is the deliverable, and it must stay wide."""
    openpyxl = pytest.importorskip("openpyxl")
    xl = REPO / "data" / "exports" / "MFAS_Workbook_Tab_Map.xlsx"
    if not xl.exists():
        pytest.skip("tab map not built yet")
    tracked = subprocess.run(["git", "ls-files", "data/exports/MFAS_Workbook_Tab_Map.xlsx"],
                             cwd=REPO, capture_output=True, text=True).stdout.strip()
    assert tracked, "the tab map is not tracked by git"
    wb = openpyxl.load_workbook(xl, read_only=True)
    try:
        ws = wb["Workbook_Tab_Map"]
        header = [c for c in next(ws.iter_rows(max_row=1, values_only=True)) if c]
        assert header[0] == "Workbook" and "Purpose" in header
        tab_cols = [h for h in header if str(h).startswith("Tab ")]
        assert len(tab_cols) >= 20, f"only {len(tab_cols)} tab columns — one workbook has 45"
        for name in ("Tab_Index", "Recurring_Tabs", "Decisions_Inventory"):
            assert name in wb.sheetnames, name
    finally:
        wb.close()
