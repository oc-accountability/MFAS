"""Stage 92 — tax rate history, and an error in the county's own reports.

Amy's request:

    "the tax payer impact - the total cost of ownership, is composed of two tax
     rates, Hillsborough and Orange County (OC), plus water, sewer and stormwater.
     ... I want to summarize all of this for the total cost of ownership, and see
     this trend since 2018, thru 2029 if we can."

A rate history is the backbone of that, and the county ACFR's statistical section
prints exactly what is needed: Table 6, "Direct and Overlapping Property Tax Rates
— Last Ten Fiscal Years", carrying the county rate, the fire districts, the school
district and every municipality including Hillsborough, in one table.

**Table 6's county column is wrong by a factor of ten, in all five editions.**

For 2025 it prints the Orange County direct rate as $0.086290 — 8.6 cents per $100
— beside Hillsborough at 60.7 cents. A North Carolina county rate is normally the
largest single component, not a seventh of the town's, and the county's own
FY2026-27 budget message states 63.83 cents rising to 67.58.

The proof is inside the same document, one page earlier. **Table 5, "Net Total
Assessed Value", prints the same ten years' direct tax rate** — and for 2025 it
says 0.8629. Multiply Table 6's county row by ten and it equals Table 5's column
for all ten years, exactly. That is not an inference from plausibility; it is a
ten-for-ten identity between two tables in one report, repeated across editions.

So the county column of Table 6 is Table 5's column with a misplaced decimal, and
Table 6's own "Total direct rate" was computed from the shifted value, carrying the
error forward. The fire district and municipal columns are unaffected — a fire
district rate of 0.18 is ordinary, and 1.8 would not be.

This stage therefore:

  * takes county rates from **Table 5**, not Table 6, and says so;
  * reads both tables from **all five ACFR editions** and corroborates every cell
    across editions, since the ten-year windows overlap and a given year appears in
    up to five independently published reports;
  * publishes a cell only where the editions agree, and reports disagreement rather
    than picking a winner;
  * records the Table 5 / Table 6 contradiction as a finding, because a resident
    reading Table 6 would draw a badly wrong conclusion about who taxes them most.

The statistical section of an ACFR is explicitly unaudited, which is where an error
of this kind survives an audit.
"""
from __future__ import annotations

import glob
import re
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, SOURCES, read_json, write_json  # noqa: E402

warnings.filterwarnings("ignore")

T5_TITLE = "Net Total Assessed Value"
T6_TITLE = "Direct and Overlapping Property Tax Rates"

# Row order in Table 6, used to align the continuation page (2021–2016), which
# prints the numbers without repeating the labels.
T6_ROWS = [
    ("county_direct", "Orange County"),
    ("total_general_direct", "Total general direct rate"),
    ("fire_districts", "Fire Districts"),
    ("total_direct", "Total direct rate"),
    ("chcc_school", "Chapel Hill-Carrboro School District"),
    ("chapel_hill", "Chapel Hill"),
    ("carrboro", "Carrboro"),
    ("hillsborough", "Hillsborough"),
    ("mebane", "Mebane"),
]
# pdfplumber emits stray spaces inside these figures ("0 .086290"), so the pattern
# tolerates internal whitespace and it is stripped before parsing.
RATE = re.compile(r"\$?\s*(\d\s*\.\s*\d{2,6})")
MONEY = re.compile(r"([\d,]{7,})")


def _nums(line: str) -> list[float]:
    return [float(m.group(1).replace(" ", "")) for m in RATE.finditer(line)]


def read_table5(pdf, page_no: int) -> dict[int, dict]:
    """Assessed value and direct tax rate by fiscal year.

    The year column lives on the facing page — Table 5 is the right half of a
    two-page spread whose left half carries "Fiscal Year".
    """
    left = pdf.pages[page_no - 2].extract_text() or ""
    # Revaluation years carry a footnote marker — "2014 (1) $ 14,734,501,833" — which
    # an anchored year+value pattern silently skips, losing the whole edition.
    years = [int(m.group(1)) for m in re.finditer(
        r"^\s*(20\d{2})\s*(?:\(\d\)\s*)?\$?\s*[\d,]{7,}", left, re.M)]
    rows = []
    for line in (pdf.pages[page_no - 1].extract_text() or "").split("\n"):
        if not MONEY.search(line):
            continue
        vals = _nums(line)
        money = [float(m.group(1).replace(",", "")) for m in MONEY.finditer(line)]
        rate = next((v for v in vals if 0.0 < v < 3.0), None)
        if rate is None or len(money) < 2:
            continue
        rows.append({"assessed_value": money[0], "direct_tax_rate": rate})
    if len(years) != len(rows):
        return {}
    return {y: r for y, r in zip(years, rows)}


