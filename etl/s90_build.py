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
}

STAGE_FACT_FILES = ["facts_xlsx.json", "facts_budget.json"]


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
            warnings.append(f"{where}: unit {f.get('unit')!r} != registry {m['unit']!r}")

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

    fy = [f["fiscal_year"] for f in facts if f.get("fiscal_year")]
    write_json(DATA / "index.json", {
        "project": "Orange County Efficiency & Accountability Initiative",
        "jurisdictions": sorted({f["jurisdiction"] for f in facts}),
        "fiscal_year_range": [min(fy), max(fy)] if fy else None,
        "counts": {
            "facts": len(facts),
            "metrics": len(METRICS),
            "documents": len(docs_blob["documents"]),
            "documents_with_trustworthy_text": docs_blob["summary"]["pdf_digital_text"],
            "documents_scanned_needing_transcription": docs_blob["summary"]["pdf_scanned_ocr"],
            "multi_document_comparisons": len(projections),
        },
        "datasets": {
            "facts": "datasets/facts.json",
            "metrics": "datasets/metrics.json",
            "documents": "datasets/documents.json",
            "projections": "datasets/projections.json",
            "requests": "datasets/requests.json",
            "issues": "datasets/issues.json",
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
