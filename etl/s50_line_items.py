"""Stage 50 — the account-level spending detail.

This is the largest dataset in the project and the one that lets a resident ask
"where does my money actually go" and get a real answer instead of three fund
totals.

Where it comes from: the budget plan documents carry a "Line-Item Budget"
appendix listing every department's accounts — SALARIES, RETIREMENT, UTILITIES,
MAINTENANCE - INFRASTRUCTURE, GASOLINE — across five columns:

    FY25 Actual | FY26 Estimate | FY27 Budget | FY28 Projection | FY29 Projection

So each row yields up to five observations on different bases, including a real
*actual*. All of it is digital text, so no OCR risk applies here.

Layout, as observed (see docs/EXTRACTION_NOTES.md):

    Line-Item Budget: <Fund>          running header; gives the fund
    <Department>                      printed TWICE, consecutively
    <Department>
    FY25 Actual FY26 Estimate ...     column header; repeats per department
    Expenses                          top-level block
    Personnel                         category (Title Case)
      SALARIES  $v $v $v $v $v        account row (UPPER CASE)
      PERSONNEL TOTAL ...             subtotal — validation only, never summed
    Operating
      ...
    Debt Service $v $v ...            a Title-Case row that IS data, not a header
    EXPENSES TOTAL ...                department total

Traps this guards against, each one found the hard way:

1. **Departments appear twice in the document** — once in the narrative section
   with a category-level summary, once in this appendix with full account detail.
   Only the appendix is parsed. Double-counting would inflate every total.
2. **The running header prints on a minority of appendix pages** (7 of 28 in the
   FY27 document). Filtering pages on it drops ~80% of the data while looking
   like it worked, so it is used to find where the appendix *starts*, not to
   filter.
3. **State runs across page breaks.** A department's accounts routinely continue
   onto a page that repeats neither the fund header nor the department name.
4. **Some lines render with every character doubled** ("FFYY22002277
   OOppeerraattiinngg"). Harmless in a title we discard, corrupting in an account
   name, so a doubled-looking account label is a hard error, never a guess.
5. **Subtotal rows look like account rows.** Anything ending in TOTAL is held
   aside and used to check the document's own arithmetic.
6. **A blank in the source is an en-dash, not a zero.** Publishing it as 0 would
   assert the town spent nothing, so blanks are omitted.
"""
from __future__ import annotations

import json
import re
import sys
import warnings
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATASETS, SOURCES, content_cache_dir,  # noqa: E402
                    read_json, write_json)

warnings.filterwarnings("ignore")

BUDGET_DIR = ("Orange County Efficiency & Accountability Initiative/"
              "02 Research & Documents/Hillsborough Budget/")

# Only the FY27 plan carries a "Line-Item Budget" appendix. The FY26 adopted,
# FY26 recommended and FY25 manager's plans were each checked and contain none —
# they stop at category-level department summaries. Keeping them in the loop cost
# several minutes per run extracting ~800 pages to rediscover that, so they are
# listed here as checked-and-excluded rather than silently forgotten.
DOCS = [
    ("fy27-budget-and-financial-plan-recommended", "FY27 Budget and Financial Plan Recommended.pdf"),
]
NO_APPENDIX = [
    "FY26 Budget and Financial Plan Adopted.pdf",
    "FY26 Recommended Budget and Financial Plan.pdf",
    "Fiscal Year 2025 Managers Recommended Budget and Financial Work Plan.pdf",
]

MONEY = r"(?:\(\$[\d,]+\)|\$\(?[\d,]+\)?|–|—)"
MONEY_RUN = re.compile(rf"^(.*?)\s*((?:{MONEY}\s*){{2,}})$")
COLHDR = re.compile(r"FY(\d\d)\s+(Actual|Estimate|Budget|Projection|Adopted|Recommended)")
FUNDHDR = re.compile(r"Line-Item Budget:\s*(.+?)\s*$")

BASIS = {"actual": "actual", "estimate": "estimate", "budget": "budget",
         "projection": "projected", "adopted": "adopted", "recommended": "recommended"}

CATEGORIES = {"Personnel", "Operating", "Capital", "Interfund Transfers",
              "Cost Allocations", "Other Financing Sources", "Revenues", "Expenses",
              "Expenditures", "Transfers", "Debt Service"}
