"""Integrity gates for the published data.

These are the checks that stop this project from doing the one thing it must never
do: publish a confidently wrong number about a real public official.

Run with: make test
"""
from __future__ import annotations

import collections
import functools
import html as html_mod
import json
import os
import re
import shutil
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

    One of them exceeds GitHub's hard 100 MiB per-file limit (a second sits at
    98 MiB), so a stray `git add -f` would produce a repo that cannot be pushed.
    check=True and the non-empty assertion matter: a failing or absent git would
    otherwise return no files and pass this test vacuously.
    """
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                         text=True, check=True).stdout.split()
    assert out, "git ls-files returned nothing — this test cannot see the repo"
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
                         text=True, check=True).stdout.split()
    assert out, "git ls-files returned nothing — this test cannot see the repo"
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


# The ten scanned reports, by id. Every scan gate in this file keys off the
# text_layer labels — and mutation testing showed that relabelling all ten to
# "digital" turned every gate green with nothing else failing. The labels
# themselves need an anchor: these ids are stable (they name the documents), so
# a manifest-regeneration bug that dropped or flipped them fails loudly here
# instead of shipping.
KNOWN_SCAN_IDS = {
    # Added 2026-07-30, and the reason matters more than the entries. The email of
    # 2026-07-29 asked Amy for DIGITAL audits for FY2018-FY2020, because those years
    # hold 31, 28 and 197 facts against FY2025's 983. Two files then arrived named
    # "Audit 2019.pdf" and "Audit 2020.pdf" — and they are SCANS, not the digital
    # originals. Measured three independent ways, all agreeing:
    #
    #   Audit 2019.pdf   15 embedded fonts   20,369 chars over 181 pages
    #   Audit 2020.pdf    0 embedded fonts      163 chars over 163 pages
    #   (a real digital audit, the FY2022 stamped edition: 99 fonts, 254,119 chars)
    #
    # So the request stands and must NOT be reported as satisfied. They are still
    # worth having: they are different, ten-times-smaller scans of two thin years,
    # and Audit 2020 carries no embedded text at all, so there is no digit-transposing
    # OCR layer to mislead anyone — they are fair candidates for the fresh-recognition
    # path, where the per-page arithmetic gate decides what may publish.
    "audit-2019",
    "audit-2020",
    # Added 2026-07-31. The town's Finance Director sent three files in response to the
    # request for digital originals. ONE was genuine — CAFR_Issued_TOH_FY2018, 19 fonts
    # and 265,291 characters, which turned the thinnest year in the warehouse into a
    # readable one. The other two are the FY2019 and FY2020 SCANS again under new names:
    # 15 fonts / 20,369 chars, and 0 fonts / 163 chars. Measured on arrival, as always.
    # The request for genuine FY2019 and FY2020 originals therefore still stands.
    "cafr-issued-toh-fy2019",
    "town-of-hillsborough-issued-cafr-fy20-002",
    # Added 2026-07-29: the county's Article 46 quarter-cent resolution arrived
    # as a scan with an interleaved OCR layer — s00's font analysis and a manual
    # read agree. Its figures require transcription like every other scan.
    "res-2022-041-a-resolution-regarding-continued-uses-of-revenues-from-a-one-q",
    "fiscal-year-2024-2026-strategic-plan-20230626",
    "annual-comprehensive-financial-report-year-ended-june-30-2018",
    "annual-comprehensive-financial-report-year-ended-june-30-2019",
    "annual-comprehensive-financial-report-year-ended-june-30-2020",
    "annual-comprehensive-financial-report-year-ended-june-30-2021",
    "annual-financial-report-year-ended-june-30-2022",
    "annual-financial-report-year-ended-june-30-2023",
    "annual-financial-report-year-ended-june-30-2024",
    "annual-financial-report-year-ended-june-30-2025",
    "comprehensive-annual-financial-report-fy18",
}


def test_the_known_scans_are_still_labelled_as_scans(documents):
    scans = {d["id"] for d in documents["documents"] if d.get("text_layer") == "scan"}
    assert scans == KNOWN_SCAN_IDS, (
        "the set of scan-labelled documents changed — if a scan was replaced by a "
        f"digital original, update this anchor deliberately. diff: "
        f"missing={sorted(KNOWN_SCAN_IDS - scans)} extra={sorted(scans - KNOWN_SCAN_IDS)}")


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

    Recomputed from the check rows, not read off the summary: mutation testing
    showed a check row could be flipped to failing while the stored summary
    integer stayed 0 and this test stayed green. (The old failure message also
    filtered on a status string the data never uses.)
    """
    failing = [c for c in validation["checks"] if not c["reconciles"]]
    # Every failing check must be disclosed as such AND flag its slice unverified.
    for c in failing:
        assert "unexplained" in c["status"] or "variance" in c["status"], c
        assert c["verified"] is False, f"a failing check left its slice verified: {c}"
    assert validation["summary"]["unexplained"] == 0, validation["summary"]
    assert validation["summary"]["total"] == len(validation["checks"]), (
        "summary.total does not match the number of check rows")
    assert validation["summary"]["reconciled"] == sum(
        1 for c in validation["checks"] if c["reconciles"]), (
        "summary.reconciled does not match a recount of the check rows")


