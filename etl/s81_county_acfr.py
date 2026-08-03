"""Stage 81 — Orange County's audited statements, read from its own ACFRs, every year.

The county is the LARGER half of a Hillsborough resident's property tax bill — 67.58
cents per $100 against the town's 51.30 — and until now not one county figure in this
project came from a county audit. They came from Amy's design workbook, which
transcribed them by hand, cited as `OC_ACFR_2025` with no page number. Her own
verification block says so plainly: of 396 imported rows, 41 were checkable against a
page we hold and **355 were not verifiable at all**.

Every county ACFR in the archive is digital text (stage 80 established that), so
there is no reason for that. This stage reads the audits directly:

    FY2018 CAFR · FY2020 CAFR · FY2021 ACFR · FY2022 ACFR · FY2023 ACFR
    FY2024 ACFR · FY2025 ACFR · FY2018-19 Annual Financial Report

and it does two jobs at once, which is the point:

1. **Load the county's own detail** at page-level citation — the General Fund
   budget-vs-actual, the governmental funds statements, net position, activities —
   on exactly the same footing as the town's, into the same fact table, because the
   government is a column.

2. **Verify Amy's transcription** rather than replace it. Her workbook stays the
   source of truth for her own analysis and is never written to; this stage checks
   whether each figure she recorded actually appears in the audit's own statement
   for that year, and reports what it could not find. That is the doctrine the
   project already follows with her material — import and verify, twice now her
   figures have matched to the dollar — and it is worth more than a second
   implementation that quietly disagrees.

   The match is on VALUE, not on label. Her category names are her own ("Sales tax"
   where the audit prints "Local option sales taxes"), and inventing a label
   crosswalk here would be guessing at the very mapping the town has not yet
   supplied. A figure of hers that appears among the audited figures for the same
   year is corroborated; one that does not is reported as needing her page citation,
   not called an error — the county prints the same slice in several statements and
   an absence here is a question, not a verdict.

Reading mechanics, the reconciliation gate and the traps are all in
`etl/statement_parser.py`, shared with stage 61. Nothing about it is
jurisdiction-specific, which is the whole argument for one warehouse: the county
loaded through the same reader with no new machinery.

One county-specific caution, and it is why fiscal year is taken from the statement
heading rather than the filename: the file names carry dates in five different
shapes ("Orange Co ACFR 6.30.25Final", "Orange County 6-30-21 ACFR - client_1",
"Orange County NC ACFR 6.30.23") and two of them do not state a year the manifest
could parse — the manifest records `fiscal_year: null` for six of these eight
documents. The statements themselves say "Year Ended June 30, 2023" on the page,
so that is what is trusted.
"""
from __future__ import annotations

import logging
import re
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, SOURCES, DIGITAL, read_json, write_json  # noqa: E402

warnings.filterwarnings("ignore")
# pdfminer's per-page FontBBox noise is silenced once, in etl/common.py.

from statement_parser import (  # noqa: E402
    FY_IN_TEXT, SKIP_TITLE, STATEMENT_TITLE, FINANCIAL_TITLE, column_roles,
    group_rows, parse_page, reconcile, rollforward_checks, statement_title)

JUR = "Orange County, NC"

# Fixed list, not a glob: a scanned county report appearing under a similar name
# must not silently start feeding unverified figures into the warehouse.
WANTED_DOC_IDS = [
    "orange-county-2018-cafr",
    "fy-2018-19-annual-financial-report",
    "orange-county-cafr-6-30-20",
    "orange-county-6-30-21-acfr-client-1",
    "orange-county-acfr-6-30-22-final-2",
    "orange-county-nc-acfr-6-30-23",
    "orange-co-acfr-6-30-24-final",
    "orange-co-acfr-6-30-25final",
]

GF_STATEMENT = re.compile(r"General\s+Fund", re.I)