BLOCKS = {"Expenses", "Expenditures", "Revenues"}

FUND_CANON = {
    "general fund": "General Fund",
    "water & sewer fund": "Water & Sewer Fund",
    "water and sewer fund": "Water & Sewer Fund",
    "stormwater fund": "Stormwater Fund",
}

# Lines that are section furniture, never a department name.
NOT_A_DEPT = re.compile(r"Schedule|Summary|Budget:|Line-Item|Fiscal Year|^Town of|^\d")


def looks_doubled(s: str) -> bool:
    """True if a label looks like every character was printed twice (trap 4).

    Requires most pairs to match so ordinary words with a doubled letter
    ("SUPPLIES", "TOTAL") are not misread.
    """
    letters = [c for c in s if c.isalnum()]
    if len(letters) < 8:
        return False
    pairs = sum(1 for i in range(0, len(letters) - 1, 2) if letters[i] == letters[i + 1])
    return pairs >= len(letters) // 2 - 1


def parse_money(tok: str) -> float | None:
    if tok in {"–", "—"}:
        return None            # the document's own blank, not a zero (trap 6)
    neg = tok.startswith("(") or tok.endswith(")")
    digits = re.sub(r"[^\d.]", "", tok)
    if not digits:
        return None
    v = float(digits)
    return -v if neg else v


def money_list(run: str) -> list[float | None]:
    return [parse_money(t) for t in re.findall(MONEY, run)]


def canon_fund(raw: str) -> str | None:
    s = re.sub(r"\s*-\s*$", "", raw).strip()
    s = re.sub(r"\s+", " ", s).lower()
    for k, v in FUND_CANON.items():
        if s.startswith(k):
            return v
    return None


def _drop_pending(pending, problems, doc_id, pageno, boundary):
    """Discard a label fragment that never received values, and say so.

    PDF extraction sometimes emits a wrapped table cell as
    label-part-1 / values / label-part-2, leaving a fragment behind. If that
    fragment survives to the next values-only line it attaches to the WRONG row —
    which is how $300,000 of interfund transfers got recorded as Capital. The
    value was right and the category was wrong, so nothing looked broken.
    """
    if pending is not None:
        problems.append(f"{doc_id} p{pageno}: label fragment {pending[:44]!r} discarded at "
                        f"{boundary} — it never received values")
    return None


def _appendix_range(pages: list[str]) -> tuple[int, int] | None:
    """Locate the appendix as a page range (see trap 2)."""
    starts = [i for i, t in enumerate(pages) if "Line-Item Budget:" in t]
    if not starts:
        return None
    start = min(starts)
    ends = [i for i, t in enumerate(pages) if i >= start and len(COLHDR.findall(t)) >= 2]
    return (start, max(ends)) if ends else None


def page_texts(doc_id: str, path: Path, sha256: str) -> list[str]:
    """Extract every page's text, cached on disk under a CONTENT-keyed namespace.

    Extraction dominates this stage's runtime, and the cache makes iterating on
    the parser cheap. It used to be keyed on size and mtime, which is very nearly
    right and fails in the one case that matters: a corrected re-issue of the same
    report, restored from a backup or re-downloaded, can carry the same byte length
    while the mtime is whatever the copy gave it. Then the manifest records the new
    hash and this cache serves the old text — the fact still cites a document, but
    not the one the number came from. Keyed on the full source hash it cannot happen.
    """
    cache = content_cache_dir("textcache", sha256, extractor="pdfplumber",
                              version="1") / "pages.json"
    if cache.exists():
        with open(cache, encoding="utf-8") as fh:
            return json.load(fh)
    with pdfplumber.open(path) as pdf:
        pages = [(pg.extract_text() or "") for pg in pdf.pages]
    cache.parent.mkdir(parents=True, exist_ok=True)
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(pages, fh)
    return pages