def test_the_headline_year_is_fully_verified(validation):
    """The year the site leads with must reconcile outright.

    Derived, not hardcoded: the year comes from index.json (written by the build
    from the newest budget-basis line items) — the same field the site reads —
    so the site and this gate cannot silently lead with different years. The
    hardcoded 2027 this replaced would have kept testing FY2027 forever while
    the site auto-advanced.
    """
    with open(REPO / "data" / "index.json", encoding="utf-8") as fh:
        idx = json.load(fh)
    year = idx["headline_fiscal_year"]
    assert year, "index.json carries no headline_fiscal_year"
    li = load("lineitems.json")
    src_i = li["columns"].index("fiscal_year")
    basis_i = li["columns"].index("basis")
    assert year == max(r[src_i] for r in li["rows"] if r[basis_i] == "budget"), (
        "headline_fiscal_year does not match the newest budget-basis line items")
    checks = [c for c in validation["checks"]
              if c["fiscal_year"] == year and c["basis"] == "budget"]
    assert checks, f"no FY{year} budget checks ran"
    bad = [c for c in checks if not c["reconciles"]]
    assert not bad, f"FY{year} budget does not reconcile: {bad}"


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
    # Every row — a [:5000] cap here would go silently partial the day the data
    # grows past it, and 3,636 rows cost milliseconds.
    C = {c: i for i, c in enumerate(lineitems["columns"])}
    for r in lineitems["rows"]:
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

    The non-empty assertion is what keeps this from passing vacuously: with
    published=[] the loop never ran, the suite stayed green, and the site's
    entire audited-record section could silently vanish.
    """
    assert ocr_statements["published"], (
        "ocr_statements publishes nothing — the audited record the site renders "
        "would silently disappear")
    for p in ocr_statements["published"]:
        assert p["extraction"] == "ocr-arithmetic-verified", p
        assert p["component_lines"] >= 2, (
            f"a 'total' derived from {p['component_lines']} line(s) is not a real check: {p}")
        assert p["source_page"] and p["source_doc"], p


def test_ocr_column_roles_are_confirmed_never_assumed(ocr_statements):
    """Charting the wrong column would be a silent, serious error, so a role is
    only recorded when the variance column proves the layout arithmetically."""
    assert any(d["status"] == "verified" for d in ocr_statements["documents"]), (
        "no OCR document is verified — the loop below would pass over nothing")
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
    c = idx["counts"]
    assert c["facts"] == len(facts)
    assert c["documents"] == len(documents["documents"])
    # The scan labels' redundant count is pinned here too — mutation testing
    # showed nothing else noticed when all ten labels flipped to "digital".
    assert c["documents_scanned_needing_transcription"] == sum(
        1 for d in documents["documents"] if d.get("text_layer") == "scan")
    assert c["documents_with_trustworthy_text"] == sum(
        1 for d in documents["documents"] if d.get("text_layer") == "digital")
    assert c["ocr_figures_published"] == len(load("ocr_statements.json")["published"])
    liv = load("lineitem_validation.json")
    assert c["reconciliation_checks_total"] == len(liv["checks"])
    assert c["reconciliation_checks_passed"] == sum(
        1 for x in liv["checks"] if x["reconciles"])


def test_the_cited_documents_count_is_real(documents):
    """The receipts section shows TWO numbers now — the evidence base and the
    archive — precisely because one number was doing both jobs. The evidence
    base must be recomputed here, independently of the build, from the same
    field rules: a hand-typed or stale count would recreate the original defect.
    """
    with open(REPO / "data" / "index.json", encoding="utf-8") as fh:
        idx = json.load(fh)
    doc_ids = {d["id"] for d in documents["documents"]}
    by_filename = {d["filename"]: d["id"] for d in documents["documents"]}

    def ds(name):
        p = DATASETS / name
        if not p.exists():
            return {}
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)

    cited = set(f["source_doc"] for f in load("facts.json")["facts"] if f.get("source_doc"))
    li = ds("lineitems.json")
    if li:
        i = li["columns"].index("source_doc")
        cited |= {r[i] for r in li["rows"]}
    cited |= {r["source_doc"] for c in ds("projections.json").get("comparisons", [])
              for r in c["readings"]}
    cited |= {q["source_doc"] for q in ds("facts_household.json").get("town_statements", [])
              if q.get("source_doc")}
    aud = ds("audited_general_fund.json")
    if aud.get("source_doc"):
        cited.add(aud["source_doc"])
    cited |= {p["source_doc"] for p in ds("ocr_statements.json").get("published", [])}
    proj = ds("projects.json")
    cited |= {p["source_doc"] for p in proj.get("projects", []) if p.get("source_doc")}
    if proj.get("source_doc"):
        cited.add(proj["source_doc"])
    cited |= {f["source_doc"] for f in ds("tradeoffs.json").get("justification_forms", [])
              if f.get("source_doc")}
    cited |= {i for s in ds("transfer_schedule.json").get("schedules", [])
              for i in s.get("source_docs", [])}
    req = ds("requests.json")
    if req.get("request_document"):
        cited.add(req["request_document"])
    for single in ("utility_rates.json", "revenue.json", "warehouse_county.json"):
        v = ds(single).get("source_doc")
        if v:
            cited.add(v)
    cited |= set(ds("workbook_b.json").get("source_docs", []))
    st = ds("structure.json")
    sh = st.get("already_shared") or {}
    if sh.get("source_doc"):
        cited.add(sh["source_doc"])
    cited |= set((st.get("run_separately") or {}).get("source_docs", []))
    cited |= {t["source_doc"] for t in sh.get("what_the_town_records_paying", [])
              if t.get("source_doc")}
    cited |= {q["source_doc"] for q in
              (ds("context.json").get("finance_director_on_debt") or {}).get("quotes", [])
              if q.get("source_doc")}
    cited |= {i["source_doc"] for i in ds("issues.json").get("issues", [])
              if i.get("source_doc")}
    cited = {c if c in doc_ids else by_filename.get(c, c) for c in cited}

    assert cited <= doc_ids, f"published data cites unknown documents: {sorted(cited - doc_ids)}"
    assert sorted(cited) == idx["cited_documents"], (
        "index.json cited_documents does not match an independent recount: "
        f"missing={sorted(cited - set(idx['cited_documents']))} "
        f"extra={sorted(set(idx['cited_documents']) - cited)}")
    assert idx["counts"]["documents_cited"] == len(cited)
    # Sanity floors: the evidence base can grow, but a collapse to near-nothing
    # means an extractor broke, not that the site stopped citing documents.
    assert len(cited) >= 15, f"only {len(cited)} cited documents — an extractor broke?"
    assert idx["counts"]["documents_cited"] < idx["counts"]["documents"], (
        "every archived document claims to be cited — that is the original "
        "misleading state this count exists to prevent")


def test_no_published_figure_is_read_from_scan_text_anywhere(documents):
    """The page-wide zero the credibility card shows. Recomputed here across the
    same datasets the build counts, so the card's zero is a measured fact about
    everything published — not, as it once was, a facts.json-only count wearing
    a page-wide claim."""
    with open(REPO / "data" / "index.json", encoding="utf-8") as fh:
        idx = json.load(fh)
    scans = {d["id"] for d in documents["documents"] if d.get("text_layer") == "scan"}
    n = 0
    n += sum(1 for f in load("facts.json")["facts"]
             if f.get("source_doc") in scans
             and f.get("extraction") not in ("transcribed", "ocr-arithmetic-verified"))
    li = load("lineitems.json")
    i = li["columns"].index("source_doc")
    n += sum(1 for r in li["rows"] if r[i] in scans)
    ocr = load("ocr_statements.json")
    n += sum(1 for p in ocr["published"] if p.get("extraction") != "ocr-arithmetic-verified")
    aud = load("audited_general_fund.json")
    if aud.get("source_doc") in scans:
        n += len(aud.get("rows", []))
    assert idx["counts"]["figures_read_from_scan_text"] == n
    assert n == 0, f"{n} published figures trace to a scan's text layer"


def test_the_transfer_schedule_carries_its_sources():
    """The rendered transfer matrix used to name no document at all — nine
    dollar cells with no provenance, against the one rule."""
    t = load("transfer_schedule.json")
    assert t["schedules"], "no transfer schedules published"
    for s in t["schedules"]:
        assert s.get("source_docs"), f"schedule FY{s['fiscal_year']} {s['basis']} cites nothing"


# ------------------------------------- the imported design warehouse (stage 85)
@pytest.fixture(scope="module")
def warehouse():
    return load("warehouse_county.json")


def test_imported_rows_keep_the_workbook_authors_schema(warehouse):
    """Her field names are the contract; renaming them would break the handoff.

    All rows: the old [:200] slice left half the warehouse unchecked (396 rows)
    while the docstring claimed the schema was guarded.
    """
    for r in warehouse["rows"]:
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
    """s85 must read the design workbook, never modify it — she edits in Excel.

    The ban list matches s96's stricter one: the old list ('wb.save(',
    '.save(wbp') missed a write through any other variable name, demonstrated
    by mutation. Bare '.save(' catches every normally-spelled write.
    """
    src = (REPO / "etl" / "s85_warehouse.py").read_text(encoding="utf-8")
    for banned in ("wb.save(", ".save(", "openpyxl.Workbook("):
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
    domain = (REPO / "assets" / "domain.js").read_text(encoding="utf-8")
    assert "state.gallons" in app, "water use is no longer a numeric state value"
    # id= attribute forms, not bare tokens: a comment containing the word would
    # satisfy a bare-token grep with the control itself deleted.
    assert 'id="galNum"' in app and 'id="galSel"' in app, "the custom-entry control is missing"
    # The block-rate maths moved to assets/domain.js on 2026-08-03 so it could be unit
    # tested without a browser (tests/js/domain.test.py -> blockBill / utilityBill).
    # Follow it rather than dropping the guard: assert BOTH that the computation still
    # exists where it now lives, and that the page still routes through it — either
    # half alone would pass with the bill quietly reverted to a two-option lookup.
    assert "function blockBill" in domain, (
        "the block-rate bill computation is gone from assets/domain.js")
    assert "threshold_gallons" in domain and "block2_per_1000" in domain, (
        "the bill is no longer computed from the published rate structure")
    assert "MFAS.utilityBill(" in app, (
        "assets/app.js no longer computes the utility bill from the rate structure")


def test_the_coming_section_reads_the_deficit_by_year():
    """Tripwire for the 3.4x understatement: one()/val() pick a single row per
    metric by document recency and returned FY2026's estimate where the sentence
    said "by FY2029". The fetch must stay year-addressed."""
    app = (REPO / "assets" / "app.js").read_text(encoding="utf-8")
    assert "forYear('general_fund_surplus_deficit', need.fiscal_year)" in app, (
        "the coming-section deficit is no longer fetched by the year the sentence names")
    assert "val('general_fund_surplus_deficit')" not in app, (
        "a year-blind deficit fetch is back — this is how the FY2029 sentence "
        "silently showed FY2026's figure")


def test_artifacts_that_leave_the_page_carry_sender_provenance():
    """Tripwire: the printed sheet and the copied text must keep consulting the
    sender-fields state — a shared link's figures used to leave the page in the
    first person with no provenance at all."""
    app = (REPO / "assets" / "app.js").read_text(encoding="utf-8")
    assert "function senderFields()" in app, "the sender-fields helper is gone"
    assert app.count("senderFields()") >= 4, (
        "senderFields() is no longer consulted everywhere figures leave the page "
        "(notice, printed sheet, copied text)")


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
    # Both operands are stored, so assert the arithmetic — not only the ETL's own
    # flag about its arithmetic (a bug writing optimistic flags passes flags-only
    # tests).
    assert abs(v["fy29_cliff_parts_sum"] - v["fy29_cliff_total_stated"]) < 1.0, v


def test_her_penny_assumption_matches_the_towns_published_figure(wbb):
    # The guard must exist to guard: an ETL rename dropping the key would have
    # turned this into a loop over nothing, silently.
    assert any("penny_matches_published" in i for i in wbb["tax_equivalent_exposure"]), (
        "no tax-equivalent item carries penny_matches_published — the check vanished")
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
    for loaded in ("wasteful", "should be merged", "should merge", "should consolidate",
                   "consolidate the", "bloated", "duplicative waste", "waste of money"):
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
        # Absence is only acceptable if nothing points readers at the file: the
        # README links it, so "not built yet" must FAIL rather than skip — a
        # skipped gate here is exactly how a linked 404 shipped once before.
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        assert "MFAS_Data_Warehouse.xlsx" not in readme, (
            "README links the warehouse export but the file does not exist")
        pytest.skip("export not built and not referenced")
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


# ---------------------------------------------------------------------------
# The warehouse core (s87) — Amy's 2026-07-29 decisions, held to
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def wh():
    return load("warehouse.json")


def test_the_warehouse_grain_is_unique_and_written_down(wh):
    """Most warehouse pain is a grain nobody wrote down. This one is written down
    AND enforced: the first build collided on the town's own repeated FICA lines,
    which is what the Line ordinal exists for."""
    assert "one row per" in wh["grain"]
    C = {c: i for i, c in enumerate(wh["columns"])}
    keys = [(r[C["Organization_ID"]], r[C["Fiscal_Year_ID"]], r[C["Scenario"]],
             r[C["Fund_ID"]], r[C["Flow"]], r[C["Department"]], r[C["Account"]],
             r[C["Line"]], r[C["Measure"]]) for r in wh["rows"]]
    assert len(keys) == len(set(keys)), "duplicate grain keys in Fact_Financial"


def test_the_government_is_a_column_and_both_are_loaded(wh):
    """Her rule, agreed 100%: the government is a COLUMN. Both governments must sit
    in the ONE table with the ONE schema — step 4's proof, re-derived here rather
    than trusted from the stage's own flag."""
    C = {c: i for i, c in enumerate(wh["columns"])}
    orgs = {r[C["Organization_ID"]] for r in wh["rows"]}
    assert {"ORG_HB", "ORG_OC"} <= orgs, f"both governments must be loaded: {orgs}"
    widths = {len(r) for r in wh["rows"]}
    assert widths == {len(wh["columns"])}, (
        "rows of differing width — the single-schema claim is false")
    assert wh["step4_proof"]["schema_changed_by_county_load"] is False
    assert wh["step4_proof"]["orange_county_rows"] == sum(
        1 for r in wh["rows"] if r[C["Organization_ID"]] == "ORG_OC")


