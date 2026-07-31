"""Stage 90 — merge stage outputs into the payload the website loads, and validate it.

Emits:
  data/datasets/facts.json       every observation, long/tidy
  data/datasets/metrics.json     human labels + units for each metric key
  data/datasets/projections.json where the same fiscal year is reported by more
                                 than one document, the spread between them
  data/index.json                small entry point the site fetches first

Validation is a hard gate, not advisory. A transparency site that renders a
missing number as 0, or cites a document id that does not exist, is worse than
one that refuses to build.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, DATASETS, TRUSTWORTHY, read_json, write_json  # noqa: E402

# Every metric that may appear in facts.json. An unknown key fails the build:
# the site needs a label and a unit for anything it charts.
METRICS = {
    "admin_spend_total": dict(
        label="Total administrative spend", unit="USD", category="Spending",
        description="Administrative spending as supplied by a county commissioner in "
                    "the initiative's request workbook. Not an audited figure.",
        direction="lower-is-cheaper"),
    "admin_spend_yoy_pct": dict(
        label="Administrative spend, year-over-year change", unit="percent",
        category="Spending", description="Computed by this pipeline from the stated totals."),
    "admin_spend_change_pct_since": dict(
        label="Administrative spend, total change over the period", unit="percent",
        category="Spending", description="First to last fiscal year in the stated series."),
    "capital_project_original_budget": dict(
        label="Capital project — original budget", unit="USD", category="Capital projects",
        description="Budget when the project was first approved."),
    "capital_project_current_budget": dict(
        label="Capital project — current budget", unit="USD", category="Capital projects",
        description="Most recent budget for the same project."),
    "general_fund_surplus_deficit": dict(
        label="General Fund surplus / (deficit)", unit="USD", category="General Fund",
        description="Negative values are deficits. Shown in the source in parentheses."),
    "general_fund_surplus_deficit_pct": dict(
        label="General Fund surplus / (deficit), % of budget", unit="percent",
        category="General Fund", description="Negative values are deficits."),
    "general_fund_balance_available_cash": dict(
        label="General Fund balance — available cash", unit="USD", category="Savings",
        description="The town's savings. Its stated floor is 50% of expenditures."),
    "general_fund_balance_pct_of_expenditures": dict(
        label="Fund balance as % of expenditures", unit="percent", category="Savings",
        description="The town states its aim is to stay no lower than 50%."),
    "general_fund_expenditures": dict(
        label="General Fund expenditures", unit="USD", category="Budget totals"),
    "water_sewer_fund_expenditures": dict(
        label="Water & Sewer Fund expenditures", unit="USD", category="Budget totals"),
    "stormwater_fund_expenditures": dict(
        label="Stormwater Fund expenditures", unit="USD", category="Budget totals"),
    "total_budget": dict(
        label="Total budget, all funds", unit="USD", category="Budget totals"),
    "property_tax_rate": dict(
        label="Property tax rate", unit="cents_per_100_valuation", category="Taxes",
        description="Cents per $100 of assessed value."),
    "revenue_per_cent_of_tax_rate": dict(
        label="Revenue raised by one cent of tax rate", unit="USD", category="Taxes",
        description="The town's own conversion factor. Powers the household cost estimate."),
    "salary_benefit_increase_cost": dict(
        label="Cost of salary and benefit increases", unit="USD", category="Spending"),
    "tax_rate_increase_needed_cents": dict(
        label="Tax rate increase needed to balance", unit="cents_per_100_valuation",
        category="Taxes", description="Stated by the town as a floor ('over N cents')."),
    "capital_projects_tax_rate_equivalent_cents": dict(
        label="Major capital projects, expressed as tax-rate cents",
        unit="cents_per_100_valuation", category="Capital projects"),
    "water_rate_increase_pct": dict(
        label="Water rate increase", unit="percent", category="Utilities"),
    "tax_rate_above_revenue_neutral_cents": dict(
        label="Tax rate above the revenue-neutral rate", unit="cents_per_100_valuation",
        category="Taxes",
        description="Revenue-neutral is the rate raising the same revenue after a "
                    "revaluation. The gap above it is the effective increase."),
    "affordable_housing_allocation": dict(
        label="Affordable housing allocation", unit="USD", category="Housing"),

    # ---- household impact (stage 40) ----------------------------------------
    # Dimensions (in-town vs out-of-town, average vs minimum consumption) are in the
    # metric name because the Fact schema is intentionally flat.
    **{f"{util}_bill_increase_monthly_{loc}_{lvl}": dict(
        label=(f"{util.capitalize()} bill increase, "
               f"{'in-town' if loc == 'intown' else 'out-of-town'}, "
               f"{'average' if lvl == 'avg' else 'minimum'} use"),
        unit="USD_per_month", category="Your household",
        description=("The town's own stated monthly increase from FY2026 to FY2027. "
                     "Average use is 4,000 gallons/month, minimum is 2,000."))
       for util in ("water", "sewer") for loc in ("intown", "outoftown")
       for lvl in ("avg", "min")},

    "sewer_rate_increase_pct": dict(
        label="Sewer rate increase", unit="percent", category="Utilities"),
    "stormwater_fee_increase_per_eru": dict(
        label="Stormwater fee increase per ERU", unit="USD", category="Utilities",
        description="Per Equivalent Residential Unit. The source does not state whether this "
                    "is monthly or annual, so no annual total is derived from it."),
    "affordable_housing_tax_rate_equivalent_cents": dict(
        label="Affordable housing target, as tax-rate cents",
        unit="cents_per_100_valuation", category="Housing",
        description="The board agreed in FY2024 to raise housing spending annually until it "
                    "reaches this share of the tax rate."),
    "salary_benefit_tax_rate_equivalent_cents": dict(
        label="Salary and benefit increase, as tax-rate cents",
        unit="cents_per_100_valuation", category="Spending"),
    "fy29_scenario_increase_on_400k_home": dict(
        label="FY2029 scenario: annual increase on a $400,000 home", unit="USD",
        category="Taxes",
        description="The town's own worked example, useful as a cross-check on the calculator."),
    "nonprofit_partnership_funding": dict(
        label="Nonprofit partnership funding", unit="USD", category="Spending"),

    # ---- Orange County (stage 80) -------------------------------------------
    # A Hillsborough household pays the county rate IN ADDITION to the town rate,
    # and the county rate is the larger of the two.
    "county_property_tax_rate": dict(
        label="Orange County property tax rate", unit="cents_per_100_valuation",
        category="Taxes",
        description="Charged on top of the town rate. Cents per $100 of assessed value."),
    "county_property_tax_rate_prior": dict(
        label="Orange County property tax rate, prior year",
        unit="cents_per_100_valuation", category="Taxes"),
    "county_tax_rate_increase_cents": dict(
        label="Orange County tax rate increase", unit="cents_per_100_valuation",
        category="Taxes"),
    "county_revenue_per_cent_of_tax_rate": dict(
        label="Revenue raised by one cent of the county tax rate", unit="USD",
        category="Taxes",
        description="The county's own conversion factor; its tax base is far larger "
                    "than the town's."),
    "county_tax_increase_on_500k_home": dict(
        label="County increase on a $500,000 home", unit="USD", category="Taxes",
        description="The county's own worked example, used to cross-check the rate."),
    "county_new_general_fund_revenue": dict(
        label="County new General Fund revenue", unit="USD", category="Budget totals"),
    "county_new_general_fund_expenses": dict(
        label="County new General Fund expenses", unit="USD", category="Budget totals"),
}

STAGE_FACT_FILES = ["facts_xlsx.json", "facts_budget.json", "facts_household.json",
                    "facts_county.json"]


def main() -> None:
    docs_blob = read_json(DATASETS / "documents.json")
    doc_ids = {d["id"] for d in docs_blob["documents"]}

    facts, sources = [], []
    for fn in STAGE_FACT_FILES:
        p = DATASETS / fn
        if not p.exists():
            sys.exit(f"missing {p} — run the earlier ETL stages first")
        blob = read_json(p)
        facts += blob["facts"]
        sources.append(fn)

    errors, warnings = [], []

    for i, f in enumerate(facts):
        where = f"facts[{i}] {f.get('metric')}"
        if f.get("metric") not in METRICS:
            errors.append(f"{where}: metric not in the registry in s90_build.py")
        if f.get("source_doc") not in doc_ids:
            errors.append(f"{where}: source_doc {f.get('source_doc')!r} "
                          f"is not in documents.json")
        if f.get("value") is None:
            errors.append(f"{where}: null value — drop it rather than publish a blank")
        ex = f.get("extraction")
        if ex not in TRUSTWORTHY:
            errors.append(f"{where}: extraction={ex!r} is not trustworthy for publication")
        m = METRICS.get(f.get("metric"))
        if m and f.get("unit") != m["unit"]:
            # Promoted from warning to ERROR 2026-07-31. A unit mismatch is not a
            # style problem: the registry is what the website uses to format and
            # compare a figure, so dollars rendered as thousands, or cents-per-$100
            # rendered as dollars, changes the meaning by orders of magnitude while
            # the number itself looks perfectly reasonable on the page.
            errors.append(f"{where}: unit {f.get('unit')!r} != registry {m['unit']!r} — "
                          f"a unit mismatch changes what the number MEANS")

    if errors:
        print(f"\nBUILD FAILED — {len(errors)} integrity error(s):")
        for e in errors[:40]:
            print(f"   {e}")
        sys.exit(1)

    # --- where do documents disagree about the same year? -----------------
    grouped = defaultdict(list)
    for f in facts:
        if f.get("fiscal_year") is None:
            continue
        grouped[(f["metric"], f["fiscal_year"], f["jurisdiction"])].append(f)

    projections = []
    for (metric, fy, jur), rows in sorted(grouped.items()):
        if len(rows) < 2:
            continue
        vals = [r["value"] for r in rows]
        lo, hi = min(vals), max(vals)
        earliest = min(rows, key=lambda r: r["source_doc"])
        latest = max(rows, key=lambda r: r["source_doc"])
        projections.append({
            "metric": metric, "fiscal_year": fy, "jurisdiction": jur,
            "readings": [{"value": r["value"], "basis": r.get("basis"),
                          "source_doc": r["source_doc"],
                          "source_page": r.get("source_page")} for r in rows],
            "min": lo, "max": hi, "spread": round(hi - lo, 2),
            "spread_pct_of_min": round((hi - lo) / abs(lo) * 100, 1) if lo else None,
            "note": ("The same fiscal year reported by more than one budget document. "
                     "Differences reflect basis (projection vs budget vs estimate) and "
                     "revised information, not necessarily error."),
        })

    write_json(DATASETS / "facts.json", {
        "generated_by": "etl/s90_build.py",
        "merged_from": sources,
        "count": len(facts),
        "facts": facts,
    })
    write_json(DATASETS / "metrics.json", {
        "generated_by": "etl/s90_build.py",
        "metrics": METRICS,
    })
    write_json(DATASETS / "projections.json", {
        "generated_by": "etl/s90_build.py",
        "note": ("Fiscal years that more than one document reports. This is the "
                 "dataset behind the 'how have the town's projections moved?' view."),
        "comparisons": projections,
    })

    # Stage 50's account-level data is large and lives in its own files; the site
    # lazy-loads it. Surface its counts and its reconciliation result here so the
    # entry point tells the whole story.
    li = read_json(DATASETS / "lineitems.json") if (DATASETS / "lineitems.json").exists() else None
    liv = (read_json(DATASETS / "lineitem_validation.json")
           if (DATASETS / "lineitem_validation.json").exists() else None)

    # ---- which documents does the published data actually cite? ---------------
    # The receipts section used to say every figure "traces to one of 84 documents
    # in the archive" — 84 is the archive's size, and 65 of those documents are
    # cited by nothing the site shows. One number was doing two jobs. This computes
    # the evidence base — the distinct manifest documents the published datasets
    # actually cite — so the site can show both numbers and neither can drift:
    # they are recomputed on every build and pinned by a test.
    by_filename = {d["filename"]: d["id"] for d in docs_blob["documents"]}
    scan_ids = {d["id"] for d in docs_blob["documents"] if d.get("text_layer") == "scan"}

    def maybe(name):
        p = DATASETS / f"{name}.json"
        return read_json(p) if p.exists() else None

    cited: dict[str, set] = {}          # dataset -> doc ids it cites
    scan_text_figures = 0               # published values read from a scan's text layer

    cited["facts"] = {f["source_doc"] for f in facts if f.get("source_doc")}
    scan_text_figures += sum(1 for f in facts
                             if f.get("source_doc") in scan_ids
                             and f.get("extraction") not in ("transcribed",
                                                            "ocr-arithmetic-verified"))
    if li:
        src_i = li["columns"].index("source_doc")
        cited["lineitems"] = {r[src_i] for r in li["rows"]}
        scan_text_figures += sum(1 for r in li["rows"] if r[src_i] in scan_ids)
    cited["projections"] = {r["source_doc"] for c in projections for r in c["readings"]}

    hh = maybe("facts_household")
    if hh:
        cited["household"] = {q["source_doc"] for q in hh.get("town_statements", [])
                              if q.get("source_doc")}
    aud = maybe("audited_general_fund")
    if aud and aud.get("source_doc"):
        cited["audited"] = {aud["source_doc"]}
        if aud["source_doc"] in scan_ids:
            scan_text_figures += len(aud.get("rows", []))
    ocr = maybe("ocr_statements")
    if ocr:
        cited["ocr_statements"] = {p["source_doc"] for p in ocr.get("published", [])}
        # A recovered figure is publishable only when re-read from the page IMAGE and
        # proven by its own arithmetic; anything else here would be text-layer output.
        scan_text_figures += sum(1 for p in ocr.get("published", [])
                                 if p.get("extraction") != "ocr-arithmetic-verified")
    for name, get in [
        ("projects", lambda d: {p["source_doc"] for p in d.get("projects", [])
                                if p.get("source_doc")} | ({d["source_doc"]}
                                                           if d.get("source_doc") else set())),
        ("tradeoffs", lambda d: {f["source_doc"] for f in d.get("justification_forms", [])
                                 if f.get("source_doc")}),
        ("transfer_schedule", lambda d: {i for s in d.get("schedules", [])
                                         for i in s.get("source_docs", [])}),
        ("requests", lambda d: {d["request_document"]} if d.get("request_document") else set()),
        ("utility_rates", lambda d: {d["source_doc"]} if d.get("source_doc") else set()),
        ("revenue", lambda d: {d["source_doc"]} if d.get("source_doc") else set()),
        ("workbook_b", lambda d: set(d.get("source_docs", []))),
        ("warehouse_county", lambda d: {d["source_doc"]} if d.get("source_doc") else set()),
        ("structure", lambda d: (
            ({d["already_shared"]["source_doc"]} if (d.get("already_shared") or {}).get("source_doc")
             else set())
            | set((d.get("run_separately") or {}).get("source_docs", []))
            | {t["source_doc"] for t in (d.get("already_shared") or {})
               .get("what_the_town_records_paying", []) if t.get("source_doc")})),
        ("context", lambda d: {q["source_doc"] for q in
                               (d.get("finance_director_on_debt") or {}).get("quotes", [])
                               if q.get("source_doc")}),
        ("issues", lambda d: {i["source_doc"] for i in d.get("issues", [])
                              if i.get("source_doc")}),
    ]:
        blob = maybe(name)
        if blob:
            ids = get(blob)
            if ids:
                cited[name] = ids

    # Some stages recorded provenance as a filename rather than a manifest id;
    # both resolve here, and anything that resolves to neither fails the build.
    def resolve(ref):
        return ref if ref in doc_ids else by_filename.get(ref, ref)

    cited = {name: {resolve(r) for r in ids} for name, ids in cited.items()}
    cited_ids = sorted(set().union(*cited.values()))
    unknown_cited = [i for i in cited_ids if i not in doc_ids]
    if unknown_cited:
        sys.exit(f"published data cites documents missing from the manifest: {unknown_cited}")
    # Outside the datasets whose scan handling is counted precisely above, no
    # dataset may cite a scanned document at all — each such citation counts.
    for name, ids in cited.items():
        if name not in ("facts", "lineitems", "ocr_statements", "audited"):
            scan_text_figures += sum(1 for i in ids if i in scan_ids)

    # The year the site leads with, derived once so the site and its tests cannot
    # drift apart: the newest year the town has stated as an actual budget.
    headline_fy = (max(r[li["columns"].index("fiscal_year")] for r in li["rows"]
                       if r[li["columns"].index("basis")] == "budget") if li else None)

    # FAIL CLOSED on the one thing this entire pipeline exists to prevent. The count
    # used to be computed, written into index.json, and otherwise ignored — so a
    # figure read straight off a scan's digit-transposing text layer could be
    # published, and the only trace was a number in a JSON file nobody diffs.
    if scan_text_figures:
        sys.exit(f"\nBUILD FAILED — {scan_text_figures} published figure(s) trace to a "
                 f"scanned document's embedded text layer, which transposes digits "
                 f"(4,610,003 reads as 460,100,3). Nothing may be published from that "
                 f"text. Use a digital original, or fresh recognition gated on the "
                 f"page's own arithmetic (stages 61/75).")

    fy = [f["fiscal_year"] for f in facts if f.get("fiscal_year")]
    write_json(DATA / "index.json", {
        "project": "Orange County Efficiency & Accountability Initiative",
        "jurisdictions": sorted({f["jurisdiction"] for f in facts}),
        "fiscal_year_range": [min(fy), max(fy)] if fy else None,
        "headline_fiscal_year": headline_fy,
        # The distinct manifest documents the published datasets cite — the evidence
        # base, as opposed to counts.documents, which is the size of the archive.
        "cited_documents": cited_ids,
        "counts": {
            "facts": len(facts),
            "metrics": len(METRICS),
            "documents": len(docs_blob["documents"]),
            "documents_cited": len(cited_ids),
            "documents_with_trustworthy_text": docs_blob["summary"]["pdf_digital_text"],
            "documents_scanned_needing_transcription": docs_blob["summary"]["pdf_scanned_ocr"],
            # Published values whose provenance is a scanned page's embedded text
            # layer — measured across every dataset above, not just the headline
            # facts. The whole pipeline exists to keep this zero.
            "figures_read_from_scan_text": scan_text_figures,
            "ocr_figures_published": len(ocr.get("published", [])) if ocr else 0,
            "multi_document_comparisons": len(projections),
            **({} if not li else {
                "line_item_observations": len(li["rows"]),
                "line_item_accounts": len({r[3] for r in li["rows"]}),
                "departments": len({r[1] for r in li["rows"]}),
            }),
            **({} if not liv else {
                "reconciliation_checks_passed": liv["summary"]["reconciled"],
                "reconciliation_checks_total": liv["summary"]["total"],
                "reconciliation_unexplained": liv["summary"]["unexplained"],
            }),
        },
        "datasets": {
            "facts": "datasets/facts.json",
            "metrics": "datasets/metrics.json",
            "documents": "datasets/documents.json",
            "projections": "datasets/projections.json",
            "requests": "datasets/requests.json",
            "issues": "datasets/issues.json",
            # carries civic_participation, which is text and must never be charted
            "household": "datasets/facts_household.json",
            # large; the site fetches these only when the reader opens the
            # spending explorer, so the first paint stays light on a phone
            "lineitems": "datasets/lineitems.json",
            "lineitem_validation": "datasets/lineitem_validation.json",
            # audited outcome — small, loaded with the first paint
            "audited": "datasets/audited_general_fund.json",
            # audited totals recovered from scans, each proven by its own page
            "ocr_statements": "datasets/ocr_statements.json",
            "ocr_manifest": "datasets/ocr_manifest.json",
            # curated Orange County warehouse, imported and re-verified
            "warehouse_county": "datasets/warehouse_county.json",
            # conformance against the MFAS seven-dimension grain contract
            "mfas": "datasets/mfas_conformance.json",
            # cross-fund transfer schedule (requested by Amy)
            "transfers": "datasets/transfer_schedule.json",
            # block-rate water/sewer structure, so a reader can enter their own usage
            "utility": "datasets/utility_rates.json",
            # tax rate history for both governments, corroborated across ACFR editions
            "cost_of_ownership": "datasets/total_cost_of_ownership.json",
            # Project as a real dimension (Amy's decision) — the capital project register
            "projects": "datasets/projects.json",
            # what was funded, what was declined, and the town's stated consequence
            "tradeoffs": "datasets/tradeoffs.json",
            # the initiative's own analysis workbooks, imported and cross-checked
            "workbook_b": "datasets/workbook_b.json",
            # who provides which services, and the Finance Director's own words on debt
            "context": "datasets/context.json",
            # the open-questions register Amy asked for, with an owner per item
            "questions": "datasets/questions.json",
            # where the money comes from, beyond property tax
            "revenue": "datasets/revenue.json",
            # the structural question, posed with evidence and left open
            "structure": "datasets/structure.json",
        },
    })

    print(f"\n  {len(facts)} facts across {len(METRICS)} metrics — integrity OK")
    print(f"  {len(projections)} multi-document comparisons")
    if warnings:
        print(f"  {len(warnings)} warning(s):")
        for w in warnings[:10]:
            print(f"      {w}")


if __name__ == "__main__":
    main()
