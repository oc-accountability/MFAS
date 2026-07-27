"""Stage 40 — what next year actually costs a household.

The politically salient fact in the FY2027 budget is that the property tax rate
does **not** change, while water and sewer rates rise 7.5% each. A resident who
hears "no tax increase" still pays more. The budget message states the monthly
dollar impact directly, broken out by whether the household is inside town
limits and by consumption level, so those figures are extracted here rather than
computed — the town's own arithmetic, not ours.

Dimensions (location × consumption) are encoded in the metric name because the
Fact schema is intentionally flat. Every one is registered in s90_build.py.
"""
from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, SOURCES, Fact, DIGITAL, STATED, write_json  # noqa: E402

warnings.filterwarnings("ignore")

JUR = "Town of Hillsborough, NC"
DOC = "fy27-budget-message"
PATH = SOURCES / ("Orange County Efficiency & Accountability Initiative/"
                  "02 Research & Documents/Hillsborough Budget/FY27 Budget Message.pdf")

RATE_NOTE = ("The town's own stated monthly increase from FY2026 to FY2027, not a figure we "
             "computed. The property tax rate is unchanged this year, so for most households "
             "this utility increase is the actual change in what they pay the town.")


def parse_rate_impact(pages: dict[int, str], problems: list[str]) -> list[Fact]:
    """Read the 'Rate Impact' block.

    Layout in the extracted text:
        In-Town Rates
        Water $3.72 $1.86          <- average (4,000 gal), then minimum (2,000 gal)
        Sewer $5.24 $2.62
        Out-of-Town Rates
        Water $7.24 $3.62
        Sewer $10.20 $5.10
    """
    facts: list[Fact] = []
    page = next((n for n, t in pages.items() if "Rate Impact" in t), None)
    if page is None:
        problems.append("MISS 'Rate Impact' block")
        return facts
    text = pages[page]

    # Confirm the consumption assumptions are the ones we are about to label.
    avg = re.search(r"([\d,]+)\s*gallons per month\s+([\d,]+)\s*gallons per month", text)
    if not avg:
        problems.append("MISS the consumption-level header; not labelling avg/min")
        return facts
    avg_gal, min_gal = avg.group(1), avg.group(2)

    block = text[text.find("Rate Impact"):]
    for loc_label, loc_key in (("In-Town Rates", "intown"), ("Out-of-Town Rates", "outoftown")):
        i = block.find(loc_label)
        if i < 0:
            problems.append(f"MISS {loc_label}")
            continue
        seg = block[i:i + 220]
        for util in ("Water", "Sewer"):
            m = re.search(rf"{util}\s+\$([\d.,]+)\s+\$([\d.,]+)", seg)
            if not m:
                problems.append(f"MISS {loc_label} / {util}")
                continue
            for gal, raw, level in ((avg_gal, m.group(1), "avg"), (min_gal, m.group(2), "min")):
                facts.append(Fact(
                    jurisdiction=JUR, fiscal_year=2027,
                    metric=f"{util.lower()}_bill_increase_monthly_{loc_key}_{level}",
                    value=float(raw.replace(",", "")), unit="USD_per_month",
                    basis="recommended", source_doc=DOC, source_page=page,
                    source_detail=f"Rate Impact — {loc_label}, {util}, {gal} gal/month",
                    extraction=DIGITAL,
                    note=RATE_NOTE + f" Assumes {gal} gallons per month.",
                ))
    return facts


SCALARS = [
    # Anchored on the page-4 prose, NOT the front-page summary box. That box is laid
    # out in two columns, so "Sewer Rate" and its "7.5% increase over FY26 rate" value
    # extract onto non-adjacent lines with unrelated prose interleaved between them —
    # a regex spanning them would silently pair the wrong label with the wrong number.
    ("sewer_rate_increase_pct", "percent", "recommended",
     r"Sewer Rates\s*\n?\s*A ([\d.]+)% increase is recommended", 2027,
     "Recommended for each of the next three years. Matches the water increase."),
    ("stormwater_fee_increase_per_eru", "USD", "recommended",
     r"\$(\d+) per ERU\*? increase over FY26 fee", 2027,
     "Per Equivalent Residential Unit. The budget message does not state whether this is a "
     "monthly or annual figure, so no annual household total is derived from it here."),
    ("affordable_housing_tax_rate_equivalent_cents", "cents_per_100_valuation", "stated",
     r"until meeting the equivalent of (\d+) cents on the property tax rate", 2027,
     "The board agreed in FY2024 to raise affordable-housing spending annually until it reaches "
     "this share of the tax rate."),
    ("salary_benefit_tax_rate_equivalent_cents", "cents_per_100_valuation", "stated",
     r"which is equivalent to approximately ([\d.]+) cents on the tax rate", 2027,
     "The FY2027 salary and benefit increase, expressed as tax-rate cents."),
    ("fy29_scenario_increase_on_400k_home", "USD", "projected",
     r"about a \$(\d+) annual increase on a \$400,000 home", 2029,
     "The town's own worked example for the FY2029 deficit scenario. Useful as a cross-check on "
     "the household calculator: at 51.3 cents a $400,000 home pays about $2,052, and each cent "
     "adds $40, so $440 implies roughly an 11-cent increase — consistent with the text's "
     "'over 10 cents'."),
    ("nonprofit_partnership_funding", "USD", "adopted",
     r"set the FY27 funding level at \$([\d,]+)", 2027,
     "Town funding for nonprofit partners, set after a public hearing."),
]


def main() -> None:
    if not PATH.exists():
        sys.exit(f"missing {PATH}")
    problems: list[str] = []
    with pdfplumber.open(PATH) as pdf:
        pages = {i: (pg.extract_text() or "") for i, pg in enumerate(pdf.pages, 1)}
    full = "\n".join(pages.values())

    facts = parse_rate_impact(pages, problems)

    for metric, unit, basis, pattern, fy, note in SCALARS:
        m = re.search(pattern, full)
        if not m:
            problems.append(f"MISS scalar {metric}")
            continue
        page = next((i for i, t in pages.items() if re.search(pattern, t)), None)
        facts.append(Fact(
            jurisdiction=JUR, fiscal_year=fy, metric=metric,
            value=float(m.group(1).replace(",", "")), unit=unit, basis=basis,
            source_doc=DOC, source_page=page,
            source_detail=f"stated in prose: …{m.group(0)[:70]}…",
            extraction=STATED if basis == "stated" else DIGITAL, note=note,
        ))

    # Civic participation details are text, not figures — keep them separate so they
    # never get charted, but publish them because they are the actionable part.
    participation = []
    for pat, label in (
        (r"starting with the public hearing and first\s*\n?\s*budget workshop on ([A-Z][a-z]+ \d+)",
         "First public hearing and budget workshop"),
        (r"during its ([A-Z][a-z]+ \d+) meeting, which included a public hearing",
         "Board meeting with public hearing on nonprofit funding"),
    ):
        m = re.search(pat, full)
        if m:
            participation.append({"event": label, "date_stated": m.group(1),
                                  "source_doc": DOC,
                                  "note": ("Date as printed in the FY2027 budget message. Confirm "
                                           "against the town's current meeting calendar before "
                                           "relying on it.")})
        else:
            problems.append(f"MISS participation detail: {label}")

    write_json(DATASETS / "facts_household.json", {
        "generated_by": "etl/s40_household_impact.py",
        "extraction_problems": problems,
        "civic_participation": participation,
        "facts": [f.as_row() for f in facts],
    })

    print(f"\n  facts: {len(facts)}  participation notes: {len(participation)}")
    for p in problems:
        print(f"      {p}")


if __name__ == "__main__":
    main()
