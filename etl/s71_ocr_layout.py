"""Stage 71 — recognise the scanned pages WITH COORDINATES, so the real reader can use them.

The problem this solves. Stage 75 reads exactly one statement out of a thousand
scanned pages: the General Fund budget-vs-actual. It does that by matching runs of
whitespace in flat text, which is why it can only cope with one layout. Meanwhile
stage 61 reads the DIGITAL audits properly — every exhibit and schedule, nested
groups, proven column roles — because `statement_parser` works on the x-coordinate
of every word.

So the scanned years were not limited by recognition quality. They were limited by
throwing the coordinates away. Tesseract will emit word-level bounding boxes (TSV
output); feeding those to the same parser gives a scanned page the same treatment as
a digital one, gated by the same arithmetic.

**This does not lower the bar, and the bar is what makes it publishable.** Every
group still has to reconcile against the total printed beside it, per column, or it
is withheld. Recognition failure changes a digit; a changed digit breaks the sum. The
difference from stage 75 is only how much of the document the reader can reach.

Three safeguards, because this is recognition and not reading:

1. **Everything produced here is marked `ocr-arithmetic-verified`, never
   `digital-text`.** A downstream consumer can always tell which figures were
   recognised from an image, and the export grades them one confidence level below a
   direct read.
2. **A digital original always wins.** Where one exists for a year, the scan is not
   read at all — that is the standing recommendation, and FY2018 became a digital
   year on 2026-07-31.
3. **Ground truth, measured at depth.** Stage 63 compares this path's output against
   the digital original for the SAME year, statement by statement and line by line.
   That is a real check on hundreds of figures rather than the six-page probe.

Cached content-addressed like every other extraction (common.content_cache_dir), so
a replaced or corrected PDF can never serve boxes recognised from the old one.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import subprocess
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (BUILD, DATASETS, SOURCES, content_cache_dir, read_json,  # noqa: E402
                    write_json)

warnings.filterwarnings("ignore")
# pdfminer's per-page FontBBox noise is silenced once, in etl/common.py.

DPI = 300

# Only pages that plausibly carry a financial statement are recognised with layout —
# running 1,400 pages through tesseract twice would cost hours for prose we discard.
# The cheap filter is stage 70's flat text, which already exists.
STATEMENT_HINT = ("exhibit", "schedule", "statement of", "balance sheet",
                  "budget and actual", "revenues", "expenditures", "fund balance")


def tsv_words(pdf: Path, page: int, out: Path) -> list[dict]:
    """Recognise one page and return word boxes. Cached as JSON."""
    if out.exists():
        try:
            return json.loads(out.read_text(encoding="utf-8"))
        except Exception:
            pass                                  # corrupt cache entry: redo it

    tmp = out.parent / f".layout-{page}"
    subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(DPI),
                    "-gray", "-png", str(pdf), str(tmp)],
                   check=True, capture_output=True)
    img = next(out.parent.glob(f".layout-{page}-*.png"), None)
    if img is None:
        out.write_text("[]", encoding="utf-8")
        return []
    try:
        r = subprocess.run(
            ["tesseract", str(img), "stdout", "--psm", "6", "-l", "eng",
             "-c", "preserve_interword_spaces=1", "tsv"],
            capture_output=True, text=True, timeout=180)
        rows = list(csv.DictReader(io.StringIO(r.stdout), delimiter="\t",
                                   quoting=csv.QUOTE_NONE))
    except subprocess.TimeoutExpired:
        rows = []
    finally:
        img.unlink(missing_ok=True)

    words = []
    for row in rows:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            conf = float(row.get("conf") or -1)
            left, top = int(row["left"]), int(row["top"])
            width, height = int(row["width"]), int(row["height"])
        except (ValueError, KeyError, TypeError):
            continue
        # Tesseract reports -1 for non-word rows and low confidence for noise. A
        # rejected word is a MISSING word, which breaks the column sum and costs us
        # the group — that is the correct failure, not a silent bad digit.
        if conf < 40:
            continue
        # Rendered at DPI; statement_parser works in PDF points (72/inch). Converting
        # here means the shared parser needs no knowledge of where the words came from.
        s = 72.0 / DPI
        words.append({"text": text,
                      "x0": round(left * s, 2), "x1": round((left + width) * s, 2),
                      "top": round(top * s, 2), "bottom": round((top + height) * s, 2),
                      "conf": conf})
    out.write_text(json.dumps(words), encoding="utf-8")
    return words


def main() -> None:
    docs = {d["id"]: d for d in read_json(DATASETS / "documents.json")["documents"]}
    ocr_manifest = read_json(DATASETS / "ocr_manifest.json")

    engine = subprocess.run(["tesseract", "--version"], capture_output=True,
                            text=True).stdout.splitlines()[0]
    summary, problems = [], []
    t0 = time.time()

    for entry in ocr_manifest.get("documents", []):
        doc = docs.get(entry["document"])
        if not doc:
            problems.append(f"{entry['document']}: in the OCR manifest but not the "
                            f"document manifest — skipped")
            continue
        if doc["sha256"] != entry.get("sha256"):
            problems.append(f"{doc['id']}: OCR manifest hash does not match the archive "
                            f"— rerun stage 70 before this stage")
            continue
        src = SOURCES / doc["archive_path"]
        if not src.exists():
            problems.append(f"{doc['id']}: {src} missing")
            continue

        flat_dir = BUILD / entry["text_dir"]
        out_dir = content_cache_dir("ocr-layout", doc["sha256"],
                                    extractor=f"tesseract-tsv:{engine}",
                                    version="1", dpi=DPI, mode="gray", min_conf=40)

        # Pick the pages worth the second pass, using stage 70's flat text.
        candidates = []
        for f in sorted(flat_dir.glob("p*.txt")):
            head = f.read_text(encoding="utf-8", errors="replace")[:600].lower()
            if any(h in head for h in STATEMENT_HINT):
                candidates.append(int(f.stem[1:]))

        done = 0
        for pg in candidates:
            tsv_words(src, pg, out_dir / f"p{pg:04d}.json")
            done += 1
            if done % 20 == 0:
                print(f"    {doc['id'][:42]:44} {done}/{len(candidates)} pages "
                      f"({time.time()-t0:.0f}s)", flush=True)

        summary.append({"document": doc["id"], "filename": doc["filename"],
                        "sha256": doc["sha256"],
                        "layout_dir": str(out_dir.relative_to(BUILD)),
                        "pages_total": doc.get("pages"),
                        "pages_with_layout": len(candidates)})
        print(f"  {doc['filename'][:48]:50} {len(candidates):4} statement-ish pages",
              flush=True)

    write_json(DATASETS / "ocr_layout.json", {
        "generated_by": "etl/s71_ocr_layout.py",
        "what_this_is": (
            "Word-level bounding boxes for the statement pages of every scanned "
            "document, so the same reader that handles the digital audits can read a "
            "scan. Coordinates are converted to PDF points, so nothing downstream "
            "needs to know the page came from an image."),
        "why": ("Stage 75 reaches exactly one statement per scanned report because it "
                "matches runs of whitespace in flat text. The scanned years were never "
                "limited by recognition quality — they were limited by discarding the "
                "coordinates."),
        "safety": ("Nothing here is published on its own. Stage 62 runs these boxes "
                   "through the same arithmetic gate as the digital audits, and stage "
                   "63 measures the result against a digital original for the same "
                   "year. Every figure that survives is marked ocr-arithmetic-verified, "
                   "never digital-text."),
        "engine": engine, "render_dpi": DPI, "min_word_confidence": 40,
        "documents": summary,
        "problems": problems,
        "elapsed_seconds": round(time.time() - t0),
    })
    print(f"\n  layout recognised for {len(summary)} document(s), "
          f"{sum(s['pages_with_layout'] for s in summary)} pages, "
          f"{time.time()-t0:.0f}s")
    for p in problems:
        print(f"      {p}")


if __name__ == "__main__":
    main()
