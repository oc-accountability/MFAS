"""Stage 63 — measure the recognition path against a digital original, at depth.

The honest problem with publishing anything recovered from a scan: the argument for
it is that a misread digit breaks the column's arithmetic, so a group that reconciles
is almost certainly right. "Almost certainly" is doing real work in that sentence.
Two offsetting errors in one column would survive the gate, and no amount of restating
the argument turns it into proof.

So measure it. FIVE years are now held in both forms — FY2018 and FY2021-FY2024 —
because the town's digital audits arrived for the later years and the Finance Director
sent the issued FY2018 CAFR on 2026-07-31, while the scans of all of them remain.

For those years the pipeline reads the same statements twice by two entirely different
routes — pdfplumber on embedded text, and tesseract on rendered images — and compares
every figure. That is a real error rate on the actual documents at the actual depth we
publish, rather than a six-page sample of distinct values.

Measured 2026-08-01, after the deskew fix: **5,394 of 5,394 figures identical,
100.00%** (it read 1,941/1,941 before deskew — reading MORE of the scan cost no
accuracy at all). Not a single
recognised figure that survived the arithmetic gate disagreed with the digital
original. That is the evidence base for publishing anything from a scan — and it is
also why the gate stays: the figures that did NOT survive it are not in that count.

What is compared, and why it is a fair test:

    For each (fiscal year, statement, line, column) the recognition path publishes,
    look up the same cell in the digital reading and compare the amounts exactly.

Both sides have already passed their own arithmetic gate, so this is not "did OCR
read the page" — it is "having passed the gate, is the figure the same one the
digital original prints". Those are different questions and only the second one
matters for publication.

Three outcomes are reported separately, because collapsing them hides the interesting
case:

  * **agree** — same cell, same amount.
  * **disagree** — same cell, different amount. This is the number that matters, and
    the build fails if any appear, because a disagreement means the gate let a wrong
    figure through and every other scanned year is then suspect.
  * **only in one** — a cell one path found and the other did not. Not an error: the
    two readers legitimately reach different amounts of a document. Reported so the
    coverage difference is visible rather than being mistaken for agreement.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, read_json, write_json  # noqa: E402


def norm_line(s: str) -> str:
    """Compare labels forgivingly — recognition alters spacing and punctuation."""
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def cells(published: list[dict]) -> dict[tuple, float]:
    """(fiscal_year, statement, PAGE, group, line, column) -> amount.

    The page is in the key, and leaving it out produced six false disagreements that
    cost a real investigation — worth recording, because the failure looked exactly
    like the thing this stage exists to catch.

    Exhibit 1 prints "Pension deferrals" and "OPEB deferrals" TWICE: once under
    DEFERRED OUTFLOWS OF RESOURCES and again under DEFERRED INFLOWS, on facing pages.
    The parser's group label for both collapses to "RESOURCES" (the caps header wraps
    across lines), so without the page the two rows share a key. The digital reader
    found all four rows and kept the first; the recognition reader found only the
    second pair — so the comparison put page 37's recognised figures against page 36's
    digital ones and reported six mismatches. Every recognised value was in fact
    identical to the digital value on its own page.

    Including the page also tightens the test: only cells BOTH readers found on the
    SAME page are compared, and anything else is counted as a coverage difference.
    """
    out: dict[tuple, float] = {}
    for p in published:
        fy = p.get("fiscal_year")
        if not fy:
            continue
        for ci, v in enumerate(p.get("values") or []):
            if v is None:
                continue
            key = (int(fy), str(p.get("statement_key") or ""), p.get("source_page"),
                   norm_line(p.get("group")), norm_line(p.get("line")), ci)
            # A page can still legitimately repeat a label; keep the first reading
            # rather than letting the last silently win.
            out.setdefault(key, float(v))
    return out


def main() -> None:
    dig_path = DATASETS / "audited_digital.json"
    scan_path = DATASETS / "audited_scanned.json"
    if not dig_path.exists() or not scan_path.exists():
        sys.exit("stage 63 needs both audited_digital.json and audited_scanned.json")

    digital = read_json(dig_path)
    scanned = read_json(scan_path)

    dig_cells = cells(digital.get("published", []))
    # BOTH buckets. `published` is what the warehouse loads; `validation_only` is what
    # stage 62 read from a scan of a year we also hold digitally — deliberately not
    # published, and the only place an overlap can exist at all. Comparing `published`
    # alone means comparing the two paths on years they never share, which is how this
    # stage first reported "not measurable" while the evidence sat in the same file.
    scan_cells = cells(list(scanned.get("published", []))
                       + list(scanned.get("validation_only", [])))

    dig_years = {k[0] for k in dig_cells}
    scan_years = {k[0] for k in scan_cells}
    both = sorted(dig_years & scan_years)

    per_year: dict[int, dict] = defaultdict(
        lambda: {"agree": 0, "disagree": 0, "only_digital": 0, "only_scan": 0,
                 "disagreements": []})

    for key, sval in scan_cells.items():
        fy = key[0]
        if fy not in both:
            continue
        if key in dig_cells:
            dval = dig_cells[key]
            if abs(dval - sval) < 0.5:
                per_year[fy]["agree"] += 1
            else:
                per_year[fy]["disagree"] += 1
                if len(per_year[fy]["disagreements"]) < 25:
                    per_year[fy]["disagreements"].append({
                        "statement": key[1], "page": key[2], "group": key[3],
                        "line": key[4], "column": key[5],
                        "digital": dval, "recognised": sval,
                        "difference": round(sval - dval, 2)})
        else:
            per_year[fy]["only_scan"] += 1
    for key in dig_cells:
        if key[0] in both and key not in scan_cells:
            per_year[key[0]]["only_digital"] += 1

    agree = sum(v["agree"] for v in per_year.values())
    disagree = sum(v["disagree"] for v in per_year.values())
    checked = agree + disagree
    rate = (agree / checked * 100) if checked else None

    verdict = (
        "NOT MEASURABLE — no fiscal year is currently held in both digital and scanned "
        "form, so the recognition path has no ground truth. Treat scan-derived figures "
        "with the caution their label implies." if not checked else
        f"{agree}/{checked} figures identical ({rate:.2f}%) across "
        f"{len(both)} year(s) read by two independent routes"
        if disagree == 0 else
        f"DISAGREEMENT: {disagree} of {checked} figures differ — the arithmetic gate "
        f"passed a figure that the digital original contradicts")

    out = {
        "generated_by": "etl/s63_ocr_ground_truth.py",
        "question": ("Having passed its own arithmetic gate, does a figure recovered "
                     "from a scan match the figure the digital original prints?"),
        "method": ("For every (fiscal year, statement, group, line, column) the "
                   "recognition path publishes, the same cell is looked up in the "
                   "digital reading and the amounts compared exactly. Both sides have "
                   "already passed the reconciliation gate, so this measures what "
                   "survives it, not whether recognition works."),
        "why_this_exists": ("The case for publishing anything read from a scan is that "
                            "a misread digit breaks the column sum. That is strong "
                            "evidence and not proof — offsetting errors would survive "
                            "it — so the residual risk is measured rather than argued."),
        "years_in_both_forms": both,
        "figures_compared": checked,
        "figures_identical": agree,
        "figures_differing": disagree,
        "agreement_pct": round(rate, 2) if rate is not None else None,
        "coverage_note": ("'only_digital' and 'only_scan' are NOT errors: the two "
                          "readers reach different amounts of a document, and a cell "
                          "one found and the other did not is a coverage difference. "
                          "It is reported separately so it cannot be mistaken for "
                          "agreement."),
        "per_year": {str(k): v for k, v in sorted(per_year.items())},
        "verdict": verdict,
    }
    write_json(DATASETS / "ocr_ground_truth.json", out)

    print(f"  years held in both forms: {both or 'NONE'}")
    for fy in both:
        v = per_year[fy]
        tot = v["agree"] + v["disagree"]
        pct = f"{v['agree']/tot*100:.2f}%" if tot else "n/a"
        print(f"    FY{fy}: {v['agree']}/{tot} identical ({pct})   "
              f"only-digital {v['only_digital']}, only-scan {v['only_scan']}")
    print(f"\n  {verdict}")

    if disagree:
        for fy in both:
            for d in per_year[fy]["disagreements"][:8]:
                print(f"      FY{fy} {d['statement']} p{d['page']} {d['line'][:30]:32} "
                      f"digital={d['digital']:,.0f} recognised={d['recognised']:,.0f}")
        sys.exit("\nBUILD FAILED — a figure that passed the arithmetic gate disagrees "
                 "with the digital original. Every scan-derived figure is suspect until "
                 "this is understood; do not publish around it.")


if __name__ == "__main__":
    main()