def parse_doc(doc_id: str, path: Path, problems: list[str],
              sha256: str) -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    totals: list[dict] = []
    pages = page_texts(doc_id, path, sha256)

    rng = _appendix_range(pages)
    if rng is None:
        problems.append(f"{doc_id}: INFO no 'Line-Item Budget' appendix in this document")
        return rows, totals
    first, last = rng

    # Persistent across pages — trap 3.
    fund = None
    cols: list[tuple[int, str]] = []
    dept = None
    category = None
    block = None
    pending = None      # an UPPER-CASE label whose values arrive on a later line

    for idx in range(first, last + 1):
        pageno = idx + 1
        for raw in [l.strip() for l in pages[idx].split("\n") if l.strip()]:
            fh = FUNDHDR.search(raw)
            if fh:
                f = canon_fund(fh.group(1))
                if f:
                    fund = f
                continue
            if re.fullmatch(r"\d{1,4}", raw):
                continue                                  # page-number footer
            if "Operating & Capital Budget" in raw or looks_doubled(raw):
                continue                                  # running title

            # The page-number footer is appended to the END of a line, e.g.
            #   "SALARIES - COMMISSIONERS $36,110 ... $41,000 249"
            #   "Debt Service 259"
            # That breaks the end-of-line anchor on the money run and silently
            # dropped whole rows, and invented a "Debt Service 259" department.
            # Only strip it from lines that carry money (so a label legitimately
            # ending in a number, like "TRANSFER TO FUND 69", keeps its digits);
            # for header matching use a footer-stripped view of the line.
            if re.search(MONEY, raw):
                raw = re.sub(r"\s+\d{1,4}$", "", raw)
            bare = re.sub(r"\s+\d{1,4}$", "", raw).strip()

            found = COLHDR.findall(raw)
            if len(found) >= 2:
                # A running table header that repeats on continuation pages — it
                # is NOT a section boundary, so the current category survives it.
                cols = [(2000 + int(y), BASIS[b.lower()]) for y, b in found]
                pending = _drop_pending(pending, problems, doc_id, pageno, "column header")
                continue

            if bare in BLOCKS:
                block, category = bare, None
                pending = _drop_pending(pending, problems, doc_id, pageno, "block header")
                continue

            m = MONEY_RUN.match(raw)

            # A bare category header, carrying no values.
            if bare in CATEGORIES and not m:
                category = bare
                pending = _drop_pending(pending, problems, doc_id, pageno, "category header")
                continue

            if not m:
                # Any line with money that failed to parse is a silent data loss
                # — the exact failure that hid the footer bug. Never stay quiet.
                if len(re.findall(MONEY, raw)) >= 2:
                    problems.append(f"{doc_id} p{pageno}: money line did not parse: {raw[:70]!r}")
                    continue
                if pending is not None:
                    pending = (pending + " " + raw).strip()   # wrapped label
                    continue
                if raw.isupper():
                    pending = raw
                elif not NOT_A_DEPT.search(bare) and bare != dept:
                    dept = bare
                    category = None
                    pending = _drop_pending(pending, problems, doc_id, pageno, "new department")
                continue

            label, run = m.group(1).strip(), m.group(2)
            vals = money_list(run)

            if not label:
                if pending is None:
                    problems.append(f"{doc_id} p{pageno}: values with no label: {run[:40]}")
                    continue
                label, pending = pending, None
            else:
                pending = None

            if looks_doubled(label):
                problems.append(f"{doc_id} p{pageno}: doubled-looking label {label!r} — "
                                f"refusing to guess the real name")
                continue
            if not cols:
                problems.append(f"{doc_id} p{pageno}: {label!r} before any column header")
                continue
            if len(vals) != len(cols):
                problems.append(f"{doc_id} p{pageno}: {label!r} has {len(vals)} values for "
                                f"{len(cols)} columns — skipped rather than mis-aligned")
                continue
            if dept is None or fund is None:
                problems.append(f"{doc_id} p{pageno}: {label!r} with no "
                                f"{'department' if dept is None else 'fund'} in scope")
                continue

            # "Debt Service" with no values is a header; WITH values it is a data
            # row belonging to that category rather than inheriting the category
            # printed above it. This must test the extracted LABEL — testing the
            # whole line never matches ("Debt Service $80,277 …"), which is what
            # left $366,781 of debt service sitting inside Operating with both
            # subtotals still looking plausible.
            if label in CATEGORIES:
                category = label

            rec = {
                "fund": fund, "department": dept,
                "category": category or block or "",
                "account": re.sub(r"\s+", " ", label),
                "values": vals, "page": pageno,
                # per-department, so carried on the row rather than assumed doc-wide
                "_cols": list(cols),
            }
            (totals if label.upper().endswith("TOTAL") else rows).append(rec)

    return rows, totals