def test_warehouse_scenarios_are_frozen_and_estimates_survive(wh):
    """Dim_Scenario is frozen at five values, and appending an Actual must never
    cost an Estimate: what the town projected versus what happened is the history
    nobody else keeps (her extensibility test #2)."""
    frozen = {s["Scenario"] for s in wh["dim_scenario"]}
    assert frozen == {"Actual", "Adopted", "Recommended", "Estimate", "Projection"}
    C = {c: i for i, c in enumerate(wh["columns"])}
    used = {r[C["Scenario"]] for r in wh["rows"]}
    assert used <= frozen, f"scenarios outside the frozen dimension: {used - frozen}"
    # FY2025 carries budget AND actual readings side by side today — the
    # never-overwrite property as data, not as a promise.
    fy25 = {r[C["Scenario"]] for r in wh["rows"] if r[C["Fiscal_Year_ID"]] == "FY2025"
            and r[C["Organization_ID"]] == "ORG_HB"}
    assert {"Actual", "Adopted"} <= fy25, fy25


def test_warehouse_flows_never_sum_across(wh):
    """Revenue plus expenditure is not a number. The first build of s87 produced
    exactly that ($38.9M for the GF), which is why Flow exists — and why each
    flow must reconcile to its source on its own."""
    C = {c: i for i, c in enumerate(wh["columns"])}
    li = load("lineitems.json")
    L = {c: i for i, c in enumerate(li["columns"])}
    li_gf27 = round(sum(r[L["value"]] for r in li["rows"]
                        if r[L["fund"]] == "General Fund"
                        and r[L["fiscal_year"]] == 2027 and r[L["basis"]] == "budget"), 2)
    wh_gf27 = round(sum(r[C["Amount"]] for r in wh["rows"]
                        if r[C["Organization_ID"]] == "ORG_HB"
                        and r[C["Fiscal_Year_ID"]] == "FY2027"
                        and r[C["Scenario"]] == "Recommended"
                        and r[C["Fund_ID"]] == "FUND_GF"
                        and r[C["Flow"]] == "Expenditure"
                        and r[C["Measure"]] == "amount"), 2)
    assert wh_gf27 == li_gf27, (
        f"warehouse GF FY2027 Recommended expenditure {wh_gf27:,} does not reconcile "
        f"to the line items {li_gf27:,}")


def test_warehouse_hillsborough_rows_cite_the_manifest(wh, documents):
    C = {c: i for i, c in enumerate(wh["columns"])}
    ids = {d["id"] for d in documents["documents"]}
    bad = sorted({r[C["Source_ID"]] for r in wh["rows"]
                  if r[C["Organization_ID"]] == "ORG_HB" and r[C["Source_ID"]] not in ids})
    assert not bad, f"Hillsborough fact rows cite unknown documents: {bad}"


def test_warehouse_recommended_is_not_called_adopted(wh):
    """The FY27 line items come from the RECOMMENDED plan. The site once labelled
    that year "already adopted"; the warehouse must not repeat the lie."""
    C = {c: i for i, c in enumerate(wh["columns"])}
    fy27_lineitem_rows = [r for r in wh["rows"]
                          if r[C["Fiscal_Year_ID"]] == "FY2027"
                          and r[C["Organization_ID"]] == "ORG_HB"
                          and r[C["Source_Detail"]] == "line-item appendix"]
    assert fy27_lineitem_rows, "the FY2027 line items are missing from the warehouse"
    assert {r[C["Scenario"]] for r in fy27_lineitem_rows} == {"Recommended"}


def test_the_government_is_never_a_tab_name():
    """Her rule's other half: no warehouse tab or file may carry a municipality's
    name. (Her authored source workbooks keep theirs — they are hers.)"""
    openpyxl = pytest.importorskip("openpyxl")
    xl = REPO / "data" / "exports" / "MFAS_Data_Warehouse.xlsx"
    if not xl.exists():
        pytest.skip("export not built yet")
    wb = openpyxl.load_workbook(xl, read_only=True)
    try:
        bad = [n for n in wb.sheetnames
               if any(g in n for g in ("Hillsborough", "Orange", "Chapel", "Carrboro",
                                       "Mebane", "_HB", "_OC", "_CH"))]
    finally:
        wb.close()
    assert not bad, f"government names in tab names: {bad}"


# ------------------------------------------- the site's copy vs what it publishes
#
# This class of defect is invisible to every check above, and it is the one that
# does the most damage: a sentence that was true when it was written and is now
# contradicted by the page it sits on. Three of them had accumulated — the glossary
# told readers the site "cannot yet show" audited figures while the audited record
# sat two sections above it, the receipts intro said nothing on the page came from a
# scanned document, and the footer called the audited decade "work not yet done". A
# reader who notices one of those has been given a reason to disbelieve everything
# else, which is the only asset this project has.
SITE_COPY = ("index.html", "assets/app.js")


def _site_text():
    return "\n".join((REPO / f).read_text(encoding="utf-8") for f in SITE_COPY)


def test_the_site_never_claims_it_lacks_figures_it_publishes(ocr_statements):
    """If the audited series ships, no copy may say it does not."""
    if not ocr_statements["published"]:
        pytest.skip("nothing recovered from scans in this build")
    text = " ".join(_site_text().lower().split())
    for phrase in ("cannot yet show", "cannot show yet", "cannot show audited",
                   "work not yet done", "no longer out of reach"):
        assert phrase not in text, (
            f"site copy still says {phrase!r} while ocr_statements.json publishes "
            f"{len(ocr_statements['published'])} recovered figures")


def test_the_site_never_claims_scans_contribute_nothing(ocr_statements):
    """A scan's *hidden text* is never trusted; a scanned *page* does contribute.

    Collapsing those two is what made the old sentence false. The precise claim is
    worth more than the sweeping one, so the sweeping one must not come back.
    """
    if not ocr_statements["published"]:
        pytest.skip("nothing recovered from scans in this build")
    text = " ".join(_site_text().lower().split())
    for phrase in ("nothing on this page is taken from those",
                   "none of the figures on this page come from a scan"):
        assert phrase not in text, f"site copy still says {phrase!r}"


def test_the_masthead_does_not_overclaim_where_figures_come_from(facts, documents):
    """14 of the published figures come from the initiative's own request workbook,
    not from a government publication — and dozens of documents are the county's,
    not the town's. The page labels both where they appear; the masthead must not
    contradict that by claiming every figure is the town's.

    The skip encodes BOTH reasons the banned sentence is false: mutation testing
    showed that recategorising the one records-request document disarmed the old
    single-condition skip while county documents still made the sentence false.
    """
    by_id = {d["id"]: d for d in documents["documents"]}
    non_gov = {f["source_doc"] for f in facts
               if by_id.get(f["source_doc"], {}).get("category") in {"records-request", "issues"}}
    non_town = {f["source_doc"] for f in facts
                if by_id.get(f["source_doc"], {}).get("jurisdiction")
                not in (None, "Town of Hillsborough, NC")}
    if not non_gov and not non_town:
        pytest.skip("every fact currently comes from a town publication")
    html = (REPO / "index.html").read_text(encoding="utf-8")
    assert "Every figure comes from the town's own published documents" not in html, (
        f"the masthead claims every figure is the town's while {len(non_gov)} source "
        f"document(s) are the initiative's own and {len(non_town)} are not the town's")


def test_the_masthead_does_not_promise_a_page_every_figure_lacks(facts):
    """14 figures come from spreadsheet cells, which have a document but no page.

    "shown with the document and page it came from" was true of the 69 read out of
    PDFs and quietly false of the rest. The claim now carries its own exception, and
    it may only drop that exception if every fact really does carry a page.

    Scope: ALL site copy, not just index.html. The original index.html-only scope
    let the identical sentence survive in the print takeaway (app.js) — on the one
    artefact a resident carries to a meeting — and let the meta description
    reintroduce the claim as a paraphrase in the page's most-syndicated sentence.
    The banned list carries the paraphrase too. Exact-string pins: a rewording can
    still evade them, which is why the honest sentences are also derived from data
    where possible rather than guarded only here.
    """
    pageless = [f["metric"] for f in facts if f.get("source_doc") and not f.get("source_page")]
    if not pageless:
        pytest.skip("every fact carries a page — the unqualified claim would be true")
    text = " ".join(_site_text().split())
    for phrase in ("with the document and page it came from",
                   "with the document and page shown for every number",
                   "document and page shown for every"):
        assert phrase not in text, (
            f"site copy promises a page for every figure ({phrase!r}) while "
            f"{len(pageless)} facts have none (e.g. {sorted(set(pageless))[:3]})")


# ---------------------------------------------------------------------------
# The warehouse fill of 2026-07-29. Each of these guards a defect that actually
# shipped into data during that work, which is the only reason to write a gate.
# ---------------------------------------------------------------------------

@pytest.fixture
def warehouse_full():
    return load("warehouse.json")


def test_no_slice_is_reported_twice_by_two_documents(warehouse_full):
    """Every audited statement prints last year's actual as a comparative column.

    Loading those alongside the prior year's own audit put 475 slices into
    Fact_Financial twice — same organisation, year, scenario, account and measure,
    from two documents, distinguished only by Line. Every row reconciled against its
    own page, which is precisely what made it dangerous: nothing looked wrong, and
    anyone summing an account across Lines would have doubled it.

    A comparative column may only load for a year no document reads directly.
    """
    cols = {n: i for i, n in enumerate(warehouse_full["columns"])}
    seen = {}
    dupes = []
    for r in warehouse_full["rows"]:
        key = tuple(r[cols[c]] for c in ("Organization_ID", "Fiscal_Year_ID", "Scenario",
                                         "Flow", "Department", "Account", "Measure"))
        src = r[cols["Source_ID"]]
        if key in seen and seen[key] != src:
            dupes.append((key, seen[key], src))
        seen.setdefault(key, src)
    assert not dupes, (
        f"{len(dupes)} slice(s) reported by two documents — a comparative prior-year "
        f"column is loading for a year already read directly. First: {dupes[0]}")


