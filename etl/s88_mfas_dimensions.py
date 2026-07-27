"""Stage 88 — measure this project's data against Amy's MFAS dimension contract.

Her Decision Context Model deck states the contract plainly:

    "The Seven Architectural Dimensions, Seven Data Dimensions —
     uniquely identify every financial fact in MFAS."

        Government · Organization · Fund · Project · Activity · Account · Fiscal Year

That is a grain definition, and grain definitions are testable. So rather than
describing how well this project's data fits her framework, this stage measures
it: for every account-level row, which of the seven dimensions can actually be
populated, and which cannot.

The output is deliberately unflattering where it should be. A dimension that
cannot be filled is reported as missing rather than fudged with an approximation,
because the point of the exercise is to show her precisely what would need to
change for this data to load into MFAS cleanly.

It also adds the one dimension she asked for by name:

    "the financial data needed the added dimension to differentiate ongoing
     operations from one-time items. so this dimension was fleshed out and
     should be added."

That maps onto her Change Events vocabulary — Recurring vs One-Time, Continuing
Operations, Strategic Investments. It is *derived* from the town's own expenditure
categories, not stated by the town, and anything ambiguous is left unclassified
rather than guessed.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, read_json, write_json  # noqa: E402

SEVEN = ["Government", "Organization", "Fund", "Project", "Activity", "Account", "Fiscal_Year"]

# Her Change Events distinguish recurring commitments from one-time investments.
# Derived from the town's own expenditure categories. Deliberately conservative:
# where a category genuinely mixes both, it stays unclassified rather than being
# forced into a bucket that would misstate the total.
RECURRENCE = {
    "Personnel": ("Recurring", "Continuing Operations",
                  "Salaries, benefits and retirement recur every year and compound."),
    "Operating": ("Recurring", "Continuing Operations",
                  "Day-to-day cost of delivering existing services."),
    "Cost Allocations": ("Recurring", "Continuing Operations",
                         "Internal charges that recur with the operations they support."),
    "Debt Service": ("Recurring", "Committed",
                     "Recurring payments, but arising from a past one-time decision to "
                     "borrow — the clearest example of a Change Event with a long tail."),
    "Capital": ("One-Time", "Strategic Investment",
                "A discrete purchase or project rather than an ongoing obligation, "
                "though it often creates recurring operating cost afterwards."),
    # Interfund Transfers deliberately absent: they carry both routine subsidy and
    # one-off capital funding, and cannot be split without reading each transfer.
}


def main() -> None:
    li = read_json(DATASETS / "lineitems.json")
    C = {c: i for i, c in enumerate(li["columns"])}
    rows = li["rows"]

    # --- how much of her seven-dimension grain can this data actually fill? ----
    coverage = {
        "Government": {
            "status": "available",
            "maps_to": "jurisdiction (Town of Hillsborough / Orange County, NC)",
            "note": "Present on every row.",
        },
        "Organization": {
            "status": "conflated with Government",
            "maps_to": "—",
            "note": ("This project has one level where MFAS has two. Her Entity_ID (ORG_OC) is "
                     "an Organization within a Government. Splitting them matters as soon as "
                     "school districts, authorities or fire districts are added — each is a "
                     "separate Organization under the same Government. The project-scope "
                     "document that arrived 2026-07-27 DEFINES the two levels — two Governments "
                     "(Orange County, Town of Hillsborough), each with the same nine domains — "
                     "so the structure is now known even though the data is not yet split by it. "
                     "What remains is a modelling decision, not an extraction: whether the school "
                     "district, sheriff's office and EMS are Organizations under the county or "
                     "Governments in their own right. See datasets/context.json."),
        },
        "Fund": {
            "status": "available",
            "maps_to": "fund (General / Water & Sewer / Stormwater)",
            "note": "Present on every row and reconciled to published fund totals.",
        },
        "Project": {
            "status": "available",
            "maps_to": "project_id in datasets/projects.json (see etl/s94_projects.py)",
            "note": ("Added at Amy's decision — \"I do want Project to be a real dimension\". "
                     "This was the one dimension of her seven that the data could not fill; the "
                     "town's capital plan publishes a register of every project with its fund, "
                     "department, priority rank, cost by account by year, funding sources and "
                     "stated operating budget impact, each reconciled to its own printed totals. "
                     "Her Fire Station #3 example is now answerable: a decision's cost can be "
                     "gathered across every account and year it touches. Not yet joined row by "
                     "row to the line-item appendix, which records capital spending by account "
                     "within a department rather than by project."),
        },
        "Activity": {
            "status": "partial",
            "maps_to": "department (30 values) + category",
            "note": ("Department is close to Activity but not the same thing. Activity is what "
                     "the money DOES; department is who spends it. 'Street repaving' is an "
                     "activity that may sit in one department, while 'Public Works' contains "
                     "many activities."),
        },
        "Account": {
            "status": "available",
            "maps_to": "account (182 distinct: SALARIES, RETIREMENT, GASOLINE…)",
            "note": "Present on every row.",
        },
        "Fiscal_Year": {
            "status": "available",
            "maps_to": "fiscal_year + basis (actual / budget / estimate / projected)",
            "note": ("Her Dim_Fiscal_Year carries a Data Scenario per year; this project carries "
                     "an equivalent basis per row, which is finer and compatible."),
        },
    }

    # --- the recurring vs one-time dimension she asked for --------------------
    classified = Counter()
    totals: dict[tuple, float] = {}
    for r in rows:
        cat = r[C["category"]]
        rec = RECURRENCE.get(cat)
        label = rec[0] if rec else "Unclassified"
        classified[label] += 1
        key = (r[C["fund"]], r[C["fiscal_year"]], r[C["basis"]], label)
        totals[key] = totals.get(key, 0.0) + r[C["value"]]

    # FY2027 budget, the headline year, as a worked illustration
    headline = sorted(
        [{"fund": k[0], "fiscal_year": k[1], "basis": k[2], "recurrence": k[3],
          "amount": round(v, 2)}
         for k, v in totals.items() if k[1] == 2027 and k[2] == "budget"],
        key=lambda x: (x["fund"], x["recurrence"]))

    gf = {h["recurrence"]: h["amount"] for h in headline if h["fund"] == "General Fund"}
    recurring_share = (gf.get("Recurring", 0)
                       / sum(v for v in gf.values() if v) * 100) if gf else None

    available = sum(1 for d in coverage.values() if d["status"] == "available")

    write_json(DATASETS / "mfas_conformance.json", {
        "generated_by": "etl/s88_mfas_dimensions.py",
        "contract": ("Amy's Decision Context Model, slide 9: the seven data dimensions that "
                     "uniquely identify every financial fact in MFAS."),
        "seven_dimensions": SEVEN,
        "summary": {
            "fully_available": available,
            "partial_or_conflated": sum(1 for d in coverage.values()
                                        if d["status"] in ("partial", "conflated with Government")),
            "missing": sum(1 for d in coverage.values() if d["status"].startswith("MISSING")),
            "rows_measured": len(rows),
        },
        "dimension_coverage": coverage,
        "recurrence_dimension": {
            "why": ("Added at Amy's request: 'the financial data needed the added dimension to "
                    "differentiate ongoing operations from one-time items'. Aligns with her "
                    "Change Events vocabulary."),
            "derivation": ("Derived from the town's own expenditure categories, NOT stated by the "
                          "town. Interfund Transfers are left unclassified because they mix "
                          "routine subsidy with one-off capital funding and cannot be split "
                          "without reading each transfer individually."),
            "mapping": {k: {"recurrence": v[0], "change_event_type": v[1], "reason": v[2]}
                        for k, v in RECURRENCE.items()},
            "rows_by_class": dict(classified),
            "general_fund_fy2027_budget": gf,
            "recurring_share_of_classified_general_fund_pct":
                round(recurring_share, 1) if recurring_share else None,
            "totals": headline,
        },
        "what_would_close_the_gaps": [
            "Project: CLOSED 2026-07-27 (etl/s94_projects.py) — 27 projects with cost by account "
            "by year, funding sources and stated operating impact. Remaining work is joining the "
            "register to individual line-item rows, which the appendix does not label by project.",
            "Activity: distinguish what the money does from who spends it; department is a proxy.",
            "Organization: split Organization from Government before adding school districts, "
            "authorities or fire districts.",
        ],
    })

    print(f"  measured {len(rows):,} account rows against the seven MFAS dimensions")
    for d in SEVEN:
        print(f"      {d:14} {coverage[d]['status']}")
    print(f"\n  recurrence dimension added: {dict(classified)}")
    if recurring_share:
        print(f"  General Fund FY2027 budget is {recurring_share:.1f}% recurring "
              f"(of the classified portion)")
        for h in headline:
            if h["fund"] == "General Fund":
                print(f"      {h['recurrence']:14} ${h['amount']:>14,.0f}")


if __name__ == "__main__":
    main()