def read_document(doc_id: str, path: Path, problems: list):
    """Parse every statement page of one ACFR. Returns (pages, published, doc_fy)."""
    scratch, doc_fy = [], None
    with pdfplumber.open(path) as pdf:
        for i, pg in enumerate(pdf.pages, start=1):
            title = statement_title(pg)
            if doc_fy is None:
                m = FY_IN_TEXT.search(title)
                if m:
                    doc_fy = int(m.group(1))
            if SKIP_TITLE.search(title):
                continue
            if not STATEMENT_TITLE.search(title):
                continue
            parsed, edges, probs = parse_page(pg, i)
            problems.extend(probs)
            if not parsed or len(edges) < 2:
                continue
            groups = reconcile(group_rows(parsed, len(edges)), len(edges))
            rf_rows, rf_checks = rollforward_checks(parsed, len(edges))
            if not groups and not rf_rows:
                continue
            m = FY_IN_TEXT.search(title)
            sm = re.search(r"(Exhibit\s+[A-Z0-9-]+|Schedule\s+[A-Z0-9-]+)", title, re.I)
            scratch.append({
                "page": i, "title": title, "edges": edges, "groups": groups,
                "rf_rows": rf_rows, "rf_checks": rf_checks,
                "page_fy": int(m.group(1)) if m else doc_fy,
                "stmt_key": (re.sub(r"\s+", " ", sm.group(1)).title() if sm
                             else f"page-{i}"),
            })

    # Column roles per statement, pooled across its pages — a single page of a
    # multi-page schedule often prints too few totals to confirm the layout.
    by_stmt: dict[tuple, list] = defaultdict(list)
    for s in scratch:
        by_stmt[(s["stmt_key"], len(s["edges"]))].append(s)
    stmt_roles = {k: column_roles([g for s in v for g in s["groups"]], k[1])
                  for k, v in by_stmt.items()}

    pages_out, published = [], []
    for s in scratch:
        roles, proof = stmt_roles[(s["stmt_key"], len(s["edges"]))]
        if roles:
            proof += f" (pooled across {s['stmt_key']})"
        fin_grain = bool(FINANCIAL_TITLE.search(s["title"]))
        stmt = re.sub(r"\s+", " ", s["title"])[:190]
        ok = sum(1 for g in s["groups"] if g["reconciles"])

        pages_out.append({
            "statement_key": s["stmt_key"], "page": s["page"], "title": stmt,
            "fiscal_year": s["page_fy"], "columns": len(s["edges"]),
            "column_roles": {str(k): v for k, v in roles.items()},
            "column_roles_confirmed_by": proof,
            "groups_total": len(s["groups"]), "groups_reconciled": ok,
            "rollforward_lines_proved": len(s["rf_rows"]),
            "rollforward_checks": s["rf_checks"],
            "financial_grain": fin_grain, "groups": s["groups"],
        })

        def emit(group, line, values, is_subtotal, proof_text, _s=s, _stmt=stmt,
                 _roles=roles, _fin=fin_grain):
            published.append({
                "jurisdiction": JUR, "fiscal_year": _s["page_fy"],
                "statement": _stmt, "statement_key": _s["stmt_key"],
                "group": group, "line": line, "is_subtotal": is_subtotal,
                "values": values,
                "column_roles": {str(k): v for k, v in _roles.items()},
                "verified_by": proof_text, "financial_grain": _fin,
                "source_doc": doc_id, "source_page": _s["page"],
                "extraction": DIGITAL,
            })

        for g in s["groups"]:
            if not g["reconciles"]:
                continue
            for m_ in g.get("publish_members", g["members"]):
                emit(g["group"], m_["label"], m_["values"], m_["is_subtotal"],
                     "components sum to the printed total, per column")
            emit(g["group"], g["total_label"], g["total"], True,
                 "printed total, reconciled against its components")
        for r in s["rf_rows"]:
            emit("(roll-forward)", r["label"], r["values"], False,
                 f"the statement's own identity: {r['identity']}")

    return pages_out, published, doc_fy