def test_every_fact_financial_row_states_a_basis(warehouse_full):
    """A figure whose column meaning is unknown must NOT be in the financial table.

    Stages 61 and 81 prove which column is budget and which is actual from each
    statement's own variance identity. Where that cannot be proven the lines are
    verified and cited but their basis is not established, and they belong in
    Fact_Statement_Line. Letting one into Fact_Financial would publish a budget
    figure as an outturn about a real government.
    """
    cols = {n: i for i, n in enumerate(warehouse_full["columns"])}
    allowed = set(warehouse_full["dim_scenario"] and
                  [s["Scenario"] for s in warehouse_full["dim_scenario"]])
    bad = [r for r in warehouse_full["rows"] if r[cols["Scenario"]] not in allowed]
    assert not bad, f"{len(bad)} row(s) carry a scenario outside Dim_Scenario"

    fsl = warehouse_full.get("fact_statement_line", {})
    for r in fsl.get("rows", []):
        assert r.get("basis_unknown_because"), (
            "a Fact_Statement_Line row must say why its basis is unknown — that "
            "sentence is the only thing stopping it being read as an actual")


def test_fact_metric_never_mixes_units(warehouse_full):
    """Fact_Metric holds dollars-per-pupil beside dollars. Unit is load-bearing.

    It exists because nine of Amy's county tables are real facts at a grain that is
    not fund dollars. If a row loses its Unit, someone sums $5,877 per pupil into a
    dollar total.
    """
    fm = warehouse_full.get("fact_metric", {})
    for r in fm.get("rows", []):
        assert r.get("Unit"), f"Fact_Metric row without a Unit: {r.get('Metric')}"
        assert r.get("Metric"), f"Fact_Metric row without a Metric: {r}"


def test_coverage_reports_the_backlog_honestly():
    """Coverage must not count a document as read because a QUESTION names it.

    The first version scanned dataset text for document ids. The questions register
    names each unread document inside the question asking for it to be read, so the
    measurement promoted all 23 backlog items to "read" the moment it described the
    gap — a coverage report congratulating itself.
    """
    cov = load("coverage.json")
    docs = {d["id"] for d in load("documents.json")["documents"]}
    assert cov["documents_total"] == len(docs)
    statuses = {r["status"] for r in cov["documents"]}
    assert statuses <= {"read", "read-into-datasets-only", "not-yet-read", "no-figures",
                        "design-document", "scanned-unextractable",
                        "superseded-by-digital"}, statuses
    for r in cov["documents"]:
        if r["status"] != "read":
            assert r["why"], f"{r['document']}: a non-read status must say why"
    # The backlog is a real number and must be reported, not smoothed to zero.
    assert cov["backlog_count"] == sum(1 for r in cov["documents"]
                                       if r["status"] == "not-yet-read")


def test_digital_audits_agree_with_the_independent_readings():
    """The cross-document checks are the project's strongest evidence — keep them.

    A digital reading of an audit and a character-recognition reading of the SCANNED
    version of the same audit landing on the same figure is as close to an external
    audit as this project gets. If a check starts disagreeing, one of the two readings
    is wrong and both are suspect until it is resolved.
    """
    try:
        ad = load("audited_digital.json")
    except FileNotFoundError:
        pytest.skip("audited_digital.json not built")
    cross = ad.get("cross_document_checks", {})
    assert cross.get("checks_run", 0) >= 4, (
        "the cross-document checks stopped running — they are the reason these "
        "figures are believable, so losing them silently is the failure mode")
    bad = [c for c in cross["checks"] if not c["agree"]]
    assert not bad, f"independent readings disagree: {bad[:2]}"


# ---------------------------------------------------------------------------
# Fixes for the 2026-07-31 external code audit. Each test pins a defect that
# was live in a published artifact, not a hypothetical.
# ---------------------------------------------------------------------------

def test_no_document_is_attributed_to_the_wrong_government(documents):
    """H-01. The export inferred the owner from a substring of the jurisdiction.

    `"ORG_OC" if "Orange" in jurisdiction else "ORG_HB"` published ten
    initiative-authored documents as Orange County government sources, and — once
    Chapel Hill arrived — thirteen Chapel Hill documents as Town of Hillsborough,
    because "Chapel Hill" does not contain "Orange". Ownership is now recorded
    explicitly in the manifest; this pins it.
    """
    expected = {
        "Town of Hillsborough, NC": "ORG_HB",
        "Orange County, NC": "ORG_OC",
        "Town of Chapel Hill, NC": "ORG_CH",
        "Town of Carrboro, NC": "ORG_CB",
        "City of Mebane, NC": "ORG_MB",
        "Orange County Efficiency & Accountability Initiative": "ORG_INIT",
    }
    for d in documents["documents"]:
        assert d.get("organization_id"), f"{d['id']}: no organization_id"
        want = expected.get(d["jurisdiction"])
        assert want, f"{d['id']}: jurisdiction {d['jurisdiction']!r} has no ORG mapping"
        assert d["organization_id"] == want, (
            f"{d['id']} ({d['jurisdiction']}) attributed to {d['organization_id']}, "
            f"expected {want}")


def test_initiative_documents_are_never_presented_as_government_records(documents):
    """H-01. Readability is not authority.

    The initiative's own request workbooks and design files are machine-readable,
    and the export gave every machine-readable document `High` confidence — so the
    project's own working papers carried the standing of a published audit.
    """
    init = [d for d in documents["documents"] if d["jurisdiction"].startswith(
        "Orange County Efficiency")]
    assert init, "no initiative documents found — has the jurisdiction label changed?"
    for d in init:
        assert d["organization_id"] == "ORG_INIT", d["id"]
        assert d["source_authority"] == "initiative", d["id"]


def test_the_export_agrees_with_the_json_it_was_built_from():
    """H-04. The exports ran BEFORE s90 merged facts.json, so the downloadable
    workbook could carry the previous run's figures while the site carried the
    new ones — and a second build hid it by making them agree again."""
    openpyxl = pytest.importorskip("openpyxl")
    xl = REPO / "data" / "exports" / "MFAS_Data_Warehouse.xlsx"
    if not xl.exists():
        pytest.skip("export not built")
    facts = load("facts.json")["facts"]
    wb = openpyxl.load_workbook(xl, read_only=True)
    try:
        ws = wb["1.0 Fact_Published_Figures"]
        rows = [r for r in ws.iter_rows(values_only=True) if r and r[0]]
        header = next(i for i, r in enumerate(rows) if "Organization_ID" in [str(x) for x in r if x])
        data = rows[header + 1:]
        assert len(data) == len(facts), (
            f"export has {len(data)} fact rows, facts.json has {len(facts)} — the "
            f"export was built from a different run's data")
    finally:
        wb.close()


def test_source_registry_gives_every_document_a_content_keyed_identity():
    """M-04/M-01. IDs came from filenames and collisions resolved by traversal
    order, so an ID could move to different bytes while facts kept citing it.
    And every rebuild reset official_url to None, erasing maintainer work."""
    path = REPO / "data" / "source_registry.json"
    assert path.exists(), "the source registry is missing — s00 should create it"
    reg = json.loads(path.read_text(encoding="utf-8"))["sources"]
    docs = load("documents.json")["documents"]
    for d in docs:
        assert d["sha256"] in reg, f"{d['id']} is not in the source registry"
        assert reg[d["sha256"]]["id"] == d["id"], (
            f"{d['id']}: registry says {reg[d['sha256']]['id']} for the same bytes")
    ids = [v["id"] for v in reg.values()]
    assert len(ids) == len(set(ids)), "the registry assigns one ID to two hashes"


def test_trust_documents_do_not_pin_stale_archive_counts(documents):
    """M-07. Stale trust documentation is expensive in an accountability project.

    The README claimed 84 documents and 879 MB while the manifest held 115 and
    925 MiB; PROVENANCE.md claimed 30 documents and 726 MB. A reader checking our
    numbers against our own prose finds a discrepancy and has no way to know which
    is stale. Volatile counts either come from the manifest or are not stated.
    """
    summary = documents["summary"]
    n = summary["unique_documents"]
    mb = round(summary["total_bytes"] / 1048576)
    stale = []
    for name in ("README.md", "AGENTS.md", "docs/PROVENANCE.md",
                 "docs/EXTRACTION_NOTES.md", "docs/AGENT_BRIEF.md"):
        p = REPO / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r"(\d{2,4})\s*(?:unique\s+)?documents\b", text):
            if int(m.group(1)) not in (n,) and int(m.group(1)) > 20:
                stale.append(f"{name}: claims {m.group(1)} documents, manifest has {n}")
        for m in re.finditer(r"\b(\d{3,4})\s*(?:MB|MiB)\b", text):
            v = int(m.group(1))
            # 100 MiB is GitHub's limit, quoted deliberately; anything else that
            # looks like an archive size must match the manifest.
            if v not in (100, mb) and v > 200:
                stale.append(f"{name}: claims {v} MB, archive is {mb} MiB")
    assert not stale, "stale pinned counts in trust documentation:\n  " + "\n  ".join(stale)