# re.M matters: this is searched against whole-page text, and without MULTILINE
# the `$` only matches the end of the page, so the header is never found.
# re.M matters: this is searched against whole-page text, and without MULTILINE
# the `$` only matches the end of the page, so the header is never found.
SUMMARY_HDR = re.compile(r"Financial Summary:\s*(.+?)\s*$", re.M)

ROUNDING_TOLERANCE = 10.0  # dollars; the source's own summary tables round. Tiny
                           # against millions, so nothing real can hide under it.

# Variances between the account-level appendix and the fund summary that are
# characteristics of the source document, not of this parser. Each is stated with
# its cause; anything NOT listed here fails the build.
_DISASTER = ("The Disaster - General Fund unit is budgeted $10,000 of Operating at CATEGORY level "
             "on its department page with no account-level line, so the account-level appendix "
             "correctly shows $0 for it. The appendix is internally consistent — the money exists "
             "only above account grain and cannot appear in an account listing.")
KNOWN_VARIANCES = {
    ("General Fund", "Operating", 2027, "budget"): {"amount": -10000.0, "why": _DISASTER},
    ("General Fund", "Operating", 2028, "projected"): {"amount": -10000.0, "why": _DISASTER},
    ("General Fund", "Operating", 2029, "projected"): {"amount": -10000.0, "why": _DISASTER},
}

# Variances that are real, disclosed, and NOT yet explained. The build tolerates
# them because they are enumerated here with their measured size, but the data
# marks these slices unverified so the website may not present them as
# reconciled. Anything not in this list or KNOWN_VARIANCES fails the build.
#
# Every one of these sits in a prior-year actual/estimate column, never in the
# FY2027 budget the site leads with — that column reconciles completely.
UNRECONCILED = {
    ("General Fund", "Interfund Transfers", 2025, "actual"): (
        -29000.0, "Cause not established. Do not present FY2025 interfund transfers as complete."),
    ("General Fund", "Operating", 2025, "actual"): (
        -8228.0, "Cause not established; likely amounts recorded above account grain, as with "
                 "the Disaster unit."),
    ("General Fund", "Capital", 2026, "estimate"): (
        -823328.0, "The Disaster unit alone carries $2,131,931 of FY2026 estimated Capital at "
                   "category level with no account lines, which more than covers this gap; the "
                   "exact composition has not been traced."),
    ("General Fund", "Operating", 2026, "estimate"): (
        105668.0, "Positive variance — the accounts exceed the published category total. Cause "
                  "not established, so FY2026 estimates must not be presented as reconciled."),
    ("Water & Sewer Fund", "Interfund Transfers", 2029, "projected"): (
        -10000.0, "Cause not established. Matches the Disaster pattern in size but has not been "
                  "traced to a specific unit, so it is not claimed as explained."),
}


def parse_fund_summaries(pages: list[str], problems: list[str]) -> dict:
    """Read the town's own 'Expenditures by Type' tables off the Financial Summary
    pages. These are what the account detail must add up to, and parsing them
    (rather than hardcoding figures) means the check keeps working when a new
    budget year is added."""
    out: dict[tuple, float] = {}
    fund = None
    for idx, text in enumerate(pages):
        sh = SUMMARY_HDR.search(text)
        if not sh:
            continue
        f = canon_fund(sh.group(1))
        if not f:
            continue
        fund = f
        cols: list[tuple[int, str]] = []
        in_expend = False
        for raw in [l.strip() for l in text.split("\n") if l.strip()]:
            if re.search(MONEY, raw):
                raw = re.sub(r"\s+\d{1,4}$", "", raw)
            found = COLHDR.findall(raw)
            if len(found) >= 2:
                cols = [(2000 + int(y), BASIS[b.lower()]) for y, b in found]
                continue
            if re.search(r"Expenditures? by Type", raw):
                in_expend = True
                continue
            # "Revenues by Type" — the plural matters. Matching only the singular
            # let revenue rows leak in as fake expenditure categories such as
            # "Water (FY27 - FY29 - 7.5% projected rate increase per year)".
            if re.search(r"Revenues? by Type", raw):
                in_expend = False
                continue
            if not in_expend or not cols:
                continue
            m = MONEY_RUN.match(raw)
            if not m:
                continue
            label = m.group(1).strip()
            if not label or label.upper().endswith("TOTAL"):
                continue
            # Don't trust section position alone. The Water & Sewer summary page
            # lays its tables out differently, which let revenue rows like
            # "Water (FY27 - FY29 - 7.5% projected rate increase per year)" through
            # as expenditure categories. An expenditure category must be one of the
            # categories the line items themselves use — anything else is flagged,
            # never silently accepted or silently dropped.
            if label not in CATEGORIES:
                problems.append(f"summary p{idx+1}: ignoring {label!r} in the {fund} "
                                f"expenditure table — not a known expenditure category")
                continue
            vals = money_list(m.group(2))
            if len(vals) != len(cols):
                problems.append(f"summary p{idx+1}: {label!r} {len(vals)} values / {len(cols)} cols")
                continue
            for (fy, basis), v in zip(cols, vals):
                if v is not None:
                    out[(fund, label, fy, basis)] = v
    return out