def verify_amy(published) -> dict:
    """Does each figure in Amy's county workbook appear in that year's audited read?

    Value-based, per fiscal year, for the reasons in the module docstring. Reports
    corroborated / not-found counts and lists what was not found so she can supply
    the page — this is a question for her, never a claim that she is wrong.
    """
    path = DATASETS / "warehouse_county.json"
    if not path.exists():
        return {"ran": False, "why": "warehouse_county.json not present"}

    by_year: dict[int, set] = defaultdict(set)
    for p in published:
        if p["fiscal_year"] is None:
            continue
        for v in p["values"]:
            if v is not None:
                by_year[p["fiscal_year"]].add(round(abs(v), 2))

    rows = read_json(path)["rows"]
    fields = ("Original_Budget", "Final_Budget", "Actual_Amount", "Amount", "Variance")
    found = notfound = 0
    misses = []
    for r in rows:
        fy = r.get("Fiscal_Year_ID")
        m = re.match(r"FY(\d{4})$", str(fy or ""))
        if not m:
            continue
        year = int(m.group(1))
        if year not in by_year:
            continue
        for f in fields:
            v = r.get(f)
            if v is None or not isinstance(v, (int, float)) or abs(v) < 1000:
                continue
            if round(abs(float(v)), 2) in by_year[year]:
                found += 1
            else:
                notfound += 1
                if len(misses) < 60:
                    misses.append({"table": r.get("table"), "fiscal_year": fy,
                                    "category": r.get("Category"), "field": f,
                                    "value": v, "her_citation": r.get("ACFR_Page")})

    return {
        "ran": True,
        "question": ("Does each monetary figure in Amy's county workbook appear among the "
                     "figures this stage read from that year's audited statements?"),
        "method": ("Matched on VALUE within the same fiscal year, not on label — her category "
                   "names are her own and inventing a label crosswalk would be guessing at the "
                   "mapping the town has not supplied. Figures under $1,000 are skipped because "
                   "small integers collide by chance."),
        "figures_corroborated": found,
        "figures_not_found": notfound,
        "not_found_means": ("a question for Amy, not an error: the county prints the same slice "
                            "in several statements, and this stage withholds any group whose "
                            "arithmetic it could not prove, so an absence can be on either side"),
        "years_covered": sorted(by_year),
        "not_found_sample": misses,
    }


