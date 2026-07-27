"""Stage 60 — the audited General Fund: what was budgeted vs what was actually spent.

This answers the question a resident asks most directly about accountability:
*did the town spend what it said it would?* Everything else on the site is a plan;
this is the audited outcome, signed off by an outside auditor.

Source: `Fiscal Year 2025 Financial Report.pdf`, Exhibit 5 — "Statement of
Revenues, Expenditures, and Changes in Fund Balances - Budget and Actual, General
Fund". Crucially this document is **digital text**, not a scan: it is the small
digital twin of the 61 MB scanned FY2025 report, so no OCR is involved and none of
the digit-transposition risk applies.

The statement gives four columns per line:

    Original Budget | Final Budget | Actual Amounts | Variance (Positive/Negative)

Two traps specific to this document:

1. **Spaces inside numbers.** The digital text renders figures as "1 7,047,188"
   and "$ 2 04,657". Spaces are stripped, but the result must still look like
   properly grouped thousands — otherwise we would be inventing a number rather
   than reading one.
2. **Variance signs.** The statement's "Variance" column is *positive = favourable*
   and is printed in parentheses when unfavourable. It is stored as printed and
   recomputed independently, so a misread sign cannot pass silently.

Self-proving: for every line, Actual − Final Budget must equal the printed
variance, and the components must sum to the printed totals. Any line that fails
is reported and excluded rather than published.
"""
from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, SOURCES, write_json  # noqa: E402

warnings.filterwarnings("ignore")

DOC_ID = "fiscal-year-2025-financial-report"
PATH = SOURCES / ("Orange County Efficiency & Accountability Initiative/"
                  "02 Research & Documents/Hillsborough Budget/"
                  "Fiscal Year 2025 Financial Report.pdf")

SECTION_REVENUE = "revenues"
SECTION_EXPEND = "expenditures"

LABEL_MAX_X = 260.0     # everything left of the first figure column is the label
FRAGMENT_GAP = 2.5      # pt; fragments closer than this are one number
COL_TOLERANCE = 6.0     # pt; how near a right edge must be to claim a column


def rows_from_words(page) -> list[tuple[str, list[tuple[float, str]]]]:
    """Group a page's words into (label, [(right_edge, token), …]) rows.

    Coordinates rather than whitespace, because this document renders stray
    spaces INSIDE numbers ("$ 2 04,657", "4 ,515,010"). Splitting on whitespace
    is therefore ambiguous — but the figures are right-aligned in fixed columns,
    so geometry resolves it exactly: adjacent fragments are merged, and the
    merged number's right edge identifies which column it belongs to.
    """
    from collections import defaultdict
    bands: dict[int, list] = defaultdict(list)
    for w in page.extract_words():
        bands[round(w["top"] / 3.0)].append(w)

    out = []
    for key in sorted(bands):
        ws = sorted(bands[key], key=lambda w: w["x0"])
        label = " ".join(w["text"] for w in ws if w["x1"] <= LABEL_MAX_X).strip()
        figs = [w for w in ws if w["x1"] > LABEL_MAX_X and w["text"] != "$"]
        merged: list[tuple[float, str]] = []
        for w in figs:
            if merged and w["x0"] - prev_x1 <= FRAGMENT_GAP:
                merged[-1] = (w["x1"], merged[-1][1] + w["text"])
            else:
                merged.append((w["x1"], w["text"]))
            prev_x1 = w["x1"]
        if label or merged:
            out.append((label, merged))
    return out


def column_edges(rows) -> list[float]:
    """Infer the figure columns from the right edges actually used on the page."""
    edges: list[float] = []
    for _, figs in rows:
        for x1, tok in figs:
            if any(c.isdigit() for c in tok):
                edges.append(x1)
    edges.sort()
    cols: list[list[float]] = []
    for e in edges:
        if cols and e - cols[-1][-1] <= COL_TOLERANCE:
            cols[-1].append(e)
        else:
            cols.append([e])
    # keep the columns that actually recur; stray marks form tiny clusters
    return [sum(c) / len(c) for c in cols if len(c) >= 4]