def reconcile(rows: list[dict], published: dict, problems: list[str]) -> dict:
    """Compare parsed account detail to the town's published category totals."""
    import collections
    got = collections.defaultdict(float)
    for r in rows:
        for (fy, basis), v in zip(r["_cols"], r["values"]):
            if v is not None:
                got[(r["fund"], r["category"], fy, basis)] += v

    checks, unexplained = [], []
    for key in sorted(published, key=lambda k: (k[0], k[2], k[3], k[1])):
        fund, cat, fy, basis = key
        exp = published[key]
        act = got.get(key, 0.0)
        diff = act - exp
        known = KNOWN_VARIANCES.get(key)
        # The town's own summary tables are rounded to whole dollars while the
        # account rows are too, so a few dollars across ~700 rows is the source's
        # rounding, not a parse error. Kept tight so nothing real hides under it.
        ok = abs(diff) <= ROUNDING_TOLERANCE
        if not ok and known and abs(diff - known["amount"]) <= ROUNDING_TOLERANCE:
            ok = True
        disclosed = UNRECONCILED.get(key)
        rec = {"fund": fund, "category": cat, "fiscal_year": fy, "basis": basis,
               "published": exp, "parsed_from_accounts": round(act, 2),
               "difference": round(diff, 2), "reconciles": ok}
        if ok:
            rec["status"] = "known source variance" if known else "reconciles"
            if known:
                rec["explanation"] = known["why"]
        elif disclosed and abs(diff - disclosed[0]) <= max(ROUNDING_TOLERANCE, abs(disclosed[0]) * 0.001):
            # Disclosed but unexplained: allowed through, marked unverified. If the
            # size drifts from what was measured, it stops matching and fails.
            rec["status"] = "disclosed, unexplained — slice is NOT verified"
            rec["explanation"] = disclosed[1]
            rec["verified"] = False
        else:
            rec["status"] = "UNEXPLAINED"
            unexplained.append(rec)
        rec.setdefault("verified", ok)
        checks.append(rec)

    for u in unexplained:
        problems.append(f"RECONCILIATION FAILED {u['fund']} / {u['category']} "
                        f"FY{u['fiscal_year']} {u['basis']}: accounts total "
                        f"{u['parsed_from_accounts']:,.0f} vs published {u['published']:,.0f} "
                        f"(diff {u['difference']:+,.0f})")
    # Which (fund, year, basis) slices may the site present as reconciled? Only
    # those where every category in the slice verified.
    slices: dict[tuple, bool] = {}
    for c in checks:
        k = (c["fund"], c["fiscal_year"], c["basis"])
        slices[k] = slices.get(k, True) and c.get("verified", False)

    return {"checks": checks,
            "verified_slices": [{"fund": f, "fiscal_year": y, "basis": b, "verified": v}
                                for (f, y, b), v in sorted(slices.items(),
                                                           key=lambda x: (x[0][1], x[0][0]))],
            "summary": {"total": len(checks),
                        "reconciled": sum(1 for c in checks if c["reconciles"]),
                        "disclosed_unexplained": sum(1 for c in checks
                                                     if c.get("verified") is False),
                        "unexplained": len(unexplained),
                        "verified_slices": sum(1 for v in slices.values() if v),
                        "total_slices": len(slices)}}


