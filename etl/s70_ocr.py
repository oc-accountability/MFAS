"""Stage 70 — OCR every scanned document.

The scanned annual reports hold the town's audited history, and their embedded
text layer is unusable (docs/EXTRACTION_NOTES.md). Fresh OCR *is* usable: measured
against the one report that exists in both scanned and digital form, tesseract at
300 DPI reproduced 141 of 141 figures exactly (`etl/ocr_accuracy_probe.py`).

This stage produces the text. It does **not** decide that any figure is correct —
stage 75 does that, and only for figures whose column sums exactly to the total
printed beside them.

Two rules encoded here:

1. **A digital original always wins.** Where the same report exists as a proper
   digital file, that file is used and the scan is skipped entirely. Right now
   that applies to FY2025. This is also the standing recommendation to the town:
   publishing digital originals removes this entire class of risk.
2. **Resumable and cached.** ~1,000 pages of rendering and recognition is slow, so
   each page's text is written once under build/ (gitignored) and skipped on a
   re-run. Deleting build/ocr forces a clean redo.
"""
from __future__ import annotations

import subprocess
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (BUILD, DATASETS, SOURCES, content_cache_dir, read_json,  # noqa: E402
                    write_json)

warnings.filterwarnings("ignore")

DPI = 300
OCR_ROOT = BUILD / "ocr"

# A scanned report that also exists as a digital file: use the digital one, skip
# the scan. Maps scanned document id -> digital document id that supersedes it.
SUPERSEDED_BY_DIGITAL = {
    "annual-financial-report-year-ended-june-30-2025": "fiscal-year-2025-financial-report",
}

# Same content, no text at all, and duplicated by the other FY2018 file.
SKIP = {"comprehensive-annual-financial-report-fy18"}


def ocr_page(pdf: Path, page: int, out: Path) -> str:
    """Render one page and recognise it. Returns the text."""
    if out.exists():
        return out.read_text(encoding="utf-8", errors="replace")
    tmp = out.parent / f".render-{page}"
    subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(DPI),
                    "-gray", "-png", str(pdf), str(tmp)],
                   check=True, capture_output=True)
    img = next(out.parent.glob(f".render-{page}-*.png"), None)
    if img is None:
        out.write_text("", encoding="utf-8")
        return ""
    try:
        # psm 6 (a uniform block of text) reads financial tables far better than
        # the default page-segmentation guesswork.
        r = subprocess.run(["tesseract", str(img), "stdout", "--psm", "6", "-l", "eng",
                            "-c", "preserve_interword_spaces=1"],
                           capture_output=True, text=True, timeout=180)
        text = r.stdout
    except subprocess.TimeoutExpired:
        text = ""
    finally:
        img.unlink(missing_ok=True)
    out.write_text(text, encoding="utf-8")
    return text


def main() -> None:
    docs = read_json(DATASETS / "documents.json")["documents"]
    digital_ids = {d["id"] for d in docs if d.get("text_layer") == "digital"}
    targets = [d for d in docs
               if d.get("text_layer") == "scan"
               and d["id"] not in SKIP
               and SUPERSEDED_BY_DIGITAL.get(d["id"]) not in digital_ids]

    skipped = [{"document": d["id"],
                "reason": ("a digital original of the same report is available and is used instead"
                           if SUPERSEDED_BY_DIGITAL.get(d["id"]) in digital_ids
                           else "duplicate with no recoverable content")}
               for d in docs if d.get("text_layer") == "scan" and d not in targets]

    OCR_ROOT.mkdir(parents=True, exist_ok=True)
    summary = []
    t0 = time.time()

    for d in targets:
        src = SOURCES / d["archive_path"]
        if not src.exists():
            print(f"  MISSING {d['archive_path']}")
            continue
        # Bound to the file's CONTENT and the recogniser's configuration, so a
        # replaced or corrected PDF can never serve text recognised from the old
        # one. See common.content_cache_dir for why this matters more than it looks.
        engine = subprocess.run(["tesseract", "--version"], capture_output=True,
                                text=True).stdout.splitlines()[0]
        out_dir = content_cache_dir("ocr", d["sha256"], extractor=f"tesseract:{engine}",
                                    version="1", dpi=DPI, mode="gray")
        pages = d.get("pages") or 0
        done = chars = 0
        for pg in range(1, pages + 1):
            txt = ocr_page(src, pg, out_dir / f"p{pg:04d}.txt")
            chars += len(txt)
            done += 1
            if done % 25 == 0:
                print(f"    {d['id'][:44]:46} {done}/{pages} pages "
                      f"({time.time()-t0:.0f}s elapsed)", flush=True)
        summary.append({"document": d["id"], "filename": d["filename"],
                        "sha256": d["sha256"],
                        # Recorded so stage 75 reads exactly these directories rather
                        # than enumerating whatever is left lying under build/ocr —
                        # an orphaned directory from a superseded file used to be
                        # indistinguishable from a current one.
                        "text_dir": str(out_dir.relative_to(BUILD)),
                        "pages": pages, "chars": chars,
                        "chars_per_page": round(chars / pages) if pages else 0})
        print(f"  done {d['filename'][:52]:54} {pages:4}pg  {chars:>9,} chars", flush=True)

    # Sweep orphans. A directory left behind by a superseded or replaced source is
    # indistinguishable from a live one to anything that enumerates build/ocr, and it
    # is exactly what let stale text be published against a document whose hash had
    # moved on. Stage 75 now reads the manifest rather than the directory listing, so
    # this is belt and braces — but a cache that quietly accumulates dead entries is
    # also how someone later "helpfully" restores one.
    live = {s["text_dir"] for s in summary}
    orphans = []
    for d in sorted(OCR_ROOT.iterdir()):
        if not d.is_dir():
            continue
        rel = str(d.relative_to(BUILD))
        if rel in live:
            continue
        orphans.append(rel)
        for f in d.glob("*"):
            f.unlink()
        d.rmdir()
    if orphans:
        print(f"  swept {len(orphans)} orphaned OCR cache director(ies): "
              f"{', '.join(o.split('/')[-1] for o in orphans[:4])}"
              f"{' …' if len(orphans) > 4 else ''}")

    write_json(DATASETS / "ocr_manifest.json", {
        "generated_by": "etl/s70_ocr.py",
        "orphaned_caches_swept": orphans,
        "note": ("Text recovered by character recognition from the scanned reports. Recognition "
                 "quality was measured at 141/141 figures on a document that exists in both "
                 "scanned and digital form, but recognition is never assumed correct: no figure "
                 "reaches the website from here unless its column sums exactly to the total "
                 "printed beside it (stage 75)."),
        "best_practice": ("Replace every scanned PDF with the town's original digital copy. A "
                          "digital original removes this entire class of risk, because the figures "
                          "are read directly rather than recognised from an image. Where a digital "
                          "original exists it is already used in preference to the scan."),
        "engine": subprocess.run(["tesseract", "--version"], capture_output=True,
                                 text=True).stdout.splitlines()[0],
        "render_dpi": DPI,
        "documents": summary,
        "skipped": skipped,
        "total_pages": sum(s["pages"] for s in summary),
        "elapsed_seconds": round(time.time() - t0),
    })
    print(f"\n  {sum(s['pages'] for s in summary):,} pages OCR'd across {len(summary)} documents "
          f"in {time.time()-t0:.0f}s")
    for s in skipped:
        print(f"  skipped {s['document'][:50]:52} — {s['reason']}")


if __name__ == "__main__":
    main()