def read_table6(pdf, page_no: int, problems: list[str]) -> dict[str, dict[int, float]]:
    """Every entity's rate by fiscal year, across the table's two pages."""
    out: dict[str, dict[int, float]] = defaultdict(dict)
    for pno in (page_no, page_no + 1):
        if pno > len(pdf.pages):
            continue
        text = pdf.pages[pno - 1].extract_text() or ""
        if pno > page_no and T6_TITLE in text:
            continue                                    # the next table, not a continuation
        years = None
        numeric_rows = []
        for line in text.split("\n"):
            yrs = re.findall(r"\b(20[012]\d)\b", line)
            if years is None and len(yrs) >= 4 and not RATE.search(line):
                years = [int(y) for y in yrs]
                continue
            if years and _nums(line):
                numeric_rows.append((line, _nums(line)))
        if not years:
            continue
        # The continuation page prints the numbers without repeating the labels, so
        # rows can only be aligned by position — and position is only trustworthy if
        # the row count matches exactly. One edition's continuation page parses to a
        # different count, and aligning it by index anyway attributed a fire-district
        # figure to Hillsborough. Skip rather than guess; the cross-edition check
        # caught it, but it should not have needed to.
        labelled = [(l, v) for l, v in numeric_rows if re.search(r"[A-Za-z]", l)]
        if labelled:
            for line, vals in labelled:
                key = next((k for k, lab in T6_ROWS if line.strip().startswith(lab[:8])), None)
                if key:
                    for y, v in zip(years, vals[:len(years)]):
                        out[key][y] = v
        elif len(numeric_rows) == len(T6_ROWS):
            for (key, _), (_, vals) in zip(T6_ROWS, numeric_rows):
                for y, v in zip(years, vals[:len(years)]):
                    out[key][y] = v
        else:
            problems.append(f"p{pno}: {len(numeric_rows)} numeric rows, expected "
                            f"{len(T6_ROWS)} — cannot align by position, page skipped")
    return out