def test_every_extraction_cache_is_content_addressed():
    """H-02. A cache keyed on a name, size or mtime describes the SLOT a document
    occupies, not the document. Replacing a PDF under the same filename then served
    text from the old file while the manifest recorded the new hash — which severs
    the fact-to-source chain this project presents as its trust guarantee, and a
    routine resumable `make etl` was enough to trigger it."""
    # Matched against CODE only. The docstrings deliberately quote the old keys to
    # explain what went wrong, and a test that cannot tell an explanation from the
    # defect it describes punishes writing the explanation down.
    def code_of(name: str) -> str:
        import ast
        tree = ast.parse((REPO / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc and node.body and isinstance(node.body[0], ast.Expr):
                    node.body[0].value = ast.Constant(value="")
        return ast.unparse(tree)

    banned = [
        ("etl/s70_ocr.py", 'OCR_ROOT / d["id"]'),
        ("etl/s50_line_items.py", "st.st_size"),
        ("etl/s50_line_items.py", "st.st_mtime"),
        ("etl/s85_warehouse.py", "path.stem[:60]"),
        ("etl/s94_projects.py", "7776223-1778845438"),
    ]
    for name, pattern in banned:
        src = code_of(name)
        assert pattern not in src, (
            f"{name} still keys a cache on {pattern!r} — use common.content_cache_dir(), "
            f"which binds the namespace to the source sha256 and extractor version")
    common = (REPO / "etl" / "common.py").read_text(encoding="utf-8")
    assert "def content_cache_dir" in common, "the content-addressed cache helper is gone"


def test_stage_diagnostics_can_actually_fail_the_build():
    """H-03. Stages collected failures, printed them, and exited 0, so the documented
    rebuild command succeeded while publishing partial data."""
    common = (REPO / "etl" / "common.py").read_text(encoding="utf-8")
    assert "def report_and_gate" in common
    assert "sys.exit(1)" in common, "report_and_gate no longer fails the build"
    for name in ("s30_budget_messages", "s40_household_impact", "s80_county"):
        src = (REPO / "etl" / f"{name}.py").read_text(encoding="utf-8")
        assert "report_and_gate(" in src, f"{name} does not gate its diagnostics"


def test_the_release_gate_runs_the_tests():
    """H-03. `make etl` was the documented rebuild command and never ran the tests —
    which is how three high-severity defects coexisted with a green suite."""
    mk = (REPO / "Makefile").read_text(encoding="utf-8")
    assert "\nverify:" in mk, "no verify target"
    block = mk.split("\nverify:")[1].split("\n\n")[0]
    assert "etl" in block and "test" in block, "verify must run BOTH the ETL and the tests"
    wf = REPO / ".github" / "workflows" / "verify.yml"
    assert wf.exists(), "no CI workflow enforces the gate"
    assert "pytest" in wf.read_text(encoding="utf-8")


def test_exports_are_built_after_the_facts_are_merged():
    """H-04. s101/s103 read facts.json; s90 writes it. Running the exports first
    meant the downloadable workbook carried the previous run's figures."""
    mk = (REPO / "Makefile").read_text(encoding="utf-8")
    etl = mk.split("\netl:")[1].split("\ntest:")[0]
    order = re.findall(r"etl/(s\w+)\.py", etl)
    assert order.index("s90_build") < order.index("s101_workbook"), (
        "s90_build must run BEFORE s101_workbook or the export lags the JSON by a build")
    assert order.index("s90_build") < order.index("s103_tab_map")


def test_the_workbook_exports_rebuild_byte_identically():
    """M-02. docs/PROVENANCE.md tells a contributor to expect a clean
    `git diff --stat data/` after a rebuild. It never was: OpenPyXL stamps both the
    ZIP member timestamps AND `docProps/core.xml` with the current instant, so the
    exports were dirty on every run and the one signal that would reveal a REAL data
    change was permanently drowned out.

    This checks the mechanism rather than re-running the build: both clocks pinned,
    and the workbook's own 'Generated' cell derived from the source set instead of
    today's date."""
    common = (REPO / "etl" / "common.py").read_text(encoding="utf-8")
    assert "def normalise_xlsx" in common, "the xlsx normaliser is gone"
    assert "docProps/core.xml" in common, (
        "normalise_xlsx no longer pins docProps/core.xml — fixing only the ZIP "
        "timestamps leaves the file non-deterministic, which was the first attempt")
    assert "def build_stamp" in common
    for name in ("s101_workbook", "s103_tab_map"):
        src = (REPO / "etl" / f"{name}.py").read_text(encoding="utf-8")
        assert "normalise_xlsx(OUT)" in src, f"{name} does not normalise its output"
        assert "date.today()" not in src, f"{name} still stamps the wall-clock date"


def test_the_cover_sheet_counts_match_reality():
    """A cover is where a wrong number is least likely to be checked and most likely to
    be quoted.

    The first build of the MFAS cover printed "83 published figures" — it had been handed
    `len(facts)`, which is only the Fact_Published_Figures tab — against a real total of
    23,569, and "26 tabs" for a workbook with 28. Both were caught by looking at the
    rendered sheet, which is not a control. This is the control: the cover's counts must
    equal the workbook's own sheet list and the coverage dataset it claims to summarise.

    This is the same defect class the 2026-07-31 audit named — a volatile count pinned in
    prose — just relocated into a spreadsheet cell where the existing README/docs scanner
    could not see it.
    """
    openpyxl = pytest.importorskip("openpyxl")
    xl = REPO / "data" / "exports" / "MFAS_Data_Warehouse.xlsx"
    if not xl.exists():
        pytest.skip("export not built yet")
    cov = json.loads((REPO / "data" / "datasets" / "coverage.json").read_text())
    wb = openpyxl.load_workbook(xl, read_only=True)
    try:
        assert "MFAS" in wb.sheetnames, "the cover sheet is missing"
        assert wb.sheetnames[0] == "MFAS", (
            f"the cover must be the first tab, found {wb.sheetnames[0]!r}")
        ws = wb["MFAS"]
        vals = {}
        for row in ws.iter_rows(values_only=True):
            cells = [c for c in row if c is not None]
            if len(cells) >= 2 and isinstance(cells[0], str):
                vals[cells[0]] = str(cells[1])
        n_tabs = len(wb.sheetnames)
        # Each fact tab carries a caveat note on row 1 and its header on row 2, so the
        # data starts at row 3 — `max_row - 1` would count the header and inflate every
        # tab by one, which is how the cover briefly read three too high.
        fact_rows = 0
        for t in ("Fact_Financial", "Fact_Metric", "Fact_Statement_Line"):
            if t not in wb.sheetnames:
                continue
            ws_t = wb[t]
            hdr = 1
            for r_i, r_vals in enumerate(ws_t.iter_rows(min_row=1, max_row=3,
                                                        values_only=True), 1):
                if "Source_ID" in [str(v) for v in r_vals if v is not None]:
                    hdr = r_i
                    break
            fact_rows += max(0, ws_t.max_row - hdr)
    finally:
        wb.close()

    assert "Tabs" in vals and "Facts" in vals, sorted(vals)
    assert vals["Tabs"].startswith(f"{n_tabs} "), (
        f"cover claims {vals['Tabs'][:12]!r} tabs, workbook has {n_tabs}")
    # AGAINST THE TABS THEMSELVES, not against coverage.json.
    #
    # The first version of this test compared the cover with coverage.json and passed
    # while the cover said 23,569 and the three fact tabs held 24,251 — it had made two
    # partial views of the data agree with each other, and neither agreed with the
    # workbook. A test that compares a claim with a second copy of the same claim is
    # not a control. Count the rows.
    assert f"{fact_rows:,}" in vals["Facts"], (
        f"cover says {vals['Facts']!r}, but the fact tabs hold {fact_rows:,} rows")
    assert str(cov["documents_total"]) in vals["Facts"], (
        f"cover does not carry the archive size {cov['documents_total']}")
    if "Still unread" in vals:
        assert str(cov["backlog_count"]) in vals["Still unread"], (
            f"cover backlog {vals['Still unread']!r} != {cov['backlog_count']}")


def test_the_workbook_house_style_matches_the_websites_palette():
    """One identity. `etl/workbook_style.py` copies its colours out of the site's LIGHT
    theme, and a copy that nobody checks drifts the first time either side is touched.

    The site's values are the validated ones — `assets/style.css` records measured
    contrast ratios and the failures that produced them — so the CSS is the authority and
    the workbook follows it, never the reverse.
    """
    css = (REPO / "assets" / "style.css").read_text(encoding="utf-8")
    style = (REPO / "etl" / "workbook_style.py").read_text(encoding="utf-8")
    # (workbook constant, the CSS custom property it was taken from)
    for const, prop in [("INK", "--text-primary"), ("INK_SOFT", "--text-secondary"),
                        ("MUTED", "--text-muted"), ("PAPER", "--surface-1"),
                        ("PAPER_ALT", "--surface-3"), ("BLUE", "--accent"),
                        ("BLUE_TEXT", "--accent-text"), ("ORANGE", "--series-2"),
                        ("GREEN", "--series-3")]:
        m = re.search(rf'^{const} = "([0-9A-F]{{6}})"', style, re.M)
        assert m, f"{const} not found in workbook_style.py"
        # The light theme is the SECOND block; the dark set is the site's default and
        # would be near-white on paper. Take the last definition, which is the light one.
        hits = re.findall(rf"{re.escape(prop)}:\s*#([0-9a-fA-F]{{6}})\b", css)
        assert hits, f"{prop} not found in assets/style.css"
        assert m.group(1).lower() in [h.lower() for h in hits], (
            f"workbook {const}=#{m.group(1)} is not any published value of {prop} "
            f"({', '.join('#' + h for h in hits)}) — the workbook and the site have drifted")


# ---------------------------------------------------------------------------
# The calculator's location rule. C-01 in the 2026-08-01 external audit: the page
# asked where the home was and then charged town property tax either way.
# ---------------------------------------------------------------------------

def _chromium():
    for exe in ("chromium", "chromium-browser", "google-chrome"):
        p = shutil.which(exe)
        if p:
            return p
    return None


def test_town_tax_is_conditional_on_being_in_town_in_the_source():
    """The cheap gate, so the rule is enforced even where no browser exists.

    `annualTax()` returned the town levy unconditionally and every caller — the hero,
    the printable takeaway, the "what it pays for" line and the spending explorer —
    used it. A $500,000 home outside the limits was shown $5,944 instead of $3,379.
    """
    js = (REPO / "assets" / "app.js").read_text(encoding="utf-8")
    m = re.search(r"function townTax\(\)\s*\{(.*?)\n\}", js, re.S)
    assert m, "townTax() is gone — the location rule lives there"
    assert "state.location !== 'intown'" in m.group(1), (
        "townTax() no longer checks the location; an out-of-town home would be charged "
        "town property tax again")
    assert "function annualTax(" not in js, (
        "annualTax() is back. It was the unconditional town levy and every caller "
        "treated it as 'the town tax this household pays' — rename it or gate it, but "
        "do not reintroduce the name")

    code = _js_without_comments(js)
    # Excluding the declaration line. `js.count("townTax()")` counted it, so the
    # assertion held even if every caller had been ripped out and inlined.
    callers = len(re.findall(r"(?<!function )\btownTax\(\)", code))
    assert callers >= 3, (
        f"only {callers} caller(s) route through townTax() — a surface has gone back "
        f"to computing the town levy for itself, which is how the out-of-town defect "
        f"survived in four places at once")

    # This replaces a `for call in re.findall(...): pass` loop — a body-less loop that
    # asserted NOTHING and reported the location rule as covered whether the helper it
    # named was called twelve times or never. It was never called: townLevyIfInTown()
    # and totalPropertyTax() were both dead code while five renderers each kept their
    # own inline copy of the conversion. This is the assertion it should have been.
    inline = re.findall(r"homeValue\s*/\s*100\s*\*\s*0?\.01", code)
    assert not inline, (
        f"{len(inline)} inline cost-per-cent formula(s) are back in assets/app.js. That "
        f"expression belongs in assets/domain.js, where it is unit tested and where a "
        f"location rule can be applied once — five ungated copies of it are finding "
        f"F-01 of docs/2026-08-03_FRONTEND_AUDIT.md")


def _js_without_comments(js: str) -> str:
    """Strip comments before grepping for code.

    Every assertion in this file that greps assets/app.js is otherwise satisfiable by a
    comment that merely MENTIONS the thing — and this file's own history is a list of
    guards that turned out to be looser than they read. Line comments are removed only
    where the line has nothing else on it, so a `https://` inside a string survives.
    """
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return "\n".join(
        "" if ln.lstrip().startswith(("//", "*")) else ln for ln in js.splitlines())


def test_the_calculator_is_loaded_before_the_page_that_uses_it():
    """assets/app.js calls MFAS.* at module scope. If the script tag is missing, or is
    ordered after app.js, EVERY figure on the site fails to render — not one section,
    the whole page. There is no build step to catch that, so this is the gate."""
    html = (REPO / "index.html").read_text(encoding="utf-8")
    dom = html.find('src="assets/domain.js"')
    app = html.find('src="assets/app.js"')
    assert dom != -1, "assets/domain.js is not loaded by index.html — the page cannot compute"
    assert app != -1, "assets/app.js is not loaded by index.html"
    assert dom < app, (
        "assets/domain.js must load BEFORE assets/app.js; app.js references MFAS at "
        "module scope and would throw before rendering anything")
    # Match the WHOLE tag, not the text after src=. The first version of this assertion
    # searched `src="assets/domain.js"[^>]*(defer|async)` and so read only the
    # attributes to the RIGHT of src — `<script defer src="assets/domain.js">` sailed
    # through it. Caught by reverting the fix and finding the test still green, which is
    # the only reason to bother reverting.
    tag = re.search(r"<script\b[^>]*assets/domain\.js[^>]*>", html)
    assert tag, "could not locate the domain.js script tag"
    assert not re.search(r"\b(defer|async)\b", tag.group(0)), (
        f"domain.js must not be deferred or async — app.js is a plain script and would "
        f"run first, leaving MFAS undefined: {tag.group(0)}")


def _render(paths):
    """Serve the repo and return {name: dumped DOM} for each (name, path) given.

    `--force-prefers-reduced-motion` is load-bearing, not tidiness. setFigure()
    animates the hero over 620ms via requestAnimationFrame, and --dump-dom captures
    whatever the count-up happens to be showing: successive runs of the ORIGINAL
    version of this test read $4,968, $4,892 and $783 where the true figure is $5,944.
    The string "5,944" appeared nowhere in the hero — every assertion below was in fact
    resting on the snapshot card further down the page.

    That is not a cosmetic flaw in a test. If an edit reinstated the out-of-town defect
    in the hero ALONE, the dumped hero text would be some arbitrary intermediate, would
    not contain "5,944", and this gate would pass while the 76% overstatement shipped.
    With reduced motion, draw() passes animate=false, setFigure takes its early return,
    and the hero is captured at its real value.
    """
    import http.server
    import socketserver
    import threading

    os.chdir(REPO)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(REPO))
    out = {}
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            for name, path in paths:
                r = subprocess.run(
                    [_chromium(), "--headless", "--disable-gpu", "--no-sandbox",
                     "--force-prefers-reduced-motion",
                     "--virtual-time-budget=15000", "--dump-dom",
                     f"http://127.0.0.1:{port}/{path}"],
                    capture_output=True, text=True, timeout=180)
                out[name] = r.stdout
        finally:
            httpd.shutdown()
    return out


@pytest.mark.skipif(_chromium() is None, reason="no chromium available")
def test_out_of_town_pages_never_show_the_town_levy():
    """The real gate: render the page in a browser, both answers, and read the DOM.

    Asserting on the source alone would have missed the three surfaces that kept their
    own copy of the calculation — the printable takeaway built its own row list, and the
    explorer computed a share per department. This drives the actual share-link path a
    reader would use.
    """
    doms = _render([(w, f"index.html?home=500000&where={w}")
                    for w in ("intown", "outoftown")])

    # The hero, BY ELEMENT. A whole-page substring search cannot tell the difference
    # between the primary figure being right and some other element on the page
    # happening to contain the same digits — which is exactly the state this gate was
    # in until 2026-08-03.
    def hero(dom):
        m = re.search(r'id="heroV"[^>]*>([^<]*)', dom)
        assert m, "the hero figure element is gone"
        return m.group(1).strip()

    assert hero(doms["intown"]) == "$5,944", (
        f'in town the hero must read the town levy plus the county levy, '
        f'got {hero(doms["intown"])!r}')
    assert hero(doms["outoftown"]) == "$3,379", (
        f'OUT OF TOWN the hero must read the COUNTY LEVY ALONE. This is the 2026-08-01 '
        f'defect: it read $5,944 instead of $3,379, a 76% overstatement. '
        f'got {hero(doms["outoftown"])!r}')

    town, county, both = "2,565", "3,379", "5,944"
    assert town in doms["intown"], (
        "in town, the town levy should appear — the fixture or the rates changed")
    assert county in doms["intown"]

    # The whole finding, in two assertions.
    assert town not in doms["outoftown"], (
        "OUT OF TOWN: the town property tax is still shown. The page asks where the "
        "home is and must not charge the town's levy to a home outside its limits.")
    assert both not in doms["outoftown"], (
        "OUT OF TOWN: the town+county total is still shown somewhere on the page")
    assert county in doms["outoftown"], (
        "OUT OF TOWN: the county levy should still be charged — every taxpayer in the "
        "county pays it")
    assert "No town property tax" in doms["outoftown"], (
        "OUT OF TOWN: removing the row silently is not enough; say why it is absent")
    assert "fire district tax" in doms["outoftown"], (
        "OUT OF TOWN: county-only is not the whole bill — a fire district tax applies "
        "and must be named, or the fix trades an overstatement for an understatement")


# ---------------------------------------------------------------------------
# The 2026-08-03 frontend audit's browser-observable findings.
#
# The audit's own closing note: F-02, F-06, F-07, F-08, F-11, F-13, F-16 and F-22 are
# traced through the code with the data held constant — "argued from the source and the
# current datasets, not observed. The next fiscal roll is the real test." These gates
# run that roll early, against a MUTATED copy of the published data, which is the only
# way to observe a dormant defect before it fires on a live civic site.
# ---------------------------------------------------------------------------

# The eighteen personalised figures F-01 found are all `oneCent * N` — the TOWN's rate
# applied to the reader's home. These are the phrases that carry them, measured off the
# rendered page rather than guessed.
#
# ⚠ The audit proposed asserting on "for a home like yours" / "for you" generally. That
# was over-broad, and measuring it proved so: the SAME wording carries the county rise
# ("Orange County's rate rose 3.75 cents, which adds $188 a year for a home like yours")
# and the year-over-year total, both of which an out-of-town household genuinely pays.
# Banning the phrase would force the page to stop telling a non-resident the one increase
# that does reach them — trading a false statement for a missing one. So the gate names
# the TOWN-POLICY surfaces specifically.
_TOWN_POLICY_MARKERS = (
    "One cent on the tax rate costs you",   # the row label, in-town wording
    "/yr on your home",                     # the twelve driver rows' suffix
    "a year</span> for your home",          # the capital-commitments line
    "a year</span> for you)",               # the affordable-housing line
    "on a home like yours",                 # the FY2029 cliff card
)


@pytest.mark.skipif(_chromium() is None, reason="no chromium available")
def test_out_of_town_pages_never_quote_a_town_policy_dollar_to_the_reader():
    """F-01. The levy row was fixed; eighteen personalised dollar figures were not.

    `?home=500000&where=outoftown` rendered a hero of $3,379 and the sub-line "No town
    property tax", and two inches below it, in the same list: "One cent on the tax rate
    costs you · $50 / yr" and "If the rate rose 10 cents · at least +$500 / yr". Section
    04 added "$210 a year for your home", "about $100 a year for you", a FY2029 cliff of
    "$743 a year on a home like yours", and TWELVE driver rows reading "$729/yr on your
    home", "$131", "$78" and so on. Every one is $0 for that household, and two of them
    printed onto the sheet a resident carries into a board meeting.

    The previous gate asserted only that the strings "2,565" and "5,944" were absent, so
    none of this was covered.
    """
    doms = _render([(w, f"index.html?home=500000&where={w}")
                    for w in ("intown", "outoftown")])
    # Comments are part of the DOM, and this file's own history says a guard that can be
    # satisfied — or broken — by prose is not measuring the thing it names.
    strip = lambda d: re.sub(r"<!--.*?-->", "", d, flags=re.S)
    out, inn = strip(doms["outoftown"]), strip(doms["intown"])

    present = [m for m in _TOWN_POLICY_MARKERS if m in out]
    assert not present, (
        f"OUT OF TOWN: {len(present)} town-policy surface(s) still quote a personalised "
        f"dollar figure to a household the same page says pays the town nothing: "
        f"{present}. The CENTS are a real town-policy fact and may stay; the "
        f"'costs you' dollar column may not (finding F-01).")

    # NEGATIVE CONTROL. Without this, deleting the rows outright would satisfy the
    # assertion above — and a gate that a deletion passes is not measuring anything.
    # In town every one of these figures is real and must still be published.
    missing = [m for m in _TOWN_POLICY_MARKERS if m not in inn]
    assert not missing, (
        f"IN town these figures are real costs and must still appear; {missing} are "
        f"gone. The fix is to withhold them outside the limits, not to remove them.")


def _render_mutated(mutate, paths):
    """Serve a COPY of the site with the published data altered, and dump the DOM.

    Several findings are dormant: they fire when a dataset rolls forward, loses a field,
    or fails to load. There is no way to observe those against the committed data, and
    "argued from the source" is precisely the standard that let four surfaces keep their
    own copy of a broken calculation. `mutate` is handed the temp data directory.

    Only `data/` is copied; index.html, assets and docs are symlinked, so the code under
    test is the code in the working tree and cannot drift from it.
    """
    import http.server
    import socketserver
    import threading
    import tempfile

    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in ("index.html", "assets", "docs"):
            src = REPO / name
            if src.exists():
                (root / name).symlink_to(src)
        shutil.copytree(REPO / "data", root / "data",
                        ignore=shutil.ignore_patterns("exports"))
        mutate(root / "data")

        handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                    directory=str(root))
        with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
            port = httpd.server_address[1]
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                for label, path in paths:
                    r = subprocess.run(
                        [_chromium(), "--headless", "--disable-gpu", "--no-sandbox",
                         "--force-prefers-reduced-motion",
                         "--virtual-time-budget=15000", "--dump-dom",
                         f"http://127.0.0.1:{port}/{path}"],
                        capture_output=True, text=True, timeout=180)
                    out[label] = r.stdout
            finally:
                httpd.shutdown()
    return out