def main() -> None:
    docs = {d["id"]: d for d in read_json(DATASETS / "documents.json")["documents"]}

    results, published, problems = [], [], []
    for doc_id in WANTED_DOC_IDS:
        doc = docs.get(doc_id)
        if not doc:
            problems.append(f"{doc_id}: not in the manifest — skipped")
            continue
        path = SOURCES / doc["archive_path"]
        if not path.exists():
            problems.append(f"{doc_id}: {path} missing — skipped")
            continue

        pages_out, pub, doc_fy = read_document(doc_id, path, problems)
        published.extend(pub)
        recon = sum(p["groups_reconciled"] for p in pages_out)
        tot = sum(p["groups_total"] for p in pages_out)
        results.append({"document": doc_id, "filename": doc["filename"],
                        "fiscal_year": doc_fy, "statement_pages": len(pages_out),
                        "groups_total": tot, "groups_reconciled": recon,
                        "lines_published": len(pub), "pages": pages_out})
        print(f"  {doc['filename'][:44]:46s} FY{doc_fy}  {len(pages_out):3d} pages  "
              f"{recon}/{tot} groups  {len(pub)} lines", flush=True)

    amy = verify_amy(published)

    write_json(DATASETS / "county_acfr.json", {
        "generated_by": "etl/s81_county_acfr.py",
        "note": ("Orange County's audited statements, read directly from the county's own "
                 "ACFRs — every one of which is digital text, so no character recognition is "
                 "involved. A line is published only where its group's components add up "
                 "exactly to the total printed beside them, per column; groups that do not "
                 "reconcile are withheld with a recorded reason."),
        "why_this_matters": ("The county rate is larger than the town's, and until this stage "
                             "every county figure in the project came from a hand transcription "
                             "with no page citation. These have both."),
        "amy_workbook_verification": amy,
        "documents": results,
        "published": published,
        "extraction_problems": problems[:200],
        "extraction_problem_count": len(problems),
    })

    # ---- the per-displayed-value verification record the site needs ------------
    #
    # The 2026-08-01 audit's M-01: the page reported that only two of the sixteen
    # county summary values had been rechecked, and blamed "years that do not resolve
    # to a held file". That was true of the OLDER s85 path and stopped being true the
    # moment this stage began reading all eight ACFRs directly — so the site was
    # understating its own evidence AND giving a false reason for the gap.
    #
    # Written back into warehouse_county.json rather than shipped as a new dataset:
    # county_acfr.json is 8.5 MB and adding a fetch would worsen the page-weight
    # finding in the same audit. The site already reads `verification` from that file.
    wc_path = DATASETS / "warehouse_county.json"
    if wc_path.exists():
        wc = read_json(wc_path)
        # Every total this stage read directly, by (fiscal year, section).
        direct = {}
        for pub in published:
            lbl = str(pub.get("line") or "").lower()
            grp = str(pub.get("group") or "").lower()
            if not pub.get("fiscal_year") or not lbl.startswith("total"):
                continue
            sect = ("revenues" if "revenue" in lbl or "revenue" in grp
                    else "expenditures" if "expenditure" in lbl or "expenditure" in grp
                    else None)
            if not sect:
                continue
            for v in (pub.get("values") or []):
                if v is not None:
                    direct.setdefault((int(pub["fiscal_year"]), sect), []).append(
                        {"amount": round(float(v), 2), "page": pub.get("source_page"),
                         "document": pub.get("source_doc")})
        checks = []
        for r in wc.get("rows", []):
            cat = str(r.get("Category") or "").strip().lower()
            sect = ("revenues" if cat == "total revenues"
                    else "expenditures" if cat == "total expenditures" else None)
            amt = r.get("Actual_Amount")
            fy = str(r.get("Fiscal_Year_ID") or "")
            if not sect or amt is None or not fy.startswith("FY"):
                continue
            year = int(fy[2:])
            hits = [h for h in direct.get((year, sect), [])
                    if abs(h["amount"] - float(amt)) < 0.005]
            checks.append({
                "fiscal_year": fy, "section": sect, "amount": float(amt),
                "method": "read directly from the county's own ACFR by this pipeline",
                "found": bool(hits),
                "source_document": hits[0]["document"] if hits else None,
                "source_page": hits[0]["page"] if hits else None,
                "limit": ("value-level only — this confirms the amount appears as a printed "
                          "total for that year and section, not that the workbook's label and "
                          "attribution are right"),
            })
        found = sum(1 for c in checks if c["found"])
        wc.setdefault("verification", {})["direct_reader"] = {
            "generated_by": "etl/s81_county_acfr.py",
            "values_checked": len(checks),
            "values_found": found,
            "values_not_found": len(checks) - found,
            "note": ("One record per figure the site displays. Supersedes the older "
                     "page-citation check for these values, which could only test rows whose "
                     "workbook Source_ID resolved to a held file."),
            "checks": checks,
        }
        write_json(wc_path, wc)
        print(f"  site verification record: {found}/{len(checks)} displayed county values "
              f"found in the ACFRs read directly")

    fin = sum(1 for p in published if p["financial_grain"])
    print(f"\n  {len(published)} verified county lines published "
          f"({fin} at fund financial grain, {len(published)-fin} companion)")
    if amy.get("ran"):
        tot = amy["figures_corroborated"] + amy["figures_not_found"]
        pct = 100.0 * amy["figures_corroborated"] / tot if tot else 0.0
        print(f"  Amy's workbook: {amy['figures_corroborated']}/{tot} figures corroborated "
              f"({pct:.0f}%) against the audits directly")


if __name__ == "__main__":
    main()