def main() -> None:
    problems: list[str] = []
    editions = []
    for f in sorted(glob.glob(str(SOURCES / "**" / "*ACFR*.pdf"), recursive=True)):
        name = Path(f).name
        if not name.startswith("Orange C"):
            continue                                    # town reports are read elsewhere
        with pdfplumber.open(f) as pdf:
            t5 = t6 = None
            for i, pg in enumerate(pdf.pages, 1):
                text = pg.extract_text() or ""
                if t5 is None and T5_TITLE in text and "Estimated Actual" in text:
                    t5 = i
                if t6 is None and T6_TITLE in text and "Last Ten" in text:
                    t6 = i
            editions.append({"file": name, "t5_page": t5, "t6_page": t6,
                             "table5": read_table5(pdf, t5) if t5 else {},
                             "table6": read_table6(pdf, t6, problems) if t6 else {}})

    # --- corroborate every cell across editions --------------------------------
    # The ten-year windows overlap, so most years are published two to five times.
    # A cell is publishable only where the editions that report it agree.
    def corroborate(get) -> tuple[dict, list]:
        seen: dict[int, dict[float, list[str]]] = defaultdict(lambda: defaultdict(list))
        for e in editions:
            for y, v in get(e).items():
                seen[y][round(v, 6)].append(e["file"])
        agreed, disputes = {}, []
        for y, vals in sorted(seen.items()):
            if len(vals) == 1:
                v, srcs = next(iter(vals.items()))
                agreed[y] = {"value": v, "editions": len(srcs), "sources": srcs}
            else:
                disputes.append({"fiscal_year": y,
                                 "values": {str(v): s for v, s in vals.items()}})
        return agreed, disputes

    county, county_disputes = corroborate(
        lambda e: {y: r["direct_tax_rate"] for y, r in e["table5"].items()})
    t6_county, _ = corroborate(lambda e: e["table6"].get("county_direct", {}))
    town, town_disputes = corroborate(lambda e: e["table6"].get("hillsborough", {}))
    fire, _ = corroborate(lambda e: e["table6"].get("fire_districts", {}))
    school, _ = corroborate(lambda e: e["table6"].get("chcc_school", {}))
    assessed, _ = corroborate(
        lambda e: {y: r["assessed_value"] for y, r in e["table5"].items()})

    # --- prove the factor-of-ten claim rather than asserting it ----------------
    ratio_test = []
    for y in sorted(set(county) & set(t6_county)):
        t5v, t6v = county[y]["value"], t6_county[y]["value"]
        ratio_test.append({"fiscal_year": y, "table5": t5v, "table6": t6v,
                           "ratio": round(t5v / t6v, 6) if t6v else None,
                           "exactly_ten": bool(t6v) and abs(t5v / t6v - 10.0) < 1e-6})
    proven = bool(ratio_test) and all(r["exactly_ten"] for r in ratio_test)

    # --- extend with the two forward years from the verified budget messages ---
    facts = read_json(DATASETS / "facts.json")["facts"]

    def fact(metric):
        """Every fact for a metric, not just one.

        The town publishes its rate for two fiscal years (FY2026 adopted, FY2027
        recommended) and so does the county. Taking a single row per metric dropped
        one year of each, and because the two governments' newest rows landed on
        different fiscal years the result silently merged FY2026's county rate with
        FY2027's town rate — a wrong number that looked entirely reasonable.
        """
        return [f for f in facts if f["metric"] == metric]

    forward: dict[int, dict] = {}
    for metric, field in (("property_tax_rate", "town_rate"),
                          ("county_property_tax_rate", "county_rate"),
                          ("county_property_tax_rate_prior", "county_rate")):
        for f in fact(metric):
            slot = forward.setdefault(f["fiscal_year"], {})
            rate = round(f["value"] / 100, 6)
            if field in slot and slot[field] != rate:
                problems.append(f"FY{f['fiscal_year']} {field}: two different published "
                                f"values ({slot[field]} and {rate}) — not resolved")
            slot[field] = rate
            slot.setdefault("basis", {})[field] = f.get("basis")

    county_prior = next((f for f in fact("county_property_tax_rate_prior")), None)

    # Does the corroborated history join up with the budget message? FY2025's 0.8629
    # falling to FY2026's 0.6383 is a revaluation year doing what revaluations do.
    join = None
    if county_prior and county:
        last = max(county)
        join = {"last_audited_year": last,
                "last_audited_rate": county[last]["value"],
                "next_year": county_prior["fiscal_year"],
                "next_year_rate": round(county_prior["value"] / 100, 6),
                "change_pct": round((county_prior["value"] / 100 / county[last]["value"] - 1)
                                    * 100, 1),
                "note": ("FY2026 was a revaluation year. A revaluation raises assessed values, "
                         "so a falling rate does not by itself mean a falling bill — which is "
                         "why the revenue-neutral rate matters more than the rate alone.")}

    # --- the combined series a resident actually pays --------------------------
    HOME = 400000.0
    series = []
    for y in sorted(set(county) | set(town) | set(forward)):
        c = county.get(y, {}).get("value") or forward.get(y, {}).get("county_rate")
        t = town.get(y, {}).get("value") or forward.get(y, {}).get("town_rate")
        row = {"fiscal_year": y, "county_rate": c, "town_rate": t,
               "school_district_rate": school.get(y, {}).get("value"),
               "fire_district_rate": fire.get(y, {}).get("value"),
               "assessed_value_countywide": assessed.get(y, {}).get("value"),
               "source": ("budget message" if y in forward and y not in county
                          else "ACFR statistical section"),
               "basis": forward.get(y, {}).get("basis"),
               "corroborating_editions": max(county.get(y, {}).get("editions", 0),
                                             town.get(y, {}).get("editions", 0))}
        if c and t:
            row["combined_rate"] = round(c + t, 6)
            row["rate_on_fixed_400k"] = round(HOME / 100 * (c + t), 2)
        elif c or t:
            row["incomplete"] = "only one of the two rates is available for this year"
        series.append(row)

    complete = [r for r in series if r.get("combined_rate")]
    util = {m: (fact(m)[-1]["value"] if fact(m) else None) for m in (
        "water_bill_increase_monthly_intown_avg", "sewer_bill_increase_monthly_intown_avg",
        "stormwater_fee_increase_per_eru")}

    write_json(DATASETS / "total_cost_of_ownership.json", {
        "generated_by": "etl/s92_total_cost.py",
        "requested_by": ("Amy — total cost of ownership: the Hillsborough and Orange County tax "
                         "rates plus water, sewer and stormwater, trended from 2018 through 2029."),
        "units": "dollars of tax per $100 of assessed value",
        "home_value_basis": HOME,
        "caveat_fixed_home_value": {
            "field": "rate_on_fixed_400k",
            "what_it_is": ("The combined rate applied to a constant $400,000 assessed value, so "
                           "the years can be compared on rate alone."),
            "what_it_is_NOT": ("A bill history. It is not what any real home paid over time, and "
                               "reading it as one inverts the story across a revaluation. In a "
                               "revaluation year the rate falls while assessed values rise, so a "
                               "fixed home value shows the bill dropping when an actual home's "
                               "bill may have risen. FY2026 is such a year: the county rate fell "
                               "26% and the town's 15%, but countywide assessed value was "
                               "reassessed at the same time."),
            "to_do_it_properly": ("A real bill history needs each year's assessed value for the "
                                  "same property, which is parcel-level data the archive does not "
                                  "contain. The revenue-neutral rate is the honest comparator and "
                                  "is reported separately where the governments state it."),
        },
        "method": ("County rates are taken from ACFR Table 5 (Net Total Assessed Value), NOT from "
                   "Table 6 (Direct and Overlapping Property Tax Rates), for the reason recorded "
                   "under source_error below. Municipal, fire district and school district rates "
                   "come from Table 6, whose other columns are unaffected. Every cell was read "
                   "from all five ACFR editions held and is published only where the editions "
                   "agree; the ten-year windows overlap, so most years are corroborated by two to "
                   "five independently published reports. FY2026 and FY2027 come from the town "
                   "and county budget messages."),
        "source_error": {
            "finding": ("Table 6's Orange County column is Table 5's direct tax rate with the "
                        "decimal point moved one place left, in every edition held. For FY2025 "
                        "Table 6 prints $0.086290 where Table 5 prints 0.8629."),
            "proof": ("Table 6's county value multiplied by ten equals Table 5's value for every "
                      "overlapping year, exactly. Verified below rather than asserted."),
            "verified_exactly_ten_for_all_years": proven,
            "ratio_test": ratio_test,
            "consequence": ("Table 6's own 'Total direct rate' row was computed from the shifted "
                            "value and is wrong by the same amount. A resident reading Table 6 "
                            "would conclude the county taxes them at a seventh of the town's rate, "
                            "when in fact the county rate is the larger of the two."),
            "not_corrected_silently": ("The shifted figures are reported here as found. Nothing is "
                                       "republished as a corrected version of Table 6; the "
                                       "unaffected Table 5 is used instead."),
            "unaffected": ("Fire district and municipal columns. A fire district weighted average "
                           "of 0.18 is ordinary for North Carolina; 1.8 would not be."),
            "where": "Table 5 and Table 6, statistical section (unaudited), Orange County ACFR.",
        },
        "summary": {
            "editions_read": [{"file": e["file"], "table5_page": e["t5_page"],
                               "table6_page": e["t6_page"],
                               "years_table5": len(e["table5"]),
                               "years_table6": len(e["table6"].get("hillsborough", {}))}
                              for e in editions],
            "years_covered": [min(r["fiscal_year"] for r in series),
                              max(r["fiscal_year"] for r in series)] if series else None,
            "years_with_both_rates": len(complete),
            "county_rate_disputes": county_disputes,
            "town_rate_disputes": town_disputes,
        },
        "series": series,
        "revaluation_join": join,
        "utility_increases_fy2027": util,
        "extraction_problems": problems,
        "gaps": [
            "Water and sewer BASE rates are not in the archive — only the FY2027 increases — so "
            "the utility half of the cost of ownership cannot be trended yet. The rate studies "
            "held are slide decks without the underlying schedules.",
            "The Orange County sales tax for schools is not located in the documents held. The "
            "manager's message discusses sales tax revenue but not a school-specific rate, so no "
            "figure is published for it.",
            "FY2028 and FY2029 do not exist as adopted rates. The town's capital plan states the "
            "tax rate its projects would require, which is a plan rather than a rate, and is "
            "reported separately as such.",
        ],
    })

    print(f"  read {len(editions)} county ACFR editions")
    for e in editions:
        print(f"      {e['file'][:40]:42} T5 p{e['t5_page']} ({len(e['table5'])}y)  "
              f"T6 p{e['t6_page']} ({len(e['table6'].get('hillsborough', {}))}y)")
    print(f"\n  Table 5 vs Table 6 county rate — factor of ten proven for all years: {proven}")
    for r in ratio_test[:4]:
        print(f"      FY{r['fiscal_year']}  Table 5 {r['table5']:.4f}  "
              f"Table 6 {r['table6']:.6f}  ratio {r['ratio']:.4f}")
    if county_disputes or town_disputes:
        print(f"  cross-edition disputes: county {len(county_disputes)}, town {len(town_disputes)}")
    print(f"\n  combined rate history ({len(complete)} years with both rates):")
    for r in series:
        if r.get("combined_rate"):
            print(f"      FY{r['fiscal_year']}  county {r['county_rate']:.4f} + town "
                  f"{r['town_rate']:.4f} = {r['combined_rate']:.4f}  "
                  f"-> ${r['rate_on_fixed_400k']:>8,.0f} at a fixed $400k   "
                  f"({r['corroborating_editions']} editions)")
    if join:
        print(f"\n  joins to the budget message: FY{join['last_audited_year']} "
              f"{join['last_audited_rate']:.4f} -> FY{join['next_year']} "
              f"{join['next_year_rate']:.4f} ({join['change_pct']:+.1f}%, revaluation year)")


if __name__ == "__main__":
    main()