@pytest.mark.skipif(_chromium() is None, reason="no chromium available")
def test_a_missing_county_rate_withholds_the_total_instead_of_publishing_zero():
    """F-10. `total = annualR + (countyR || 0)` turned an absent rate into a MEASURED zero.

    `county_property_tax_rate` has exactly one fact in facts.json. Drop it — a rename, a
    failed unit check in a rebuild — and with `?where=outoftown` the hero rendered $0 and
    the snapshot headlined "$0 in property tax this year", while the callout two elements
    above still said the county rise "adds $188 a year for a home like yours". The copied
    text carried "Town property tax: $0/yr" off the page with the site's sources attached.
    """
    def drop_county_rate(data):
        p = data / "datasets" / "facts.json"
        d = json.loads(p.read_text())
        before = len(d["facts"])
        d["facts"] = [f for f in d["facts"] if f["metric"] != "county_property_tax_rate"]
        assert len(d["facts"]) < before, "the fixture no longer removes anything"
        p.write_text(json.dumps(d))

    dom = _render_mutated(drop_county_rate,
                          [("out", "index.html?home=500000&where=outoftown")])["out"]
    m = re.search(r'id="heroV"[^>]*>([^<]*)', dom)
    assert m, "the hero figure element is gone"
    hero = m.group(1).strip()
    assert hero == "—", (
        f"with the county rate missing the hero must WITHHOLD, not publish a measured "
        f"zero; got {hero!r}")
    assert "$0 in property tax this year" not in dom, (
        "the snapshot published a sourced-looking $0 for a rate the build does not hold")


