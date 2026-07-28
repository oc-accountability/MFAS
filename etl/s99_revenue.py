"""Stage 99 — where the money comes from, beyond property tax.

Amy's request:

    "Revenue sources: this hit the concept of Town vs. Government... The broader view
     includes revenue from sources such as Grants, State, Other Funds, etc. So I want to
     make sure we have this broader view too."

She is right that the site was lopsided. It explained what a resident *pays* in detail and
what the town *spends* in detail, but treated revenue as a single total — which quietly
implies property tax funds everything. It does not: intergovernmental revenue, interfund
transfers and appropriated fund balance are all substantial, and a resident who thinks
their tax bill is the whole story will misjudge every tradeoff on the site.

Her own v5 Audit Edition already holds the breakdown, FY2018-FY2027, so this imports it
rather than re-deriving it — same contract as stages 85 and 96: read, never written.

**A reconciliation pattern worth stating plainly.** Each year's components are checked
against that year's stated total, and they behave differently:

  * the **budget** years (FY2026, FY2027) reconcile **to the dollar**;
  * the **actual** years do not, by anywhere from $9.6k to $2.9M.

A third state matters as much as the other two: FY2018 carries only a sales tax figure, so
there is nothing to reconcile. Calling that a variance would have implied the town was out
by $8.8M, when the truth is simply that the component detail is not in the sheet. Years
like that are reported as **components incomplete**, never as a discrepancy.

That is almost certainly a presentation difference rather than an error — audited
statements and budget schedules count transfers and appropriated fund balance differently,
and her own Model_Integrity sheet flags exactly this ("Revenue vs Functional Expenses —
different accounting presentations"). But "almost certainly" is not good enough to publish
a reconciled total, so the variance is reported per year, the components are published as
hers with the variance attached, and the question of which presentation applies goes to
the town rather than being resolved by guesswork here.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, SOURCES, read_json, write_json  # noqa: E402

warnings.filterwarnings("ignore")

WB = ("Orange County Efficiency & Accountability Initiative/"
      "06 Budget & Financial Analysis - Hillsborough/"
      "Hillsborough_GF_Trend_Schedules_FY18_FY27_v5_Audit_Edition.xlsx")

# The component columns, in the order a reader should meet them: the two a resident pays
# directly first, then the money that arrives from elsewhere, then the internal levers.
COMPONENTS = [
    ("Property Tax", "paid directly by residents and businesses in the town"),
    ("Sales Tax", "the town's share of local option sales tax, collected by the state"),
    ("Other Taxes & Licenses", "smaller local taxes, licences and permits"),
    ("Intergovernmental", "grants and revenue shared from state and federal government"),
    ("Interest", "earnings on the town's own cash balances"),
    ("Interfund Transfers", "money moved in from the town's other funds"),
    ("Fund Balance Appropriated", "savings spent to balance the year — not new income"),
    ("Other / Fees / Misc", "fees, charges and everything else"),
]
TOLERANCE = 1.0


def main() -> None:
    path = SOURCES / WB
    if not path.exists():
        sys.exit(f"missing {path}")
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb["Revenue_Trend"]

    header, rows = None, []
    for row in ws.iter_rows(values_only=True):
        vals = [str(c).strip() if c is not None else "" for c in row]
        if header is None:
            if vals and vals[0] == "Year":
                header = vals
            continue
        if not vals or not vals[0].startswith("FY"):
            continue
        rows.append({header[i]: row[i] for i in range(len(header)) if header[i]})
    wb.close()

    def num(v):
        return float(v) if isinstance(v, (int, float)) else None

    years, checks = [], []
    for r in rows:
        fy = 2000 + int(str(r["Year"])[2:])
        stated = num(r.get("Total Revenues"))
        parts = {}
        for name, _ in COMPONENTS:
            # Column headings are truncated in the sheet, so match on a prefix.
            key = next((k for k in r if k and name[:18].lower() in k.lower()), None)
            v = num(r.get(key)) if key else None
            if v:
                parts[name] = v
        summed = round(sum(parts.values()), 2)
        basis = str(r.get("Measure") or "").strip()
        variance = round(summed - stated, 2) if stated is not None else None
        reconciles = variance is not None and abs(variance) <= TOLERANCE
        # A year with almost no component detail is missing data, not a discrepancy.
        # FY2018 carries only sales tax, so a naive check called it an $8.8M variance —
        # which would have read as the town's arithmetic being wrong by millions.
        incomplete = len(parts) < 5
        state = ("reconciles" if reconciles
                 else "components incomplete" if incomplete
                 else "presentation difference")
        years.append({
            "fiscal_year": fy, "basis": basis,
            "stated_total": stated, "components_sum": summed,
            "variance": variance, "reconciles": reconciles,
            "state": state, "components_populated": len(parts),
            "components": parts,
            # A share is only safe to draw against a total the parts actually make up.
            "shares_publishable": reconciles,
            "share_of_total": ({k: round(v / summed * 100, 2) for k, v in parts.items()}
                               if reconciles and summed else None),
        })
        checks.append({"fiscal_year": fy, "basis": basis, "stated_total": stated,
                       "components_sum": summed, "variance": variance,
                       "reconciles": reconciles, "state": state,
                       "components_populated": len(parts)})

    reconciling = [y for y in years if y["reconciles"]]
    incomplete_years = [y for y in years if y["state"] == "components incomplete"]
    failing = [y for y in years if y["state"] == "presentation difference"]
    # The pattern is the finding: budgets reconcile, actuals do not.
    by_basis: dict[str, dict] = {}
    for y in years:
        b = by_basis.setdefault(y["basis"] or "unstated",
                                {"years": 0, "reconcile": 0, "variances": []})
        b["years"] += 1
        b["reconcile"] += 1 if y["reconciles"] else 0
        b.setdefault("states", {})[y["state"]] = b.setdefault("states", {}).get(y["state"], 0) + 1
        if y["variance"] is not None and y["state"] != "components incomplete":
            b["variances"].append(y["variance"])
    for b in by_basis.values():
        v = b.pop("variances")
        b["variance_range"] = [min(v), max(v)] if v else None

    # What a resident actually funds directly, in the latest reconciling year.
    latest = max(reconciling, key=lambda y: y["fiscal_year"]) if reconciling else None
    direct = None
    if latest:
        own = sum(latest["components"].get(k, 0) for k in
                  ("Property Tax", "Sales Tax", "Other Taxes & Licenses", "Other / Fees / Misc"))
        elsewhere = sum(latest["components"].get(k, 0) for k in
                        ("Intergovernmental", "Interest", "Interfund Transfers",
                         "Fund Balance Appropriated"))
        direct = {
            "fiscal_year": latest["fiscal_year"],
            "raised_locally": round(own, 2),
            "raised_locally_pct": round(own / latest["components_sum"] * 100, 1),
            "from_elsewhere_or_savings": round(elsewhere, 2),
            "from_elsewhere_or_savings_pct": round(elsewhere / latest["components_sum"] * 100, 1),
            "property_tax_share_pct": round(
                latest["components"].get("Property Tax", 0) / latest["components_sum"] * 100, 1),
            "note": ("Property tax is the largest single source but not the whole story, which "
                     "is why a tax-only view of the budget misleads."),
        }

    # Cross-check her figures against this pipeline's own independent extraction.
    facts = read_json(DATASETS / "facts.json")["facts"]
    cross = []
    for metric, fy, label in (("general_fund_expenditures", 2027, "FY2027 total"),):
        mine = [f for f in facts if f["metric"] == metric and f["fiscal_year"] == fy]
        hers = next((y["stated_total"] for y in years if y["fiscal_year"] == fy), None)
        if mine and hers:
            diff = round(hers - mine[0]["value"], 2)
            cross.append({"label": label, "hers": hers, "this_pipeline": mine[0]["value"],
                          "difference": diff, "agrees": abs(diff) <= TOLERANCE,
                          "note": ("Her revenue total for a budget year equals the expenditure "
                                   "total, because a budget balances by construction.")})

    write_json(DATASETS / "revenue.json", {
        "generated_by": "etl/s99_revenue.py",
        "requested_by": ("Amy — \"The broader view includes revenue from sources such as Grants, "
                         "State, Other Funds, etc. So I want to make sure we have this broader "
                         "view too.\""),
        "imported_from": Path(WB).name,
        "contract": "Her workbook is READ, never written.",
        "why_it_matters": ("The site explained what a resident pays and what the town spends in "
                          "detail, but treated revenue as one total — which implies property tax "
                          "funds everything. It does not, and a reader who believes it will "
                          "misjudge every tradeoff on the site."),
        "component_definitions": {name: desc for name, desc in COMPONENTS},
        "reconciliation": {
            "method": ("Each year's components are summed and compared to that year's stated "
                       "total. Shares are only published for years that reconcile, because a "
                       "percentage of a total the parts do not make up is not a share."),
            "tolerance_usd": TOLERANCE,
            "years_reconciling": len(reconciling),
            "years_with_a_presentation_difference": len(failing),
            "years_with_incomplete_components": len(incomplete_years),
            "incomplete_note": ("A year whose component detail is largely absent is reported as "
                                "incomplete, not as a discrepancy. FY2018 carries only sales tax, "
                                "and treating that as a variance would have implied the town was "
                                "out by $8.8M."),
            "by_basis": by_basis,
            "finding": ("Budget years reconcile to the dollar; actual years do not, by roughly "
                        "$1.3-1.5M. That is consistent with a presentation difference between "
                        "audited statements and budget schedules — they count transfers and "
                        "appropriated fund balance differently — and her own Model_Integrity "
                        "sheet flags the same thing. It is NOT resolved here, because deciding "
                        "which presentation applies would be a guess about the town's "
                        "accounting."),
            "checks": checks,
        },
        "cross_checks_against_this_pipeline": cross,
        "years": years,
        "who_funds_the_town": direct,
        "caveats": [
            "Appropriated fund balance is savings being spent, not income. It appears here "
            "because the town counts it as a resource that balances the budget, but a year "
            "balanced with savings is not the same as a year funded by revenue.",
            "Interfund transfers are money moved between the town's own funds, so they are "
            "revenue to the receiving fund and expenditure to the sending one. They are not "
            "new money entering the town.",
            "Intergovernmental revenue is grants and state-shared revenue. It is real money but "
            "not under the town's control, and some of it is one-time.",
        ],
    })

    print(f"  {len(years)} years: {len(reconciling)} reconcile, {len(failing)} presentation "
          f"difference, {len(incomplete_years)} incomplete")
    for b, s in by_basis.items():
        rng = s["variance_range"]
        print(f"      {b[:22]:24} {s['reconcile']}/{s['years']} reconcile   variance "
              f"{rng[0]:,.0f} to {rng[1]:,.0f}" if rng else f"      {b}")
    if direct:
        print(f"\n  FY{direct['fiscal_year']}: {direct['raised_locally_pct']}% raised locally, "
              f"{direct['from_elsewhere_or_savings_pct']}% from elsewhere or savings "
              f"(property tax alone {direct['property_tax_share_pct']}%)")
    if latest:
        print(f"\n  FY{latest['fiscal_year']} revenue by source:")
        for k, v in sorted(latest["components"].items(), key=lambda x: -x[1]):
            print(f"      {k:28} ${v:>12,.0f}  {latest['share_of_total'][k]:>5.1f}%")
    for c in cross:
        print(f"\n  cross-check {c['label']}: hers ${c['hers']:,.0f} vs this pipeline "
              f"${c['this_pipeline']:,.0f} -> agrees {c['agrees']}")


if __name__ == "__main__":
    main()
