"""Stage 75 — recover audited figures from OCR, but only where the page proves them.

Stage 70 produced text from the scanned reports. This stage turns a narrow, high
value slice of it into published figures: the **General Fund budget-vs-actual
statement** in each annual report, which gives the audited outcome for a year —
what was budgeted, what was actually spent, and the difference.

The safety property, and the whole reason this is publishable:

    A figure is published only if the column it belongs to adds up EXACTLY to the
    total printed beside it on the same page.

Character recognition fails by changing a digit. A changed digit breaks the
column's arithmetic, so it cannot slip through unnoticed — the page checks itself.
Columns that do not balance are withheld entirely rather than published with a
caveat, because a caveat on a wrong number is still a wrong number.

This is deliberately narrower than "extract everything". Extracting every table
from 1,000 OCR'd pages would produce a great deal of data that nothing verifies.
One self-checking statement per year is worth more than a hundred unverifiable
tables, and it is exactly the series a resident wants: did the town spend what it
said it would, every year?

Note the standing recommendation this stage exists under: **a digital original
would remove the need for any of it.** Where one exists it is used instead
(FY2025), and no recognition is involved.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BUILD, DATASETS, read_json, write_json  # noqa: E402

OCR_ROOT = BUILD / "ocr"

# The statement we want, however each year's report words its heading.
WANTED = re.compile(r"Budget\s+and\s*\n?\s*Actual", re.I)
GF = re.compile(r"General\s+Fund", re.I)
EXCLUDE = re.compile(r"Nonmajor|Capital Project|Capital Reserve|Special Revenue|"
                     r"Table of Contents|Schedule of", re.I)

# OCR mangles currency marks, and routinely reads a thousands COMMA as a SPACE
# ("8,940 238" for 8,940,238). Both separators are therefore accepted while
# scanning, and a candidate is only kept if it forms valid thousands grouping.
#
# This is safe to attempt precisely because the column arithmetic is the arbiter:
# a repair that makes the column add up to its printed total is almost certainly
# the right reading, and one that does not is rejected along with the column. The
# residual risk is a standalone three-digit number sitting immediately after
# another figure, which could merge — rare in these statements, and it would break
# the sum and be withheld.
# Each separator is ONE comma or ONE space followed by exactly three digits. That
# distinction is load-bearing: allowing a run of spaces makes the pattern swallow
# the next column's figure too ("1,815,676        1,873,421" as a single token).
NUM = re.compile(r"\(?\$?\s?\d{1,3}(?:[, ]\d{3})+\)?|\(?\$?\s?\d{3,}\)?")
ROW = re.compile(r"^\s*(?P<label>[A-Za-z][A-Za-z ,'()&/\-\.]{3,60}?)\s{2,}(?P<rest>.+)$")

TOTAL_REV = re.compile(r"^total\s+revenue", re.I)
TOTAL_EXP = re.compile(r"^total\s+expenditure", re.I)


def parse_num(tok: str) -> float | None:
    t = tok.strip()
    neg = t.startswith("(") or t.endswith(")")
    t = t.strip("()").replace("$", "").strip()
    # Accept a space where a thousands comma belongs, but ONLY if the result is
    # properly grouped — otherwise we would be inventing a figure, not reading one.
    if re.fullmatch(r"\d{1,3}(?:[, ]\d{3})+", t):
        v = float(re.sub(r"[, ]", "", t))
        # A space-repair is a guess, so it must produce a plausible figure. Two
        # adjacent columns can look like one number ("10,079,224 760,114" reads as
        # a valid grouping and merges into 10,079,224,760,114). No line in a town
        # budget reaches a billion dollars, so that cap rejects the merge and the
        # two figures are then read separately, as intended.
        if " " in t and v >= 1e9:
            return None
        return -v if neg else v
    t = t.replace(" ", "")
    if not re.fullmatch(r"\d{1,3}(?:,\d{3})*|\d{3,}", t):
        return None
    v = float(t.replace(",", ""))
    return -v if neg else v


def numbers(rest: str) -> list[float]:
    out = []
    for m in NUM.finditer(rest):
        tok = m.group(0)
        v = parse_num(tok)
        if v is not None:
            out.append(v)
            continue
        # The token spanned a space and merged into an implausible figure — so it
        # was two adjacent columns, not one number. Fall back to reading each
        # side. Dropping the whole token here silently lost BOTH figures.
        if " " in tok.strip():
            for piece in tok.split():
                pv = parse_num(piece)
                if pv is not None:
                    out.append(pv)
    return out


def parse_statement(text: str):
    """Return (rows, totals) for a budget-vs-actual page."""
    rows, totals = [], {}
    section = None
    closed: set[str] = set()
    for raw in text.split("\n"):
        low = raw.strip().lower().rstrip(":")
        # EXACT match, not startswith. "Revenues over (under) expenditures" is a
        # derived line further down the statement; treating it as a section header
        # re-opened the revenues block and swept the "other financing sources"
        # rows into it, inflating revenues by over a million dollars.
        if low in {"revenues", "revenue"}:
            if "revenues" not in closed:
                section = "revenues"
            continue
        if low in {"expenditures", "expenditure"}:
            if "expenditures" not in closed:
                section = "expenditures"
            continue
        m = ROW.match(raw)
        if not m or section is None:
            continue
        label = re.sub(r"\s+", " ", m.group("label")).strip(" .")
        nums = numbers(m.group("rest"))
        if len(nums) < 2:
            continue
        # A section ends at its own total and never re-opens; everything printed
        # below it belongs to other blocks (transfers, financing sources).
        if TOTAL_REV.match(label):
            totals.setdefault("revenues", nums)
            closed.add("revenues")
            section = None
            continue
        if TOTAL_EXP.match(label):
            totals.setdefault("expenditures", nums)
            closed.add("expenditures")
            section = None
            continue
        if label.lower().startswith("total"):
            continue
        rows.append({"section": section, "line": label, "values": nums})
    return rows, totals


def column_roles(totals) -> dict[int, str]:
    """Work out which column is Original Budget / Final Budget / Actual / Variance —
    and prove it rather than assuming the conventional order.

    These statements conventionally print Original, Final, Actual, Variance, but a
    column index means nothing on its own and charting the wrong one would be a
    silent, serious error. The variance column has a defined relationship to the
    other two — for revenues it is actual − final, for expenditures final − actual
    — so the layout can be *confirmed* by arithmetic. If it does not confirm, the
    roles stay unknown and the figures are published without them rather than
    guessed at.
    """
    for section, tot in totals.items():
        if len(tot) < 4:
            continue
        want = (tot[2] - tot[1]) if section == "revenues" else (tot[1] - tot[2])
        if abs(want - tot[3]) < 1.0:
            return {0: "original_budget", 1: "final_budget", 2: "actual", 3: "variance"}
    return {}


def verify(rows, totals):
    """Which columns add up exactly? Only those may be published."""
    verified = {}
    for section, tot in totals.items():
        parts = [r for r in rows if r["section"] == section]
        if not parts:
            continue
        width = min([len(tot)] + [len(p["values"]) for p in parts])
        for col in range(width):
            got = sum(p["values"][col] for p in parts)
            if abs(got - tot[col]) < 1.0:
                verified[(section, col)] = {"sum": got, "printed": tot[col], "lines": len(parts)}
    return verified


def main() -> None:
    if not OCR_ROOT.exists():
        sys.exit("no OCR output — run etl/s70_ocr.py first")
    docs = {d["id"]: d for d in read_json(DATASETS / "documents.json")["documents"]}

    results, published, problems = [], [], []
    for doc_dir in sorted(OCR_ROOT.iterdir()):
        if not doc_dir.is_dir():
            continue
        doc = docs.get(doc_dir.name)
        if not doc:
            continue
        fy = doc.get("fiscal_year")
        best = None
        for page_file in sorted(doc_dir.glob("p*.txt")):
            text = page_file.read_text(encoding="utf-8", errors="replace")
            if not (WANTED.search(text) and GF.search(text)) or EXCLUDE.search(text[:400]):
                continue
            rows, totals = parse_statement(text)
            if not totals:
                continue
            v = verify(rows, totals)
            if not v:
                continue
            score = sum(x["lines"] for x in v.values())
            if best is None or score > best["score"]:
                best = {"page": int(page_file.stem[1:]), "rows": rows,
                        "totals": totals, "verified": v, "score": score,
                        "roles": column_roles(totals)}

        if best is None:
            problems.append(f"{doc_dir.name}: no self-verifying budget-vs-actual page found "
                            f"— nothing published from this document")
            results.append({"document": doc_dir.name, "fiscal_year": fy,
                            "status": "no verifiable statement"})
            continue

        cols = sorted({c for (_s, c) in best["verified"]})
        entry = {"document": doc_dir.name, "fiscal_year": fy, "page": best["page"],
                 "column_roles": {str(k): v for k, v in best["roles"].items()},
                 "column_roles_confirmed_by": (
                     "the variance column equals actual minus final budget (revenues) "
                     "or final budget minus actual (expenditures)" if best["roles"]
                     else "NOT confirmed — roles left unknown rather than assumed"),
                 "verified_columns": [{"section": s, "column_index": c, **d}
                                      for (s, c), d in sorted(best["verified"].items())],
                 "status": "verified"}
        results.append(entry)

        for (section, col), d in sorted(best["verified"].items()):
            published.append({
                "fiscal_year": fy, "section": section, "column_index": col,
                "column_role": best["roles"].get(col),   # None if not confirmed
                "total": d["printed"], "component_lines": d["lines"],
                "source_doc": doc_dir.name, "source_page": best["page"],
                "extraction": "ocr-arithmetic-verified",
                "note": ("Recovered by character recognition from a scanned page, then verified: "
                         "the individual lines add up exactly to the total printed on the same "
                         "page, so a misread digit would have broken the sum."),
            })
        print(f"  {doc_dir.name[:52]:54} p{best['page']:<4} "
              f"{len(best['verified'])} verified column(s)")

    write_json(DATASETS / "ocr_statements.json", {
        "generated_by": "etl/s75_ocr_statements.py",
        "method": ("A figure is published only when its column adds up exactly to the total printed "
                   "beside it on the same page. Character recognition fails by altering a digit, "
                   "which breaks that sum, so the page checks itself. Columns that do not balance "
                   "are withheld rather than published with a caveat."),
        "best_practice": ("Replace every scanned PDF with the town's original digital copy. Digital "
                          "originals are read directly and need none of this verification — that is "
                          "how the FY2025 audited figures were read."),
        "documents": results,
        "published": published,
        "problems": problems,
    })
    ok = sum(1 for r in results if r["status"] == "verified")
    print(f"\n  {ok}/{len(results)} scanned reports yielded a self-verifying statement")
    print(f"  {len(published)} verified column totals published")
    for p in problems:
        print(f"      {p}")


if __name__ == "__main__":
    main()