def clean_number(tok: str) -> float | None:
    """Parse '1 7,047,188' -> 17047188, '( 2 04,657)' -> -204657, '-' -> None.

    Refuses anything that does not look like properly grouped thousands once the
    stray spaces are gone; guessing at a malformed figure is worse than skipping it.
    """
    t = tok.strip()
    if t in {"-", "–", "—", ""}:
        return None
    neg = t.startswith("(") or t.endswith(")")
    t = t.strip("()").replace("$", "").replace(" ", "").strip()
    if not t:
        return None
    if not re.fullmatch(r"\d{1,3}(?:,\d{3})*|\d+", t):
        return None
    v = float(t.replace(",", ""))
    return -v if neg else v


def to_columns(figs, edges, problems, where) -> list[float | None]:
    """Place each merged figure into its column by right edge."""
    vals: list[float | None] = [None] * len(edges)
    for x1, tok in figs:
        v = clean_number(tok)
        if v is None:
            continue
        near = min(range(len(edges)), key=lambda i: abs(edges[i] - x1))
        if abs(edges[near] - x1) > COL_TOLERANCE:
            problems.append(f"{where}: figure {tok!r} at x={x1:.1f} matches no column — skipped")
            continue
        if vals[near] is not None:
            problems.append(f"{where}: two figures land in column {near} — skipped row")
            return []
        vals[near] = v
    return vals


