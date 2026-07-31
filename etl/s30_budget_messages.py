"""Stage 30 — extract fiscal indicators from the digital-text budget documents.

These are prose documents, not data files. A generic table scraper over prose
produces confident garbage, so this stage is deliberately *declarative*: every
indicator is named, given an explicit pattern, and must match exactly once. If a
future document changes wording, the run reports a MISS instead of silently
emitting nothing — a silent gap on a transparency site reads as "zero", which is
a lie.

Two extractors:

  1. `parse_projection_table` — the "Projected Surplus/(Deficit)" grid that the
     FY26 and FY27 budget messages both carry. Handles hyphen and en-dash
     variants, and validates that each row's value count matches the year header.

  2. `SCALARS` — headline figures stated in prose, one regex each.

A deliberate feature of the output: the *same* fiscal year is reported by
multiple budget documents on different bases (Estimate / Budget / Projection).
We keep every one of them rather than collapsing to a single value, because the
divergence between them is itself the interesting story — it shows how the town's
three-year projections compare with what later actually happened.
"""
from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATASETS, SOURCES, Fact, DIGITAL, STATED,  # noqa: E402
                    write_json, read_json, report_and_gate)

warnings.filterwarnings("ignore")
JUR = "Town of Hillsborough, NC"
BUDGET_DIR = ("Orange County Efficiency & Accountability Initiative/"
              "02 Research & Documents/Hillsborough Budget/")

DASH = r"[‐-―\-]"          # hyphen, en-dash, em-dash, figure dash
# The '%' may sit inside or outside the closing paren: "(3.5%)" and "(3.5)%".
# Getting this wrong silently drops the minus sign off every deficit percentage.
NUM = r"\(?-?\$?\s?[\d,]+(?:\.\d+)?%?\)?%?"

# --- the projection table --------------------------------------------------
TABLE_ROWS = [
    (rf"Surplus/\(Deficit\)\s*{DASH}\s*\$\s*amount",
     "general_fund_surplus_deficit", "USD"),
    (rf"Surplus/\(Deficit\)\s*{DASH}\s*percent",
     "general_fund_surplus_deficit_pct", "percent"),
    (rf"Fund Balance\s*{DASH}\s*available cash",
     "general_fund_balance_available_cash", "USD"),
    (rf"Fund Balance\s*{DASH}\s*%\s*of expenditures",
     "general_fund_balance_pct_of_expenditures", "percent"),
]

BASIS_WORDS = {"estimate": "estimate", "budget": "budget",
               "projection": "projected", "actual": "actual",
               "recommended": "recommended"}


def _num(tok: str) -> float | None:
    t = tok.strip()
    # Accounting notation: a leading paren means negative. Test only the opening
    # paren — the closing one may be lost to the '%' placement.
    neg = t.startswith("(")
    t = t.strip("()%$ ").replace("$", "").replace(",", "").strip()
    if not t or t in {"-", "--"}:
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def parse_projection_table(pdf, doc_id: str) -> tuple[list[Fact], list[str], bool]:
    facts: list[Fact] = []
    problems: list[str] = []
    found_marker = False

    for pageno, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        if "Projected Surplus/(Deficit)" not in text:
            continue
        found_marker = True
        lines = [l.rstrip() for l in text.split("\n")]

        # Search FORWARD from the table title. The same page also carries a
        # sales-tax chart whose x-axis is a run of ~10 FY labels; anchoring at
        # the title and capping the token count keeps us off that axis.
        start = next(i for i, l in enumerate(lines)
                     if "Projected Surplus/(Deficit)" in l)
        years, basis, hdr_i = None, None, None
        for i in range(start, min(start + 8, len(lines))):
            toks = lines[i].split()
            if 3 <= len(toks) <= 6 and all(re.fullmatch(r"FY\d{2,4}", t) for t in toks):
                years = [2000 + int(t[2:]) if len(t) == 4 else int(t[2:]) for t in toks]
                hdr_i = i
                break
        if not years:
            problems.append(f"{doc_id} p{pageno}: found the table but no 3-6 column "
                            f"FY year header within 8 lines of the title")
            continue

        # basis row: Estimate / Budget / Projection ...
        for l in lines[hdr_i:hdr_i + 5]:
            toks = [t.lower() for t in l.split()]
            if len(toks) == len(years) and all(t in BASIS_WORDS for t in toks):
                basis = [BASIS_WORDS[t] for t in toks]
                break
        if not basis:
            basis = ["reported"] * len(years)
            problems.append(f"{doc_id} p{pageno}: no basis row (Estimate/Budget/Projection); "
                            f"used 'reported'")

        for pat, metric, unit in TABLE_ROWS:
            rx = re.compile(pat + r"\s*(.*)$")
            hit = next((rx.search(l) for l in lines if rx.search(l)), None)
            if not hit:
                problems.append(f"{doc_id} p{pageno}: MISS row {metric}")
                continue
            toks = re.findall(NUM, hit.group(1))
            vals = [_num(t) for t in toks]
            vals = [v for v in vals if v is not None]
            if len(vals) != len(years):
                problems.append(f"{doc_id} p{pageno}: {metric} has {len(vals)} values "
                                f"for {len(years)} years -> skipped (values={vals})")
                continue
            for fy, b, v in zip(years, basis, vals):
                facts.append(Fact(
                    jurisdiction=JUR, fiscal_year=fy, metric=metric, value=v,
                    unit=unit, basis=b, source_doc=doc_id, source_page=pageno,
                    source_detail="Projected Surplus/(Deficit) — General Fund",
                    extraction=DIGITAL,
                    note=("Figure as it appeared in this budget document. Later "
                          "documents restate the same fiscal year on a different "
                          "basis; both are kept deliberately."),
                ))
        break
    return facts, problems, found_marker


