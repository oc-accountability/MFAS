"""Stage 61 — the audited statements, read from the DIGITAL originals, every year.

This stage exists because of a sentence the OCR stages have carried as a standing
recommendation since they were written:

    "Replace every scanned PDF with the town's original digital copy. A digital
     original removes this entire class of risk, because the figures are read
     directly rather than recognised from an image."

Amy obtained them. `Audit 2021.pdf` and the four LGC-stamped
`_Hillsborough 20NN Audit - Stamped.pdf` files are the town's own digital audits
for FY2021 through FY2025 — embedded font text, no scanning, no character
recognition — and until now not one figure had been read out of any of them.
Stage 60 read the single FY2025 digital twin; this stage generalises it to every
year that has a digital original, which is what makes an audited series possible
at all.

What that unlocks, concretely. The scanned reports yield ONE self-verifying
statement per year (stage 75), and only its column totals. These documents carry
the full apparatus:

  * Exhibits 1-8 — government-wide net position and activities, the governmental
    funds balance sheet, the fund revenue/expenditure statements, the proprietary
    funds.
  * Schedule 1, six pages — the General Fund budget-vs-actual at DEPARTMENTAL
    detail. Governing body, facility management, administration, finance, human
    resources, communications, information services, planning, engineering, police,
    fire, streets, powell bill, solid waste, cemetery, economic development. Per
    department: personnel services, other services and charges, capital outlay,
    debt service, reimbursement from enterprise funds.
  * Schedules 2-20 — every other fund on the same budget-vs-actual basis.

How the statements are actually read — and the six traps that reading them cost —
is in `etl/statement_parser.py`, which this stage and the county ACFR stage share.
The safety property is the project's usual one:

    A line is published only if its group's components add up EXACTLY to the
    total printed beside them, per column.

Groups that do not reconcile are withheld with a recorded reason, never published
with a caveat. That gate is doing real work here — roughly one group in five is
withheld, and the ones that are tend to be balance-sheet grand totals whose two
sides are both printed as page-level totals, whose every component line is
published anyway via its own subtotal.

What makes these readings believable is not the parser, it is that they agree with
readings taken from OTHER documents by OTHER code (`cross_checks` below, and it
fails the build on a disagreement):

  * FY2025 against stage 60's read of the separate small digital twin report,
  * FY2021, FY2022 and FY2024 against stage 75's figures recovered by character
    recognition from the SCANNED reports.

All five agree to the dollar. A digital reading and a scan recognition of two
different publications of the same audit landing on the same number is about as
close to an external audit as this project can get.

Routing, deliberately conservative: fund-level revenue / expenditure / other
financing lines go to the financial fact table. Statements at a different grain —
cash flows, pension and OPEB schedules, taxes receivable, net position — are
published here with their statement name and grain, and are NOT mixed into
Fact_Financial. Forcing them into a financial fact table would be worse than
loading them deliberately as companion facts.
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

JUR = "Town of Hillsborough, NC"

# The documents this stage reads: every Hillsborough audit that is digital text.
# Deliberately a fixed list rather than a glob — a new scan appearing under a
# similar name must not silently start feeding the pipeline unverified figures.
WANTED_DOC_IDS = [
    # Obtained 2026-07-31 from the town's Finance Director. FY2018 was the thinnest
    # year in the entire warehouse — 31 facts — because only scans existed for it.
    # Measured on arrival: 19 embedded fonts and 265,291 characters over 175 pages,
    # against 163 characters for the FY2020 file sent in the same batch. Two of the
    # three were scans re-sent; this one is the real thing.
    "cafr-issued-toh-fy2018",
    "audit-2021",
    "hillsborough-2022-audit-stamped",
    "hillsborough-2023-audit-stamped",
    "hillsborough-2024-audit-stamped",
    "hillsborough-2025-audit-stamped",
]


GF_STATEMENT = re.compile(r"General\s+Fund", re.I)


def gf_totals(published):
    """The General Fund revenue/expenditure totals this stage read, by year."""
    out: dict[tuple, dict] = {}
    for p in published:
        if not GF_STATEMENT.search(p["statement"]):
            continue
        if p["line"] not in ("Total revenues", "Total expenditures"):
            continue
        roles = {int(k): v for k, v in p["column_roles"].items()}
        if "actual" not in roles.values():
            continue
        col = next(k for k, v in roles.items() if v == "actual")
        if col >= len(p["values"]) or p["values"][col] is None:
            continue
        section = "revenues" if p["line"] == "Total revenues" else "expenditures"
        out[(p["fiscal_year"], section)] = {
            "actual": p["values"][col], "source_doc": p["source_doc"],
            "source_page": p["source_page"], "statement": p["statement"]}
    return out


def cross_checks(published):
    """Does this stage agree with what the project already read independently?

    Two checks, and they are the strongest evidence available that these readings
    are right — each compares a DIFFERENT document read by a DIFFERENT parser:

      * Stage 60 read the small digital twin of the FY2025 report. This stage read
        the LGC-stamped FY2025 audit. Same statement, two publications.
      * Stage 75 recovered column totals from the SCANNED reports by character
        recognition, gated on the page's own arithmetic. Those years overlap
        FY2021-FY2024 here, where this stage read digital text instead. Agreement
        means the scan recognition and the digital reading independently produced
        the same audited figure.

    A disagreement is reported, never smoothed over — and note which side would be
    suspect: a mismatch here is far more likely to be a comparison keyed on the
    wrong statement (the first version of this function compared any fund's total,
    not the General Fund's) than a bad reading.
    """
    mine = gf_totals(published)
    checks = []

    p60 = DATASETS / "audited_general_fund.json"
    if p60.exists():
        a = read_json(p60)
        for r in a.get("rows", []):
            if not r.get("is_total"):
                continue
            key = (a.get("fiscal_year"), r["section"])
            if key in mine and r.get("actual") is not None:
                diff = mine[key]["actual"] - r["actual"]
                checks.append({
                    "check": "digital audit vs the separate digital twin report (stage 60)",
                    "fiscal_year": key[0], "section": key[1],
                    "this_stage": mine[key]["actual"], "other": r["actual"],
                    "other_source": a.get("source_doc"),
                    "difference": round(diff, 2), "agree": abs(diff) < 1.5})

    p75 = DATASETS / "ocr_statements.json"
    if p75.exists():
        for pub in read_json(p75).get("published", []):
            if pub.get("column_role") != "actual":
                continue
            key = (pub["fiscal_year"], pub["section"])
            if key in mine:
                diff = mine[key]["actual"] - pub["total"]
                checks.append({
                    "check": "digital audit vs the scanned report recovered by OCR (stage 75)",
                    "fiscal_year": key[0], "section": key[1],
                    "this_stage": mine[key]["actual"], "other": pub["total"],
                    "other_source": pub["source_doc"],
                    "difference": round(diff, 2), "agree": abs(diff) < 1.5})

    agree = sum(1 for c in checks if c["agree"])
    return {"note": ("Each row compares a figure this stage read from a digital audit against "
                     "the same figure read from a DIFFERENT document by a DIFFERENT parser. "
                     "Agreement across two independent readings is the closest thing this "
                     "project has to an external audit."),
            "checks_run": len(checks), "checks_agreeing": agree, "checks": checks}


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

        # Two passes over the document. Column roles are resolved per STATEMENT, not
        # per page: Schedule 1 runs to six pages and several of them print only one
        # or two group totals, too few to confirm the variance identity alone. Pooling
        # a statement's pages both finds the roles and makes them CONSISTENT across
        # that statement — page-at-a-time labelled page 96 of Schedule 1 and left
        # pages 93-95 of the same schedule unknown.
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
                sm = re.search(r"(Exhibit\s+\d+|Schedule\s+(?:RSI-)?\d+)", title, re.I)
                scratch.append({
                    "page": i, "title": title, "edges": edges, "groups": groups,
                    "rf_rows": rf_rows, "rf_checks": rf_checks,
                    "page_fy": int(m.group(1)) if m else doc_fy,
                    "stmt_key": (re.sub(r"\s+", " ", sm.group(1)).title() if sm
                                 else f"page-{i}"),
                })

        # Resolve roles once per statement, from all of that statement's totals.
        by_stmt: dict[tuple, list] = defaultdict(list)
        for s in scratch:
            by_stmt[(s["stmt_key"], len(s["edges"]))].append(s)
        stmt_roles: dict[tuple, tuple] = {}
        for key, entries in by_stmt.items():
            pooled = [g for s in entries for g in s["groups"]]
            stmt_roles[key] = column_roles(pooled, key[1])

        pages_out = []
        for s in scratch:
            i, title, edges = s["page"], s["title"], s["edges"]
            groups, rf_rows, page_fy = s["groups"], s["rf_rows"], s["page_fy"]
            roles, roles_proof = stmt_roles[(s["stmt_key"], len(edges))]
            if roles:
                roles_proof += f" (pooled across {s['stmt_key']})"

            ok = sum(1 for g in groups if g["reconciles"])
            pages_out.append({
                "statement_key": s["stmt_key"],
                    "page": i,
                    "title": re.sub(r"\s+", " ", title)[:190],
                    "fiscal_year": page_fy,
                    "columns": len(edges),
                    "column_roles": {str(k): v for k, v in roles.items()},
                    "column_roles_confirmed_by": roles_proof,
                "groups_total": len(groups),
                "groups_reconciled": ok,
                "rollforward_lines_proved": len(rf_rows),
                "rollforward_checks": s["rf_checks"],
                "financial_grain": bool(FINANCIAL_TITLE.search(title)),
                "groups": groups,
            })

            fin_grain = bool(FINANCIAL_TITLE.search(title))
            stmt = re.sub(r"\s+", " ", title)[:190]

            def emit(group, line, values, is_subtotal, proof,
                     _fy=page_fy, _stmt=stmt, _roles=roles, _fin=fin_grain, _p=i,
                     _key=s["stmt_key"]):
                published.append({
                    "jurisdiction": JUR, "fiscal_year": _fy,
                    "statement": _stmt, "statement_key": _key,
                    "group": group, "line": line,
                    "is_subtotal": is_subtotal, "values": values,
                    "column_roles": {str(k): v for k, v in _roles.items()},
                    "verified_by": proof, "financial_grain": _fin,
                    "source_doc": doc_id, "source_page": _p,
                    "extraction": DIGITAL,
                })

            for g in groups:
                if not g["reconciles"]:
                    continue
                for m_ in g.get("publish_members", g["members"]):
                    emit(g["group"], m_["label"], m_["values"], m_["is_subtotal"],
                         "components sum to the printed total, per column")
                emit(g["group"], g["total_label"], g["total"], True,
                     "printed total, reconciled against its components")

            for r in rf_rows:
                emit("(roll-forward)", r["label"], r["values"], False,
                     f"the statement's own identity: {r['identity']}")

        recon = sum(p["groups_reconciled"] for p in pages_out)
        tot = sum(p["groups_total"] for p in pages_out)
        results.append({"document": doc_id, "filename": doc["filename"],
                        "fiscal_year": doc_fy, "statement_pages": len(pages_out),
                        "groups_total": tot, "groups_reconciled": recon,
                        "pages": pages_out})
        print(f"  {doc['filename'][:48]:50s} FY{doc_fy}  "
              f"{len(pages_out):3d} statement pages  {recon}/{tot} groups reconcile")

    cross = cross_checks(published)

    write_json(DATASETS / "audited_digital.json", {
        "generated_by": "etl/s61_audited_digital.py",
        "cross_document_checks": cross,
        "note": ("Audited statements read directly from the town's DIGITAL audit reports "
                 "(FY2021-FY2025) — embedded text, no character recognition, so none of the "
                 "digit-transposition risk of the scanned reports applies. A line is published "
                 "only where its group's components add up exactly to the total printed beside "
                 "them, per column; groups that do not reconcile are withheld and listed."),
        "method": ("The statements are nested and the nesting is printed as indentation: a label "
                   "ending ':' opens a group, a 'Total' row closes it, and a closed group's total "
                   "becomes one member of its parent. Column roles are proven by the statement's "
                   "own variance identity rather than assumed from column order."),
        "documents": results,
        "published": published,
        "extraction_problems": problems[:200],
        "extraction_problem_count": len(problems),
    })

    fin = sum(1 for p in published if p["financial_grain"])
    print(f"\n  {len(published)} verified lines published "
          f"({fin} at fund financial grain, {len(published)-fin} companion)")
    print(f"  {len(problems)} extraction problems recorded")
    print(f"  cross-document checks: {cross['checks_agreeing']}/{cross['checks_run']} agree")
    for c in cross["checks"]:
        if not c["agree"]:
            print(f"      DISAGREES FY{c['fiscal_year']} {c['section']}: "
                  f"{c['this_stage']:,.0f} vs {c['other']:,.0f} ({c['other_source']})")
    if cross["checks_run"] and cross["checks_agreeing"] < cross["checks_run"]:
        sys.exit("\nBUILD FAILED — a digital reading disagrees with an independent reading "
                 "of the same figure. Resolve which is right before publishing either.")


if __name__ == "__main__":
    main()
