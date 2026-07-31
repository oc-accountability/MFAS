"""Stage 80 — Orange County, the larger half of a resident's property tax bill.

Until now the site computed only the Town of Hillsborough's share and said so
honestly. That was a big understatement: the **county** rate is larger than the
town's, so a Hillsborough household was seeing roughly 43% of what it actually
pays in property tax.

    Town of Hillsborough   51.30 cents per $100
    Orange County          67.58 cents per $100
    ----------------------------------------------
    Combined              118.88 cents per $100

Source: the county manager's FY2026-27 budget message. Every county document in
the archive is **digital text**, so none of the character-recognition machinery
that the town's scanned reports require applies here — these figures are read
directly.

A caution encoded in the output: the county also levies **fire district** taxes,
which vary by district and which this stage does not attempt to attribute to an
individual address. So the combined figure is "town + county", explicitly not
"your entire tax bill".
"""
from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, SOURCES, Fact, DIGITAL, STATED, write_json, report_and_gate  # noqa: E402

warnings.filterwarnings("ignore")

JUR = "Orange County, NC"
COUNTY_DIR = ("Orange County Efficiency & Accountability Initiative/"
              "06b Budget & Fin. Analysis - OC/")
DOC_ID = "fy202627-managers-messager"
DOC_FILE = "FY202627 Managers MessageR.pdf"

# (metric, unit, basis, fiscal_year, pattern, note)
SCALARS = [
    ("county_property_tax_rate", "cents_per_100_valuation", "recommended", 2027,
     r"from 63\.83\s*\n?\s*cents to ([\d.]+) cents per \$100 of assessed value",
     "The countywide rate. A Hillsborough household pays this IN ADDITION to the town rate."),
    ("county_property_tax_rate_prior", "cents_per_100_valuation", "adopted", 2026,
     r"from ([\d.]+)\s*\n?\s*cents to [\d.]+ cents per \$100 of assessed value",
     "The prior year's countywide rate."),
    ("county_tax_rate_increase_cents", "cents_per_100_valuation", "recommended", 2027,
     r"Countywide tax rate increases by ([\d.]+) cents per \$100",
     "The recommended increase over the prior year."),
    ("county_revenue_per_cent_of_tax_rate", "USD", "stated", 2027,
     r"each one cent on the tax rate generates \$([\d,]+)",
     "The county's own conversion factor — what one cent raises countywide. Compare with the "
     "town's $240,000: the county's tax base is far larger."),
    ("county_tax_increase_on_500k_home", "USD", "recommended", 2027,
     r"on a home valued at \$500,000 is\s*\n?\s*\$([\d,.]+) per year",
     "The county's own worked example of the increase, useful as a cross-check."),
    # \s+ not a literal space: the PDF wraps between "new" and "General".
    ("county_new_general_fund_revenue", "USD", "recommended", 2027,
     r"new\s+General Fund Revenue totaled \$([\d,]+)", ""),
    ("county_new_general_fund_expenses", "USD", "recommended", 2027,
     r"New\s+General Fund expenses totaled \$([\d,]+)", ""),
]


def main() -> None:
    path = SOURCES / COUNTY_DIR / DOC_FILE
    if not path.exists():
        sys.exit(f"missing {path}")
    problems: list[str] = []

    with pdfplumber.open(path) as pdf:
        pages = {i: (pg.extract_text() or "") for i, pg in enumerate(pdf.pages, 1)}
    full = "\n".join(pages.values())

    facts: list[Fact] = []
    for metric, unit, basis, fy, pattern, note in SCALARS:
        m = re.search(pattern, full)
        if not m:
            problems.append(f"MISS {metric}")
            continue
        page = next((i for i, t in pages.items() if re.search(pattern, t)), None)
        facts.append(Fact(
            jurisdiction=JUR, fiscal_year=fy, metric=metric,
            value=float(m.group(1).replace(",", "")), unit=unit, basis=basis,
            source_doc=DOC_ID, source_page=page,
            source_detail=f"stated in prose: …{' '.join(m.group(0).split())[:70]}…",
            extraction=STATED if basis == "stated" else DIGITAL, note=note,
        ))

    # Prove the reading against the county's own worked example: 3.75 cents on a
    # $500,000 home should be $187.50. If our rate and increase are right, this
    # arithmetic lands exactly — if it does not, one of them was misread.
    checks = []
    inc = next((f.value for f in facts if f.metric == "county_tax_rate_increase_cents"), None)
    example = next((f.value for f in facts
                    if f.metric == "county_tax_increase_on_500k_home"), None)
    if inc is not None and example is not None:
        derived = 500000 / 100 * (inc / 100)
        ok = abs(derived - example) < 0.51
        checks.append({
            "check": "county_increase_cross_validation",
            "stated_increase_on_500k_home": example,
            "derived_from_rate": round(derived, 2),
            "agree": ok,
            "detail": (f"{inc} cents on a $500,000 home is ${derived:,.2f}; the county's message "
                       f"states ${example:,.2f}."),
        })
        if not ok:
            problems.append(f"county increase cross-check FAILED: derived {derived:.2f} "
                            f"vs stated {example:.2f}")

    write_json(DATASETS / "facts_county.json", {
        "generated_by": "etl/s80_county.py",
        "note": ("Orange County figures. Every county document in the archive is digital text, so "
                 "none of the character-recognition handling that the town's scanned reports "
                 "require applies to these."),
        "important": ("A Hillsborough household pays the county rate IN ADDITION to the town rate. "
                      "Combined they are roughly 118.9 cents per $100 — more than twice the town "
                      "rate alone. The county also levies fire district taxes that vary by "
                      "district and are NOT included here, so 'town + county' is not necessarily "
                      "a household's entire property tax bill."),
        "consistency_checks": checks,
        "extraction_problems": problems,
        "facts": [f.as_row() for f in facts],
    })

    print(f"  {len(facts)} county facts from {DOC_FILE}")
    for f in facts:
        print(f"      FY{f.fiscal_year} {f.metric:44} {f.value:>13,.2f} {f.unit}")
    report_and_gate("stage 80", problems, checks)


if __name__ == "__main__":
    main()