@pytest.mark.skipif(_chromium() is None, reason="no chromium available")
def test_one_optional_dataset_failing_does_not_amputate_the_page():
    """F-17. boot() lets non-CORE datasets fail alone; three renderers dereferenced them
    unguarded, the throw escaped render(), and the catch handler THEN threw too because
    `#loading` had already been removed.

    Measured with requests.json 404ing: `id="you"` present; `coming`, `voice` and
    `receipts` all absent; `#verifySlot` never replaced, so "How you can check this" was
    gone; `#chipCount` still showing its static placeholder "Verified figures". A 40 KB
    page that looks finished, still carrying the masthead's promise that every figure
    names its document — with the entire receipts section that substantiates that promise
    silently deleted. No wrong number is published; the worst-case failure for this
    project's one rule is published instead.
    """
    def remove_requests(data):
        (data / "datasets" / "requests.json").unlink()

    dom = _render_mutated(remove_requests, [("x", "index.html")])["x"]
    missing = [s for s in ("you", "paysfor", "health", "coming", "voice", "receipts")
               if f'id="{s}"' not in dom]
    assert not missing, (
        f"a single optional dataset going missing removed section(s) {missing} with no "
        f"error on screen — the receipts section is what substantiates the site's one "
        f"promise, and losing it silently is the worst available failure")


@pytest.mark.skipif(_chromium() is None, reason="no chromium available")
def test_a_first_visit_leaves_no_memory_to_greet_the_reader_with():
    """F-20. Two consecutive plain visits, one browser profile, nothing touched.

    Reproduced with two fresh profiles before the fix: visit one showed no banner, visit
    two said "Welcome back — showing figures for a home assessed at $400,000, inside town
    limits." The reader had never typed a value and had never said they live in town.
    `saveHome()` ran on every render and persisted the DEFAULTS; `loadHome()` then set
    `state.returning` for any parseable stored value.

    The page asserted a memory it did not have, on the one control the whole calculator
    hangs off, and on the exact question whose mis-answer produced the 76% overstatement.
    """
    import http.server
    import socketserver
    import threading
    import tempfile

    os.chdir(REPO)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(REPO))
    with tempfile.TemporaryDirectory() as profile:
        with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
            port = httpd.server_address[1]
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            doms = []
            try:
                # The SAME profile twice — localStorage has to survive between them or
                # this test cannot see the defect at all.
                for _ in range(2):
                    r = subprocess.run(
                        [_chromium(), "--headless", "--disable-gpu", "--no-sandbox",
                         "--force-prefers-reduced-motion",
                         f"--user-data-dir={profile}",
                         "--virtual-time-budget=15000", "--dump-dom",
                         f"http://127.0.0.1:{port}/index.html"],
                        capture_output=True, text=True, timeout=180)
                    doms.append(r.stdout)
            finally:
                httpd.shutdown()

    assert "Welcome back" not in doms[0], "a FIRST visit cannot be a return visit"
    assert "Welcome back" not in doms[1], (
        "the second plain visit greeted a reader who has never entered anything. "
        "Storage must record what the reader TOLD us, not the defaults they were shown.")


def test_the_savings_floor_metric_matches_the_town_s_own_words():
    """F-16. The floor drove a ✓/! verdict from a literal `50` in five places.

    It existed in the archive only as a numeral inside the sentence the site quotes two
    panels below that verdict. A board revising the aim to 60% would have had the page
    print the new words in a blockquote and award a pass against the retired figure, on
    the same screen — and draw the chart's reference line at the old one.

    So the metric is read from that SAME sentence, and this is what keeps the two from
    drifting: if the quotation says one number and the fact says another, the build fails.
    """
    hh = json.loads((REPO / "data" / "datasets" / "facts_household.json").read_text())
    quote = next((q for q in hh["town_statements"] if q["key"] == "savings_floor"), None)
    assert quote, "the savings_floor quotation is gone — the metric's provenance with it"

    facts = json.loads((REPO / "data" / "datasets" / "facts.json").read_text())["facts"]
    metric = [f for f in facts if f["metric"] == "fund_balance_floor_pct"]
    assert metric, (
        "fund_balance_floor_pct is not published. Without it assets/app.js has nothing "
        "to read and the floor goes back to being hardcoded in five places (F-16)")
    assert len(metric) == 1, f"expected one floor fact, got {len(metric)}"
    fact = metric[0]

    in_quote = re.search(r"no lower than\s+(\d+(?:\.\d+)?)\s*%", quote["text"])
    assert in_quote, f"cannot find a percentage in the quotation: {quote['text']!r}"
    assert float(in_quote.group(1)) == fact["value"], (
        f"the town's own words say {in_quote.group(1)}% and the published metric says "
        f"{fact['value']}% — the site would grade against one while quoting the other")
    assert fact["source_doc"] == quote["source_doc"], "same document"
    assert fact["source_page"] == quote["source_page"], "same page"


def test_the_page_reads_its_fiscal_year_from_the_data():
    """F-06, F-13, F-26, F-27. Six surfaces picked a year with the literal `2027`.

    renderHealth already read index.headline_fiscal_year thirty lines below one of them,
    so the page disagreed with itself about which year it was about. On the first roll
    forward, section 04 "What's coming for you" would have opened with a closed, adopted
    budget year LABELLED a projection, while section 03 correctly started at the next one.

    The suite already carried this lesson, written next to a different fix: "the hardcoded
    2027 this replaced would have kept testing FY2027 forever while the site auto-advanced".
    """
    js = _js_without_comments((REPO / "assets" / "app.js").read_text(encoding="utf-8"))
    assert "const headlineYear = ()" in js, (
        "headlineYear() is gone — the year literals have nowhere to route through")

    # `2027` may appear ONLY inside the helper's own fallback. Anywhere else it is a
    # surface deciding for itself what year the page is about.
    js_without_helper = re.sub(
        r"const headlineYear = \(\)[^;]+;", "", js, count=1)
    literals = re.findall(r"\b20(2[6-9]|3\d)\b", js_without_helper)
    assert not literals, (
        f"{len(literals)} fiscal-year literal(s) are back in assets/app.js "
        f"({sorted(set('20' + x for x in literals))}). Route them through "
        f"headlineYear(), or the page will disagree with itself on the next roll "
        f"forward (findings F-06, F-13, F-26, F-27)")