def main() -> None:
    problems: list[str] = []
    all_rows: list[dict] = []
    all_totals: list[dict] = []
    per_doc = {}

    sha_by_id = {d["id"]: d["sha256"]
                 for d in read_json(DATASETS / "documents.json")["documents"]}
    for doc_id, fname in DOCS:
        path = SOURCES / BUDGET_DIR / fname
        if not path.exists():
            problems.append(f"missing {fname}")
            continue
        sha = sha_by_id.get(doc_id)
        if not sha:
            problems.append(f"{doc_id}: not in the document manifest — cannot cache safely")
            continue
        rows, totals = parse_doc(doc_id, path, problems, sha)
        for r in rows + totals:
            r["source_doc"] = doc_id
        all_rows += rows
        all_totals += totals
        per_doc[doc_id] = {
            "accounts": len(rows), "totals": len(totals),
            "departments": len({r["department"] for r in rows}),
        }
        print(f"  {fname[:50]:52} {len(rows):5} accounts  {len(totals):4} totals  "
              f"{len({r['department'] for r in rows}):3} depts")

    # Columnar, not a list of objects: thousands of rows of repeated keys would
    # multiply the download for a page phones have to load.
    COLUMNS = ["fund", "department", "category", "account",
               "fiscal_year", "basis", "value", "source_doc", "page"]
    table = [[r["fund"], r["department"], r["category"], r["account"], fy, basis, v,
              r["source_doc"], r["page"]]
             for r in all_rows
             for (fy, basis), v in zip(r["_cols"], r["values"]) if v is not None]

    write_json(DATASETS / "lineitems.json", {
        "generated_by": "etl/s50_line_items.py",
        "note": ("Account-level detail from the budget plans' Line-Item Budget appendix. "
                 "All from digital text, no OCR. A blank in the source is omitted rather "
                 "than published as zero."),
        "per_document": per_doc,
        "extraction_problem_count": len(problems),
        "extraction_problems": problems[:200],
        "columns": COLUMNS,
        "rows": table,
    })

    write_json(DATASETS / "lineitem_totals.json", {
        "generated_by": "etl/s50_line_items.py",
        "note": ("Subtotal/total rows as printed. Never summed into the account data — kept so "
                 "the parse can be checked against the document's own arithmetic."),
        "columns": ["fund", "department", "account", "fiscal_year", "basis", "value",
                    "source_doc", "page"],
        "rows": [[t["fund"], t["department"], t["account"], fy, basis, v, t["source_doc"], t["page"]]
                 for t in all_totals
                 for (fy, basis), v in zip(t["_cols"], t["values"]) if v is not None],
    })

    # ---- reconcile against the town's own published category totals ----------
    published = {}
    for doc_id, fname in DOCS:
        path = SOURCES / BUDGET_DIR / fname
        if path.exists():
            published.update(parse_fund_summaries(
                page_texts(doc_id, path, sha_by_id[doc_id]), problems))
    val = reconcile(all_rows, published, problems)
    write_json(DATASETS / "lineitem_validation.json", {
        "generated_by": "etl/s50_line_items.py",
        "note": ("Every published fund/category total the documents state, against the sum of the "
                 "account-level rows parsed for it. This is the proof the parse is correct: the "
                 "detail has to add up to the town's own summary."),
        "checked_documents_without_appendix": NO_APPENDIX,
        **val,
    })

    print(f"\n  {len(table):,} published observations from {len(all_rows):,} account rows")
    s = val["summary"]
    print(f"  reconciliation: {s['reconciled']}/{s['total']} published category totals agree"
          + (f"  — {s['unexplained']} UNEXPLAINED" if s["unexplained"] else ""))
    if problems:
        print(f"  {len(problems)} problem(s); first few:")
        for p in problems[:8]:
            print(f"      {p}")
    if s["unexplained"]:
        sys.exit("\nBUILD FAILED — account detail does not reconcile to the published totals. "
                 "Fix the parse or document the variance in KNOWN_VARIANCES; never ship a "
                 "spending breakdown that contradicts the town's own summary.")


if __name__ == "__main__":
    main()
