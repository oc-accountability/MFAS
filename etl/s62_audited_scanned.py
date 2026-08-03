"""Stage 62 — read the SCANNED audits with the same reader, and the same gate, as the digital ones.

Stage 61 reads the town's digital audits: every exhibit and schedule, nested groups,
column roles proven by the statement's own arithmetic. Stage 75 reads the scanned
ones — and reaches exactly one statement per year, because it matches runs of
whitespace in flat text.

That asymmetry was never about recognition quality. It was about coordinates. Stage
71 now recognises the scanned statement pages WITH word boxes, so this stage feeds
them to `statement_parser` — the identical code path, the identical reconciliation
gate — and a scanned year gets the same depth as a digital one.

**The bar does not move, and that is the whole argument.** A line is published only
where its group's components add up exactly to the total printed beside them, per
column. Character recognition fails by altering a digit, and an altered digit breaks
the sum. So the arithmetic is not a sanity check bolted on afterwards — it is the
reason any of this is publishable, and it applies here exactly as it does to a
digital page.

Where this is weaker than a digital read, stated plainly rather than buried:

  * Recognition can DROP a word entirely (low confidence, a speck on the scan). A
    dropped figure usually breaks the column sum and costs the group, which is the
    correct outcome — but a dropped LABEL can silently merge two rows.
  * The arithmetic gate is strong evidence, not proof. Two offsetting errors in one
    column would survive it. Stage 63 exists because of that sentence: it measures
    this path against a digital original for the same year, line by line, so the
    residual risk is quantified instead of argued about.
  * Everything published here is `ocr-arithmetic-verified`, never `digital-text`,
    and the export grades it one confidence level below a direct read.

**A digital original always wins — for PUBLISHING.** Nothing from a year we hold
digitally is loaded into the warehouse. But the scan of such a year is still read,
into `validation_only`, because it is the ground truth stage 63 measures this path
against. The first version skipped those years outright and thereby destroyed the
only overlap that made measurement possible; stage 63 then correctly reported "not
measurable", having been handed nothing to measure. FY2018 joined that category on
2026-07-31 when the Finance Director sent the issued CAFR — which is exactly the
outcome this project keeps asking for, and it doubled the ground truth available.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import warnings
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (BUILD, DATASETS, OCR_VERIFIED, read_json, write_json)  # noqa: E402

warnings.filterwarnings("ignore")
# pdfminer's per-page FontBBox noise is silenced once, in etl/common.py.

from statement_parser import (  # noqa: E402
    FINANCIAL_TITLE, SKIP_TITLE, STATEMENT_TITLE, column_roles, detect_grid,
    group_rows, reconcile, rollforward_checks, split_row, to_columns,
    tokens_in_band, FY_IN_TEXT)

JUR = "Town of Hillsborough, NC"
BAND = 3.0


def estimate_skew(words: list[dict]) -> float:
    """Slope (dy/dx) of the page's text lines. Paper on a scanner is never square.

    THIS IS THE SINGLE BIGGEST LIMIT ON READING A SCAN, and it took a while to see
    because it does not look like a recognition problem at all — every word comes back
    correct, and the page still yields nothing.

    A digital PDF puts every word of a line at the same `top`, so bucketing by
    `round(top / 3pt)` rebuilds rows perfectly. A scanned page is rotated by a fraction
    of a degree, so `top` DRIFTS across the page: on FY2019 p46 the title row runs from
    y=52.3 at the left margin to y=48.7 at the right, 3.6pt of drift over 490pt. Bucket
    that on a fixed 3pt grid and one printed row lands in two or three different rows —
    its label in one, half its figures in another. No group can then reconcile, because
    the components and the printed total are no longer on the same row.

    That is why FY2019 published 11 of 115 groups while its recognition was fine. The
    symptom (`Exhibit Town of Hillsborough, North Carolina 5 of Revenues...` as a page
    title) reads like garbled OCR and is actually a correct word list sorted by a y that
    slopes.

    Measured by projection profile: rotate by each candidate slope, histogram the word
    centres onto horizontal lines, and keep the slope whose histogram is most PEAKED —
    when the rotation is right, every word of a line falls in one bin. Scoring by sum of
    squares (weighted by word width, so a long label counts more than a stray mark)
    because that is maximised exactly when mass concentrates. On FY2019 p46 this finds
    -0.401 deg and more than doubles the profile score.
    """
    if len(words) < 12:
        return 0.0

    def score(slope: float) -> float:
        h: dict[int, float] = defaultdict(float)
        for w in words:
            xc = (w["x0"] + w["x1"]) / 2.0
            yc = (w["top"] + w["bottom"]) / 2.0
            h[round(yc - slope * xc)] += (w["x1"] - w["x0"])
        return sum(v * v for v in h.values())

    # +-0.03 rad (~1.7 deg) in 0.0005 steps: wider than any scanner feed produces,
    # fine enough that the residual drift across a page is under a point.
    return max((i / 2000.0 for i in range(-60, 61)), key=score)


def deskew(words: list[dict]) -> list[dict]:
    """Words with `top`/`bottom` corrected so a printed line is horizontal."""
    slope = estimate_skew(words)
    if not slope:
        return words
    out = []
    for w in words:
        shift = slope * ((w["x0"] + w["x1"]) / 2.0)
        out.append({**w, "top": w["top"] - shift, "bottom": w["bottom"] - shift})
    return out


def line_bands(words: list[dict]) -> list[list[dict]]:
    """Cluster words into printed lines by proximity, not by a fixed grid.

    Even on a deskewed page a fixed `round(top / BAND)` grid splits any line that
    happens to straddle a bucket boundary. Clustering on the gap between successive
    word centres has no boundaries to straddle: a new line starts only where the
    vertical gap exceeds BAND.
    """
    if not words:
        return []
    ordered = sorted(words, key=lambda w: (w["top"] + w["bottom"]) / 2.0)
    bands, cur = [], [ordered[0]]
    prev = (ordered[0]["top"] + ordered[0]["bottom"]) / 2.0
    for w in ordered[1:]:
        yc = (w["top"] + w["bottom"]) / 2.0
        if yc - prev > BAND:
            bands.append(cur)
            cur = []
        cur.append(w)
        prev = yc
    bands.append(cur)
    return bands


def page_from_words(words: list[dict]):
    """Rebuild the (words, char-tokens) band structure statement_parser expects.

    The parser wants two views of each row: pdfplumber-style words for the label, and
    character-merged tokens for the figures. Recognition gives us words only, so the
    figure tokens are rebuilt by merging adjacent words on the same line — which is
    also what repairs the single most common recognition artefact in these documents,
    a thousands separator read as a space ("8,940 238" for 8,940,238).
    """
    out = []
    for band in line_bands(deskew(words)):
        ws = sorted(band, key=lambda w: w["x0"])
        toks: list[dict] = []
        for w in ws:
            digit_x1 = w["x1"] if any(c.isdigit() for c in w["text"]) else None
            if toks and w["x0"] - toks[-1]["x1"] <= 5.0:
                prev = toks[-1]
                prev["text"] += w["text"]
                prev["x1"] = w["x1"]
                if digit_x1 is not None:
                    prev["digit_x1"] = digit_x1
            else:
                toks.append({"text": w["text"], "x0": w["x0"], "x1": w["x1"],
                             "digit_x1": digit_x1})
        out.append((ws, toks))
    return out


def parse_layout_page(words: list[dict], page_no: int):
    rows_tok = page_from_words(words)
    edges, boundary = detect_grid(rows_tok)
    problems: list[str] = []
    if len(edges) < 2 or boundary is None:
        return [], edges, problems

    parsed = []
    for ws, toks in rows_tok:
        label, indent, figs = split_row(ws, toks, boundary)
        vals, bad = to_columns(figs, edges)
        if not label and not any(v is not None for v in vals):
            continue
        if bad:
            problems.append(f"p{page_no}: {label[:40]!r} figure(s) {bad} match no column")
        parsed.append({"label": label, "indent": indent, "values": vals,
                       "has_figures": any(v is not None for v in vals)})
    return parsed, edges, problems


def page_title(words: list[dict]) -> str:
    """The top-of-page text, for statement identification.

    Deskewed for the same reason as the rows: on a sloping page a plain (top, x0) sort
    interleaves the right-hand exhibit number into the left-hand title, and the title is
    what decides whether a page is read at all.
    """
    out: list[str] = []
    for band in line_bands(deskew(words)):
        out.extend(w["text"] for w in sorted(band, key=lambda w: w["x0"]))
        if len(out) >= 40:
            break
    return " ".join(out[:40])


def main() -> None:
    docs = {d["id"]: d for d in read_json(DATASETS / "documents.json")["documents"]}
    layout = read_json(DATASETS / "ocr_layout.json")

    # Years read directly by stage 61. A scan of such a year is read but never
    # published — see the module docstring.
    digital_years = set()
    ad_path = DATASETS / "audited_digital.json"
    if ad_path.exists():
        for d in read_json(ad_path).get("documents", []):
            if d.get("fiscal_year"):
                digital_years.add(int(d["fiscal_year"]))

    results, published, problems, skipped = [], [], [], []
    # Read from a year we hold digitally: kept ONLY so stage 63 can compare
    # the two routes cell by cell. Never loaded into the warehouse.
    validation = []

    for entry in layout.get("documents", []):
        doc = docs.get(entry["document"])
        if not doc:
            continue
        if doc["sha256"] != entry.get("sha256"):
            problems.append(f"{doc['id']}: layout hash mismatch — rerun stage 71")
            continue
        # A year we hold digitally is still READ — it is the ground truth stage 63
        # measures this path against — but nothing from it is published. The first
        # version skipped such years outright, which removed the only overlap that
        # made measurement possible: stage 63 then correctly reported "not measurable",
        # having been handed nothing to measure. Read for evidence, publish nothing.
        fy = doc.get("fiscal_year")
        validation_only = bool(fy and int(fy) in digital_years)
        if validation_only:
            skipped.append({"document": doc["id"], "fiscal_year": fy,
                            "reason": "a digital original of this year is read directly by "
                                      "stage 61, so nothing here is published — but the "
                                      "scan IS read, because it is the ground truth stage "
                                      "63 measures the recognition path against"})

        layout_dir = BUILD / entry["layout_dir"]
        if not layout_dir.is_dir():
            problems.append(f"{doc['id']}: layout dir missing — rerun stage 71")
            continue

        scratch, doc_fy = [], fy
        for f in sorted(layout_dir.glob("p*.json")):
            try:
                words = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not words:
                continue
            title = page_title(words)
            if SKIP_TITLE.search(title) or not STATEMENT_TITLE.search(title):
                continue
            page_no = int(f.stem[1:])
            parsed, edges, probs = parse_layout_page(words, page_no)
            problems.extend(probs)
            if not parsed or len(edges) < 2:
                continue
            groups = reconcile(group_rows(parsed, len(edges)), len(edges))
            rf_rows, rf_checks = rollforward_checks(parsed, len(edges))
            if not groups and not rf_rows:
                continue
            m = FY_IN_TEXT.search(title)
            sm = re.search(r"(Exhibit\s+[A-Z0-9-]+|Schedule\s+[A-Z0-9-]+)", title, re.I)
            scratch.append({"page": page_no, "title": title, "edges": edges,
                            "groups": groups, "rf_rows": rf_rows, "rf_checks": rf_checks,
                            "page_fy": int(m.group(1)) if m else doc_fy,
                            "stmt_key": (re.sub(r"\s+", " ", sm.group(1)).title()
                                         if sm else f"page-{page_no}")})

        by_stmt: dict[tuple, list] = defaultdict(list)
        for s in scratch:
            by_stmt[(s["stmt_key"], len(s["edges"]))].append(s)
        stmt_roles = {k: column_roles([g for s in v for g in s["groups"]], k[1])
                      for k, v in by_stmt.items()}

        pages_out = []
        for s in scratch:
            roles, proof = stmt_roles[(s["stmt_key"], len(s["edges"]))]
            fin = bool(FINANCIAL_TITLE.search(s["title"]))
            stmt = re.sub(r"\s+", " ", s["title"])[:190]
            ok = sum(1 for g in s["groups"] if g["reconciles"])
            pages_out.append({"page": s["page"], "title": stmt,
                              "statement_key": s["stmt_key"],
                              "fiscal_year": s["page_fy"], "columns": len(s["edges"]),
                              "column_roles": {str(k): v for k, v in roles.items()},
                              "column_roles_confirmed_by": proof,
                              "groups_total": len(s["groups"]), "groups_reconciled": ok,
                              "financial_grain": fin, "groups": s["groups"]})

            def emit(group, line, values, is_subtotal, proof_text,
                     _s=s, _stmt=stmt, _roles=roles, _fin=fin,
                     _sink=(validation if validation_only else published)):
                _sink.append({
                    "jurisdiction": JUR, "fiscal_year": _s["page_fy"],
                    "statement": _stmt, "statement_key": _s["stmt_key"],
                    "group": group, "line": line, "is_subtotal": is_subtotal,
                    "values": values,
                    "column_roles": {str(k): v for k, v in _roles.items()},
                    "verified_by": proof_text, "financial_grain": _fin,
                    "source_doc": doc["id"], "source_page": _s["page"],
                    # NEVER digital-text. A consumer must always be able to tell that
                    # this figure was recognised from an image.
                    "extraction": OCR_VERIFIED,
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

        recon = sum(p["groups_reconciled"] for p in pages_out)
        tot = sum(p["groups_total"] for p in pages_out)
        results.append({"document": doc["id"], "filename": doc["filename"],
                        "fiscal_year": doc_fy, "statement_pages": len(pages_out),
                        "groups_total": tot, "groups_reconciled": recon,
                        "pages": pages_out})
        print(f"  {doc['filename'][:44]:46} FY{doc_fy}  {len(pages_out):3} pages  "
              f"{recon}/{tot} groups reconcile", flush=True)

    write_json(DATASETS / "audited_scanned.json", {
        "generated_by": "etl/s62_audited_scanned.py",
        "note": ("Audited statements recovered from SCANNED reports by character "
                 "recognition with layout, then held to the identical arithmetic gate "
                 "as the digital audits: a line publishes only where its group's "
                 "components add up exactly to the printed total, per column."),
        "honest_limits": (
            "This is recognition, not reading. The arithmetic gate is strong evidence "
            "and not proof — two offsetting errors in one column would survive it — "
            "which is why stage 63 measures this output against a digital original for "
            "the same year rather than asserting it is fine. Every figure is marked "
            "ocr-arithmetic-verified and is graded one confidence level below a direct "
            "read. A digital original always wins and the scan is then not used at all."),
        "digital_years_skipped": sorted(digital_years),
        "skipped": skipped,
        "documents": results,
        "published": published,
        "validation_only": validation,
        "validation_only_note": (
            "Lines recovered from a scan of a year we ALSO hold digitally. These are "
            "never loaded into the warehouse — the digital reading wins — and exist so "
            "stage 63 can measure this path against a known-good reading of the same "
            "statements."),
        "extraction_problems": problems[:200],
        "extraction_problem_count": len(problems),
    })

    fin = sum(1 for p in published if p["financial_grain"])
    print(f"\n  {len(published)} verified lines recovered from scans "
          f"({fin} at fund financial grain)")
    print(f"  {len(skipped)} document(s) skipped because a digital original exists")


if __name__ == "__main__":
    main()