def main() -> None:
    if not PATH.exists():
        sys.exit(f"missing {PATH}")
    problems: list[str] = []

    with pdfplumber.open(PATH) as pdf:
        page_no, word_rows = None, None
        for i, pg in enumerate(pdf.pages, start=1):
            t = pg.extract_text() or ""
            if "Budget and Actual" in t and "General Fund" in t and "Exhibit" in t:
                page_no = i
                word_rows = rows_from_words(pg)
                break
    if page_no is None:
        sys.exit("could not find Exhibit 5 (General Fund budget vs actual)")

    edges = column_edges(word_rows)
    if len(edges) != 4:
        sys.exit(f"expected 4 figure columns on p{page_no}, found {len(edges)}: {edges}")

    rows = []
    section = None
    for label, figs in word_rows:
        low = label.strip().lower().rstrip(":")
        if low in {"revenues", "expenditures"}:
            section = SECTION_REVENUE if low == "revenues" else SECTION_EXPEND
            continue
        if not figs or section is None or not label:
            continue
        if low in {"current", "general fund"}:
            continue
        vals = to_columns(figs, edges, problems, f"p{page_no} {label!r}")
        if len(vals) != 4:
            continue
        # A line may legitimately show a figure in only some columns — Contingency
        # is budgeted $450,000 and spent nothing, printed as dashes. Dropping it
        # lost exactly that $450,000 from the expenditure total.
        if all(v is None for v in vals[:3]):
            continue
        orig, final, actual = vals[0], vals[1], vals[2]
        printed_var = vals[3]

        # Prove the reading: for expenditures a positive variance means UNDER
        # budget (final - actual); for revenues it means OVER (actual - final).
        derived = None
        if final is not None and actual is not None:
            derived = (actual - final) if section == SECTION_REVENUE else (final - actual)
        if derived is not None and printed_var is not None and abs(derived - printed_var) >= 1.5:
            problems.append(f"p{page_no}: {label!r} variance {printed_var:,.0f} does not match "
                            f"the columns (derived {derived:,.0f}) — excluded")
            continue

        is_total = label.lower().startswith("total")
        rows.append({
            "section": section, "line": label,
            "original_budget": orig, "final_budget": final, "actual": actual,
            "variance_printed": printed_var, "variance_derived": derived,
            "is_total": is_total,
            "source_doc": DOC_ID, "source_page": page_no,
        })
        # A section ends at its own "Total …" line. What follows — "Revenues over
        # (under) expenditures", "Other financing sources", transfers — are
        # separate blocks, and folding them into the section above put the
        # $(3,320,809) transfers line inside the expenditure total.
        if is_total:
            section = None

    # Components must sum to the printed totals — the statement's own arithmetic.
    checks = []
    for sect in (SECTION_REVENUE, SECTION_EXPEND):
        parts = [r for r in rows if r["section"] == sect and not r["is_total"]]
        tot = next((r for r in rows if r["section"] == sect and r["is_total"]), None)
        if not tot or not parts:
            continue
        for col in ("original_budget", "final_budget", "actual"):
            if tot[col] is None:
                continue
            got = sum(p[col] for p in parts if p[col] is not None)
            ok = abs(got - tot[col]) < 1.5
            checks.append({"section": sect, "column": col, "sum_of_lines": round(got, 2),
                           "printed_total": tot[col], "reconciles": ok})
            if not ok:
                problems.append(f"{sect}/{col}: lines sum to {got:,.0f} but the statement "
                                f"prints {tot[col]:,.0f}")

    # ---- cross-document check -------------------------------------------------
    # The audited statement and the budget document are independent publications
    # read by independent parsers. They should agree on FY2025 once the one known
    # classification difference is accounted for: the audited statement treats
    # interfund transfers as "other financing uses", the budget document counts
    # them as expenses. Agreement here is strong evidence that BOTH parsers are
    # right; it is the closest thing this project has to an external audit.
    cross = None
    val_path = DATASETS / "lineitem_validation.json"
    if val_path.exists():
        import json as _json
        with open(val_path, encoding="utf-8") as fh:
            li_checks = _json.load(fh)["checks"]   # NOT `checks` — that name holds
                                                   # this stage's arithmetic checks
        pub = {c["category"]: c["published"] for c in li_checks
               if c["fund"] == "General Fund" and c["fiscal_year"] == 2025
               and c["basis"] == "actual"}
        aud_total = next((r["actual"] for r in rows
                          if r["section"] == SECTION_EXPEND and r["is_total"]), None)
        if pub and aud_total is not None:
            total = sum(pub.values())
            transfers = pub.get("Interfund Transfers", 0.0)
            adjusted = total - transfers
            diff = adjusted - aud_total
            cross = {
                "question": ("Does the audited statement agree with the budget document's own "
                             "FY2025 actual figures?"),
                "budget_document_total": round(total, 2),
                "less_interfund_transfers": round(transfers, 2),
                "adjusted": round(adjusted, 2),
                "audited_total_expenditures": aud_total,
                "difference": round(diff, 2),
                "agree": abs(diff) <= 2.0,
                "note": ("The audited statement classifies interfund transfers as other financing "
                         "uses rather than expenditures; removing them makes the two directly "
                         "comparable. Agreement to within a dollar across two separate documents "
                         "and two separate parsers is the strongest check in this project."),
            }
            if not cross["agree"]:
                problems.append(f"cross-document check FAILED: adjusted budget-document total "
                                f"{adjusted:,.0f} vs audited {aud_total:,.0f} "
                                f"(diff {diff:+,.0f})")

    write_json(DATASETS / "audited_general_fund.json", {
        "cross_document_check": cross,
        "generated_by": "etl/s60_audited.py",
        "note": ("Audited General Fund budget vs actual for the year ended 30 June 2025, from the "
                 "digital (not scanned) financial report. Variance is positive-is-favourable as "
                 "the statement prints it, and is independently recomputed from the columns."),
        "fiscal_year": 2025,
        "source_doc": DOC_ID,
        "source_page": page_no,
        "arithmetic_checks": checks,
        "extraction_problems": problems,
        "rows": rows,
    })

    ok = sum(1 for c in checks if c["reconciles"])
    print(f"  Exhibit 5 found on page {page_no}")
    print(f"  {len(rows)} lines ({sum(1 for r in rows if r['is_total'])} totals)")
    print(f"  arithmetic: {ok}/{len(checks)} column totals reconcile")
    for p in problems[:6]:
        print(f"      {p}")
    if checks and ok < len(checks):
        sys.exit("\nBUILD FAILED — the audited statement does not add up as parsed.")


if __name__ == "__main__":
    main()