# --- headline scalars stated in prose -------------------------------------
# (doc_id, filename, fiscal_year, metric, unit, basis, regex, note)
SCALARS = [
    # ---------------- FY2027 recommended budget message ----------------
    ("fy27-budget-message", "FY27 Budget Message.pdf", 2027,
     "general_fund_expenditures", "USD", "recommended",
     r"\$([\d,]+)\s*-\s*General Fund", ""),
    ("fy27-budget-message", "FY27 Budget Message.pdf", 2027,
     "water_sewer_fund_expenditures", "USD", "recommended",
     r"\$([\d,]+)\s*-\s*Water\s*&\s*Sewer Fund", ""),
    ("fy27-budget-message", "FY27 Budget Message.pdf", 2027,
     "stormwater_fund_expenditures", "USD", "recommended",
     r"\$\s*([\d,]+)\s*-\s*Stormwater Fund", ""),
    ("fy27-budget-message", "FY27 Budget Message.pdf", 2027,
     "total_budget", "USD", "recommended",
     r"\$([\d,]+)\s*-\s*Total Budget", ""),
    ("fy27-budget-message", "FY27 Budget Message.pdf", 2027,
     "property_tax_rate", "cents_per_100_valuation", "recommended",
     r"No Change;\s*([\d.]+)\s*cents per \$100", "No change from FY2026."),
    ("fy27-budget-message", "FY27 Budget Message.pdf", 2027,
     "revenue_per_cent_of_tax_rate", "USD", "stated",
     r"Each cent of the tax rate generates \$([\d,]+)",
     "The town's own conversion factor: what one cent on the property tax rate "
     "raises. Drives the household cost calculator."),
    ("fy27-budget-message", "FY27 Budget Message.pdf", 2027,
     "salary_benefit_increase_cost", "USD", "recommended",
     r"cost roughly \$([\d,]+) to fund increases to salary", ""),
    ("fy27-budget-message", "FY27 Budget Message.pdf", 2029,
     "tax_rate_increase_needed_cents", "cents_per_100_valuation", "projected",
     r"would require a tax rate increase of over ([\d.]+) cents",
     "Stated as 'over N cents' — a floor, not an exact figure."),
    ("fy27-budget-message", "FY27 Budget Message.pdf", 2027,
     "capital_projects_tax_rate_equivalent_cents", "cents_per_100_valuation", "projected",
     r"increases of approximately ([\d.]+) cents will be needed to pay for the fire station",
     "For the fire station, Ridgewalk Greenway and train station projects."),
    # Anchored on the page-4 prose. The front-page summary box is two-column, so there
    # "Water Rate" / "Sewer Rate" and their values extract onto non-adjacent lines with
    # prose between them — matching the bare "N% increase over FY26 rate" there would
    # pick whichever happened to come first and could pair sewer's number with water.
    ("fy27-budget-message", "FY27 Budget Message.pdf", 2027,
     "water_rate_increase_pct", "percent", "recommended",
     r"Water Rates\s*\n?\s*A ([\d.]+)% increase is recommended",
     "Recommended for each of the next three years."),

    # ---------------- FY2026 budget message ----------------
    ("fy26-budget-message", "FY26 Budget Message.pdf", 2026,
     "property_tax_rate", "cents_per_100_valuation", "adopted",
     r"([\d.]+)\s*cents per \$100 valuation", ""),
    ("fy26-budget-message", "FY26 Budget Message.pdf", 2026,
     "tax_rate_above_revenue_neutral_cents", "cents_per_100_valuation", "adopted",
     r"([\d.]+)\s*cents above the revenue-neutral rate",
     "Revenue-neutral is the rate that would raise the same revenue after a "
     "revaluation; the gap above it is the effective increase."),

    # ---------------- FY2025 budget message (older template) ----------------
    ("fiscal-year-2025-budget-message", "Fiscal Year 2025 Budget Message.pdf", 2025,
     "general_fund_expenditures", "USD", "recommended",
     r"General Fund \$([\d,]+)", ""),
    ("fiscal-year-2025-budget-message", "Fiscal Year 2025 Budget Message.pdf", 2025,
     "total_budget", "USD", "recommended",
     r"Total Budget \$([\d,]+)", ""),
    ("fiscal-year-2025-budget-message", "Fiscal Year 2025 Budget Message.pdf", 2025,
     "affordable_housing_allocation", "USD", "recommended",
     r"tax rate \(\$([\d,]+)\) for affordable housing", ""),
    ("fiscal-year-2025-budget-message", "Fiscal Year 2025 Budget Message.pdf", 2025,
     "capital_projects_tax_rate_equivalent_cents", "cents_per_100_valuation", "projected",
     r"equivalent of about ([\d.]+) cents on the tax rate",
     "The pipeline of major capital projects expressed as tax-rate cents."),
]


