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
exact-match on the full set of money tokens per page.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
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
            truth = numbers_in(digital_pages[pg])
            got = numbers_in(ocr_page(SCAN, pg, tmp))
            tset, gset = set(truth), set(got)
            matched = tset & gset
            missed = sorted(tset - gset)
            spurious = sorted(gset - tset)
            rate = len(matched) / len(tset) * 100 if tset else 0.0
            results.append({
                "page": pg, "truth_numbers": len(tset), "ocr_numbers": len(gset),
                "matched": len(matched), "recall_pct": round(rate, 1),
                "missed_sample": missed[:12], "spurious_sample": spurious[:12],
            })
            print(f"  p{pg:>4}: {len(matched):4}/{len(tset):4} matched "
                  f"({rate:5.1f}%)   {len(spurious):3} spurious")

    tot_t = sum(r["truth_numbers"] for r in results)
    tot_m = sum(r["matched"] for r in results)
    tot_s = sum(len(r["spurious_sample"]) for r in results)
    overall = tot_m / tot_t * 100 if tot_t else 0.0

    verdict = ("OCR reproduces the audited figures exactly — safe to use with per-page "
               "arithmetic checks" if overall >= 99.5 else
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
        "verdict": verdict,
    })
    print(f"\n  overall: {tot_m}/{tot_t} numbers reproduced exactly "
          f"({overall:.2f}%), {tot_s}+ spurious")
    print(f"  verdict: {verdict}")


if __name__ == "__main__":
    main()