def test_every_published_fact_cites_a_document_in_the_archive():
    """Both governments. The gate in s87 used to exempt Orange County because Amy's
    workbook carried her own register's keys, and 682 of 24,251 exported rows shipped
    citing IDs absent from the exported Source_Register — a reader joining the two
    tables lost 2.9% of the rows with nothing to tell them why."""
    wh = json.loads((REPO / "data" / "datasets" / "warehouse.json").read_text())
    ids = {d["id"] for d in json.loads(
        (REPO / "data" / "datasets" / "documents.json").read_text())["documents"]}
    col = {n: i for i, n in enumerate(wh["columns"])}
    orphans = collections.Counter()
    for r in wh["rows"]:
        if r[col["Source_ID"]] not in ids:
            orphans[r[col["Source_ID"]]] += 1
    metric = wh.get("fact_metric")
    for r in (metric.get("rows") if isinstance(metric, dict) else metric) or []:
        if r.get("Source_ID") and r["Source_ID"] not in ids:
            orphans[r["Source_ID"]] += 1
    for r in wh["fact_statement_line"]["rows"]:
        if r.get("Source_ID") and r["Source_ID"] not in ids:
            orphans[r["Source_ID"]] += 1
    assert not orphans, (
        f"{sum(orphans.values())} published fact(s) cite a Source_ID that is not in the "
        f"archive: {dict(orphans)}")


def test_confidence_never_outranks_the_extraction_method():
    """The workbook cover defines OCR as Medium and workbook imports as Working, and the
    warehouse labelled 1,110 such rows `High` — 488 OCR, 522 workbook, 100 metric.
    Filtering to High therefore did not give a reader what the cover promises, which is
    worse than no label at all: a caveat that is present but wrong gets relied on."""
    wh = json.loads((REPO / "data" / "datasets" / "warehouse.json").read_text())
    col = {n: i for i, n in enumerate(wh["columns"])}
    ceiling = {"digital-text": 3, "derived": 2, "ocr-arithmetic-verified": 2,
               "workbook-import": 1}
    rank = {"High": 3, "Medium": 2, "Working": 1, "Pending": 0}
    bad = collections.Counter()
    rows = [(r[col["Extraction"]], r[col["Confidence"]]) for r in wh["rows"]]
    metric = wh.get("fact_metric")
    rows += [(r.get("Extraction"), r.get("Confidence"))
             for r in ((metric.get("rows") if isinstance(metric, dict) else metric) or [])]
    for ext, conf in rows:
        cap = ceiling.get(str(ext))
        if cap is not None and rank.get(str(conf), 0) > cap:
            bad[(ext, conf)] += 1
    assert not bad, (f"{sum(bad.values())} row(s) claim a confidence their extraction "
                     f"method does not support: {dict(bad)}")


def test_recognition_is_never_published_for_a_year_read_digitally():
    """A digital original wins. Three separate loaders in s87 can emit a recognised
    figure; two were guarded by a stale per-row flag and the third by nothing, so 36 OCR
    rows shipped for digitally-held years and 16 duplicated a digital row exactly on
    organization, year, scenario, flow, account, measure AND amount. Each reconciled
    against its own page; an aggregate over them was still double-counted."""
    ds = REPO / "data" / "datasets"
    dig_path = ds / "audited_digital.json"
    if not dig_path.exists():
        pytest.skip("no digital audits held")
    digital_years = {int(d["fiscal_year"])
                     for d in json.loads(dig_path.read_text()).get("documents", [])
                     if d.get("fiscal_year")}
    wh = json.loads((ds / "warehouse.json").read_text())
    col = {n: i for i, n in enumerate(wh["columns"])}
    offenders = [r for r in wh["rows"]
                 if r[col["Extraction"]] == "ocr-arithmetic-verified"
                 and r[col["Organization_ID"]] == "ORG_HB"
                 and int(str(r[col["Fiscal_Year_ID"]]).replace("FY", "")) in digital_years]
    assert not offenders, (
        f"{len(offenders)} recognised row(s) published for a year held digitally "
        f"({sorted(digital_years)}): "
        f"{sorted({r[col['Fiscal_Year_ID']] for r in offenders})}")


def test_every_accepted_column_really_does_add_up():
    """Recompute each accepted column from its MEMBERS, not from the cached fields.

    The 2026-08-01 audit's M-02. The parser stored `sum_of_lines` and `reconciles`
    alongside the members, and every check downstream trusted them — so a column could
    be marked reconciled and nobody ever re-derived it. Independent recomputation found
    an accepted Orange County column whose four lines sum to $141,335 against a printed
    $141,334, because the gate accepted `abs(got - tot) < 1.5` while the project said in
    public that accepted columns add up "exactly".

    A dollar is immaterial. The claim is not: exactness is a control, and a control that
    is only asserted is not a control. This recomputes.
    """
    ds = REPO / "data" / "datasets"
    checked = mismatched = 0
    bad = []
    for name in ("audited_digital.json", "county_acfr.json", "audited_scanned.json"):
        path = ds / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        # documents[] -> pages[] -> groups[]. The reconciliation lives on the PAGE, not
        # on the flat `published` list, which carries only the lines that survived it.
        for doc in payload.get("documents") or []:
            for page in doc.get("pages") or []:
                for g in page.get("groups") or []:
                    # `members`, NOT `publish_members`. The parser collapses an inner
                    # subtotal out of the sum and then re-adds its child lines to
                    # `publish_members` so they still get published — summing THAT list
                    # counts the subtotal and its children both, and this test first
                    # reported 41 "failures" whose recomputed totals were ~70% too high.
                    # Reconciliation is computed on `members`; verify the same thing.
                    members = g.get("members") or []
                    for col in g.get("columns") or []:
                        if not col.get("reconciles"):
                            continue
                        ci = col.get("column_index")
                        tot = col.get("printed_total")
                        if ci is None or tot is None:
                            continue
                        parts = [m["values"][ci] for m in members
                                 if ci < len(m.get("values") or [])
                                 and m["values"][ci] is not None]
                        if not parts:
                            continue
                        checked += 1
                        if abs(sum(parts) - tot) >= 0.005:
                            mismatched += 1
                            if len(bad) < 5:
                                bad.append({"file": name, "group": str(g.get("group"))[:40],
                                            "column": ci, "printed": tot,
                                            "recomputed": round(sum(parts), 2)})
    assert checked, "no accepted columns were recomputed — the shape of the data changed"
    assert not mismatched, (
        f"{mismatched} of {checked} ACCEPTED columns do not actually add up: {bad}")


@pytest.mark.skipif(_chromium() is None, reason="no chromium available")
def test_the_printed_sheet_and_the_copied_text_are_covered_at_all():
    """F-04 of the 2026-08-03 frontend audit: the two artefacts that LEAVE the page
    were in no test at all, and the test that claimed them could not have seen them.

    Both are built inside click handlers, so `id="takeaway"` is simply absent from a
    --dump-dom capture. `test_out_of_town_pages_never_show_the_town_levy` names the
    printable takeaway in its docstring; its assertions never touched it. That matters
    because the takeaway kept its OWN copy of the out-of-town defect — it built its own
    row list — and it is the one artefact a resident carries into a board meeting,
    where they cannot click a citation to check it.

    tests/browser/artefacts.html loads the real app against the real datasets and
    presses the real buttons. This asserts what came back.
    """
    doms = _render([
        (w, f"tests/browser/artefacts.html?home=500000&where={w}")
        for w in ("intown", "outoftown")
    ])

    got = {}
    for where, dom in doms.items():
        m = re.search(r'<pre id="ARTEFACTS">(.*?)</pre>', dom, re.S)
        assert m, (
            f"{where}: the harness produced no artefacts at all. If index.html gained "
            f"an element assets/app.js needs in its static shell, tests/browser/"
            f"artefacts.html has drifted and must be brought back into line — do not "
            f"delete this test to make it pass.")
        text = html_mod.unescape(m.group(1))
        assert not text.startswith("HARNESS FAILED"), f"{where}: {text[:400]}"
        copied, _, sheet = text.partition("=====TAKEAWAY=====")
        got[where] = (copied, sheet)

    # ---- in town: both governments appear on both artefacts --------------------
    copied, sheet = got["intown"]
    for name, blob in (("copied text", copied), ("printed sheet", sheet)):
        assert "2,565" in blob, f"in town the {name} lost the town levy"
        assert "3,379" in blob, f"in town the {name} lost the county levy"
        assert "5,944" in blob, f"in town the {name} lost the combined total"

    # ---- out of town: the town levy must appear on NEITHER ---------------------
    copied, sheet = got["outoftown"]
    for name, blob in (("copied text", copied), ("printed sheet", sheet)):
        assert "2,565" not in blob, (
            f"OUT OF TOWN the {name} still carries the town levy. A household outside "
            f"the limits owes the town nothing, and this artefact leaves the site — "
            f"nobody reading it can check it against the page.")
        assert "5,944" not in blob, (
            f"OUT OF TOWN the {name} still carries the town+county total")
        assert "3,379" in blob, (
            f"OUT OF TOWN the {name} lost the county levy — every taxpayer in the "
            f"county pays it, so removing it trades an overstatement for an "
            f"understatement")

    # The sheet must say what the screen says. When the town row is suppressed on
    # screen and kept here, the sheet a reader carries into a meeting is the wrong one.
    assert "Town of Hillsborough" not in got["outoftown"][1], (
        "OUT OF TOWN the printed sheet still prints a Town of Hillsborough bill row")
    assert "Town of Hillsborough" in got["intown"][1], (
        "in town the printed sheet lost its town bill row — the fixture or the rates "
        "changed")