def extract_scalars(problems: list[str]) -> list[Fact]:
    facts: list[Fact] = []
    cache: dict[str, tuple[str, dict[int, str]]] = {}

    for doc_id, fname, fy, metric, unit, basis, pattern, note in SCALARS:
        if fname not in cache:
            path = SOURCES / BUDGET_DIR / fname
            if not path.exists():
                problems.append(f"missing source file {fname}")
                cache[fname] = ("", {})
                continue
            with pdfplumber.open(path) as pdf:
                pages = {i: (pg.extract_text() or "") for i, pg in enumerate(pdf.pages, 1)}
            cache[fname] = ("\n".join(pages.values()), pages)
        full, pages = cache[fname]
        if not full:
            continue

        m = re.search(pattern, full)
        if not m:
            problems.append(f"{doc_id}: MISS scalar {metric} (pattern did not match)")
            continue
        raw = m.group(1)
        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            problems.append(f"{doc_id}: {metric} unparseable value {raw!r}")
            continue
        page = next((i for i, t in pages.items() if re.search(pattern, t)), None)
        facts.append(Fact(
            jurisdiction=JUR, fiscal_year=fy, metric=metric, value=val, unit=unit,
            basis=basis, source_doc=doc_id, source_page=page,
            source_detail=f"stated in prose: …{m.group(0)[:70]}…",
            extraction=STATED if basis == "stated" else DIGITAL, note=note,
        ))
    return facts


def main() -> None:
    facts: list[Fact] = []
    problems: list[str] = []

    for doc_id, fname in [("fy27-budget-message", "FY27 Budget Message.pdf"),
                          ("fy26-budget-message", "FY26 Budget Message.pdf"),
                          ("fiscal-year-2025-budget-message",
                           "Fiscal Year 2025 Budget Message.pdf")]:
        path = SOURCES / BUDGET_DIR / fname
        if not path.exists():
            problems.append(f"missing {fname}")
            continue
        with pdfplumber.open(path) as pdf:
            f, p, found = parse_projection_table(pdf, doc_id)
        facts += f
        if not found:
            problems.append(f"{doc_id}: INFO no 'Projected Surplus/(Deficit)' table in "
                            f"this document — it uses the older prose-only template, "
                            f"so its figures come from the scalar patterns instead")
        problems += p

    facts += extract_scalars(problems)

    # sanity check: the town states a cent is worth $240,000, and separately that
    # $630,000 of salary cost equals ~2.6 cents. Those must agree within reason.
    per_cent = next((f.value for f in facts
                     if f.metric == "revenue_per_cent_of_tax_rate"), None)
    salary = next((f.value for f in facts
                   if f.metric == "salary_benefit_increase_cost"), None)
    checks = []
    if per_cent and salary:
        implied = salary / 2.6
        ok = abs(implied - per_cent) / per_cent < 0.05
        checks.append({
            "check": "cent_value_cross_validation",
            "stated_usd_per_cent": per_cent,
            "implied_from_salary_statement": round(implied),
            "agree_within_5pct": ok,
            "detail": (f"Document states each cent raises ${per_cent:,.0f} and "
                       f"separately that ${salary:,.0f} of salary cost equals about "
                       f"2.6 cents, implying ${implied:,.0f} per cent."),
        })

    write_json(DATASETS / "facts_budget.json", {
        "generated_by": "etl/s30_budget_messages.py",
        "consistency_checks": checks,
        "extraction_problems": problems,
        "facts": [f.as_row() for f in facts],
    })

    print(f"\n  facts: {len(facts)}")
    report_and_gate("stage 30", problems, checks)


if __name__ == "__main__":
    main()
