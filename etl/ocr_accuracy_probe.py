"""Measure OCR accuracy against a known ground truth — a probe, not a pipeline stage.

The question this answers: **can fresh OCR be trusted to read this town's financial
statements?** The embedded OCR layer in the scanned reports certainly cannot — it
transposes digits (docs/EXTRACTION_NOTES.md). But that is somebody else's OCR from
years ago, and it says nothing about what a modern engine does on a clean render.

We can answer it exactly, because one document exists in BOTH forms:

    Fiscal Year 2025 Financial Report.pdf          2 MB, digital text  <- ground truth
    Annual Financial Report_ Year Ended June 30, 2025.pdf   61 MB, scan of the same

Same report, same pages. So: render the scan, OCR it, and compare every number
against the digital twin. That yields a real error rate on the actual documents
rather than a hopeful assumption — and it is the only honest basis for deciding
whether to OCR the other seven annual reports, whose audited history is currently
locked away.

A number that is *nearly* right is the dangerous outcome here, so the comparison is
exact-match on the multiset of money tokens per page — both recall and precision.

What this probe does NOT establish: that each figure landed in the right row and
column. It compares the values present, not their placement. The per-page arithmetic
check in stage 75 is what actually gates publication, and even that is strong evidence
rather than proof — offsetting errors could in principle survive it.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from collections import Counter
import warnings
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SOURCES, write_json, DATASETS  # noqa: E402

warnings.filterwarnings("ignore")

BASE = SOURCES / "Orange County Efficiency & Accountability Initiative"
DIGITAL = BASE / ("02 Research & Documents/Hillsborough Budget/"
                  "Fiscal Year 2025 Financial Report.pdf")
SCAN = BASE / ("06 Budget & Financial Analysis/"
               "Annual Financial Report_ Year Ended June 30, 2025.pdf")

DPI = 300
# Statement pages: the numbers that matter and the hardest to read (dense columns,
# rules, dollar signs). Deliberately not prose pages, which would flatter OCR.
PAGES = [36, 37, 38, 40, 42, 43]

MONEY = re.compile(r"\(?\$?\s?\d[\d,\s]{2,}\)?")


def normalise(tok: str) -> str | None:
    """Canonicalise a money token, or reject it.

    The digital text of this document renders stray spaces INSIDE numbers
    ("1 7,047,188", "$ 2 04,657"), so spaces are stripped — but the result must
    then look like properly grouped thousands, otherwise we are inventing a
    number rather than reading one.
    """
    t = tok.replace("$", "").replace(" ", "").strip()
    neg = t.startswith("(")
    t = t.strip("()")
    if not t or not t[0].isdigit():
        return None
    if not re.fullmatch(r"\d{1,3}(?:,\d{3})*|\d+", t):
        return None
    if len(t.replace(",", "")) < 3:      # ignore page numbers, years, tiny counts
        return None
    return ("-" if neg else "") + t.replace(",", "")


def numbers_in(text: str) -> list[str]:
    out = []
    for m in MONEY.finditer(text):
        n = normalise(m.group(0))
        if n:
            out.append(n)
    return out


def ocr_page(pdf_path: Path, page: int, tmp: Path) -> str:
    stem = tmp / f"p{page}"
    subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(DPI),
                    "-gray", "-png", str(pdf_path), str(stem)],
                   check=True, capture_output=True)
    img = next(tmp.glob(f"p{page}-*.png"), None)
    if img is None:
        return ""
    # psm 6 = a uniform block of text, which suits a financial table better than
    # the default page-segmentation guesswork.
    r = subprocess.run(["tesseract", str(img), "stdout", "--psm", "6", "-l", "eng",
                        "-c", "preserve_interword_spaces=1"],
                       capture_output=True, text=True)
    return r.stdout


def main() -> None:
    for p in (DIGITAL, SCAN):
        if not p.exists():
            sys.exit(f"missing {p}")

    with pdfplumber.open(DIGITAL) as pdf:
        digital_pages = {i: (pdf.pages[i - 1].extract_text() or "") for i in PAGES}

    results = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for pg in PAGES:
            # MULTISET, not set. Converting both sides to sets collapsed every
            # duplicate amount and discarded order, so a page could score 100%
            # while the recogniser had dropped one of two identical figures or
            # invented values that happened to appear elsewhere on the page.
            # Counting occurrences catches both.
            truth = Counter(numbers_in(digital_pages[pg]))
            got = Counter(numbers_in(ocr_page(SCAN, pg, tmp)))
            matched = truth & got                       # per-value minimum
            missed = truth - got
            spurious = got - truth
            n_t, n_g, n_m = sum(truth.values()), sum(got.values()), sum(matched.values())
            recall = n_m / n_t * 100 if n_t else 0.0
            precision = n_m / n_g * 100 if n_g else 0.0
            results.append({
                "page": pg, "truth_numbers": n_t, "ocr_numbers": n_g,
                "matched": n_m,
                "recall_pct": round(recall, 1), "precision_pct": round(precision, 1),
                # FULL counts, not just the truncated samples. Reporting
                # len(spurious_sample) meant the headline "spurious" figure was
                # capped at 12 per page and understated any real problem.
                "missed_count": sum(missed.values()),
                "spurious_count": sum(spurious.values()),
                "missed_sample": sorted(missed.elements())[:12],
                "spurious_sample": sorted(spurious.elements())[:12],
            })
            print(f"  p{pg:>4}: {n_m:4}/{n_t:4} matched  recall {recall:5.1f}%  "
                  f"precision {precision:5.1f}%   {sum(spurious.values()):3} spurious")

    tot_t = sum(r["truth_numbers"] for r in results)
    tot_g = sum(r["ocr_numbers"] for r in results)
    tot_m = sum(r["matched"] for r in results)
    tot_s = sum(r["spurious_count"] for r in results)
    overall = tot_m / tot_t * 100 if tot_t else 0.0
    overall_precision = tot_m / tot_g * 100 if tot_g else 0.0

    # BOTH must hold. Recall alone answers "did it find everything?" and says
    # nothing about "did it invent anything?" — and an invented figure is the more
    # dangerous of the two, because a missing number is visibly missing.
    verdict = ("OCR reproduces the audited figures exactly — safe to use WITH the "
               "per-page arithmetic check, which remains the actual gate"
               if overall >= 99.5 and overall_precision >= 99.5 else
               "OCR is close but NOT exact — usable only with a human confirming every "
               "figure against the rendered page" if overall >= 90 else
               "OCR is not reliable enough on these documents to publish from")

    write_json(DATASETS / "ocr_accuracy_probe.json", {
        "generated_by": "etl/ocr_accuracy_probe.py",
        "question": ("Can fresh OCR be trusted to read the scanned annual financial reports? "
                     "Measured against the one report that exists in both digital and scanned "
                     "form, so the answer is evidence rather than assumption."),
        "engine": subprocess.run(["tesseract", "--version"], capture_output=True,
                                 text=True).stdout.splitlines()[0],
        "render_dpi": DPI,
        "ground_truth": DIGITAL.name,
        "scan_under_test": SCAN.name,
        "pages": results,
        "overall_recall_pct": round(overall, 2),
        "overall_precision_pct": round(overall_precision, 2),
        "spurious_values_total": tot_s,
        "method": ("Compared as MULTISETS of money tokens per page, so a duplicated "
                   "amount cannot be silently collapsed and an invented value cannot "
                   "be hidden by an identical one elsewhere on the page. BOTH recall "
                   "and precision must hold. Note the limit of the method: it checks "
                   "that the same VALUES appear, not that each sits on the right row "
                   "and column — attribution still needs a human sample."),
        "verdict": verdict,
    })
    print(f"\n  overall: {tot_m}/{tot_t} numbers reproduced exactly "
          f"({overall:.2f}%), {tot_s}+ spurious")
    print(f"  verdict: {verdict}")


if __name__ == "__main__":
    main()
