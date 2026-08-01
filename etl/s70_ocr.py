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

import re
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
    # kept for reporting only — see the note below on why digital years are still recognised
    digital_years = {d.get("fiscal_year") for d in docs
                     if d.get("text_layer") == "digital" and d.get("fiscal_year")}
    targets = [d for d in docs
               if d.get("text_layer") == "scan"
               and d["id"] not in SKIP
               and SUPERSEDED_BY_DIGITAL.get(d["id"]) not in digital_ids]

    # ONE SCAN PER FISCAL YEAR, and none at all for a year we hold digitally.
    #
    # On 2026-07-31 the town sent three files: a genuine digital FY2018 original and
    # re-sends of the FY2019 and FY2020 SCANS we already held under different names.
    # Without this guard the stage cheerfully queued 344 pages of recognition to
    # reproduce text it already had, and would then have offered the warehouse two
    # competing scan-derived readings of the same year — which is worse than slow.
    #
    # Preference is by SCAN FIDELITY first, and this is the part that was wrong.
    #
    # The first version preferred the SMALLEST file, to save recognition time. That is
    # the "slot not thing" bug again — file size describes the encoding, not the
    # document — and it cost two fiscal years of data. We hold FY2019 twice: a 9.6 MB
    # copy whose pages are 1-bit CCITT fax images, and a 101 MB copy whose pages are
    # 8-bit colour at the same 300 dpi. The size rule picked the fax copy. Measured on
    # page 46 (Exhibit 5, budget and actual) the fax copy misreads three figures the
    # colour copy gets right:
    #
    #     Total revenues, final budget      9,319,110  ->  9,349,110
    #     Transportation, final budget      1,106,124  -> 41,106,124
    #     Community activities, original      308,161  ->    308,164
    #
    # The arithmetic gate caught all three and withheld their columns, exactly as
    # designed — so the damage was silent and looked like a bad scan rather than a bad
    # choice of scan. FY2019 published 81 verified lines where a digital year publishes
    # 570-970. Bitonal fax compression throws away the greyscale that separates a 1 from
    # a 4 in a thin serif digit; no amount of recognition tuning gets it back.
    #
    # So: rank on bits-per-pixel actually stored in the page images, then on pixel area,
    # and only then prefer an already-cached copy. Fidelity is measured from the file's
    # own images rather than inferred from its size.
    #
    # Note what is deliberately NOT skipped here: a scan whose year we also hold
    # DIGITALLY. Recognising it is free once cached, and it is the ground truth stage
    # 63 measures the recognition path against — FY2018 gained a digital original on
    # 2026-07-31 and thereby became the second year that exists in both forms.
    # Suppression of scan-derived FIGURES for such a year belongs in stage 62, where
    # publishing decisions are made, not here where text is produced.
    # TWO defects in the first version of this guard, both caught by dry-running the
    # selection before spending an hour of recognition on it:
    #
    #   * It deduplicated on fiscal year ALONE, so `fiscal-year-2024-2026-strategic-plan`
    #     — sixteen pages, not a financial statement at all — claimed FY2024 and pushed
    #     out the actual FY2024 annual financial report. A year of audited data would
    #     have vanished and the log would have called it a duplicate.
    #   * The manifest parses no year from "Audit 2019.pdf" or "CAFR FY20", so the three
    #     files that prompted this guard escaped it entirely.
    #
    # Hence: dedup ONLY among annual reports, and derive the year from the filename when
    # the manifest has none. A document that is not an annual report is never a
    # duplicate of one and is always recognised.
    ANNUAL = re.compile(r"CAFR|ACFR|Annual\s+(Comprehensive\s+)?Financial|Audit", re.I)

    def report_year(d) -> int | None:
        if d.get("fiscal_year"):
            return int(d["fiscal_year"])
        # No leading \b before FY: these filenames use underscores
        # ("CAFR_Issued_TOH_FY2019"), and an underscore is a word character, so the
        # boundary never matched and the file escaped deduplication entirely.
        m = re.search(r"FY[\s_]?(\d{4})|FY[\s_]?(\d{2})(?!\d)|\b(20\d{2})\b",
                      d["filename"], re.I)
        if not m:
            return None
        raw = m.group(1) or m.group(3) or m.group(2)
        n = int(raw)
        return n if n > 99 else 2000 + n

    def already_cached(d):
        return any((BUILD / "ocr").glob(f"{d['sha256'][:16]}-*/p0001.txt"))

    _fidelity_cache: dict[str, tuple[int, int]] = {}

    def scan_fidelity(d) -> tuple[int, int]:
        """(bits stored per pixel, pixels per page) sampled from the file's own images.

        Read from the PDF rather than guessed from its size: a 1-bit CCITT page and an
        8-bit colour page of the same statement can differ 10x in bytes and 0x in dpi,
        and it is the BIT DEPTH that decides whether a thin '1' survives as a 1.
        Sampled over a mid-document window because front matter is often a different
        scan from the statements. Returns (0, 0) when the probe fails, which ranks the
        candidate last without crashing the build.
        """
        h = d["sha256"]
        if h in _fidelity_cache:
            return _fidelity_cache[h]
        src = SOURCES / d["archive_path"]
        best = (0, 0)
        try:
            out = subprocess.run(["pdfimages", "-list", "-f", "40", "-l", "50", str(src)],
                                 capture_output=True, text=True, timeout=120).stdout
            for line in out.splitlines()[2:]:
                f = line.split()
                if len(f) < 8:
                    continue
                try:
                    w, ht, comps, bpc = int(f[3]), int(f[4]), int(f[6]), int(f[7])
                except ValueError:
                    continue
                best = max(best, (comps * bpc, w * ht))
        except Exception:
            pass
        _fidelity_cache[h] = best
        return best

    chosen: dict[int, dict] = {}
    year_dupes = []
    # Negated fidelity so that ascending sort puts the HIGHEST-fidelity copy first;
    # already_cached is only a tiebreak between copies of equal fidelity, never a
    # reason to keep reading a worse one.
    for d in sorted(targets, key=lambda x: (report_year(x) or 0,
                                            tuple(-v for v in scan_fidelity(x)),
                                            0 if already_cached(x) else 1,
                                            x["bytes"])):
        if not ANNUAL.search(d["filename"]):
            continue                       # not an annual report: never a duplicate
        fy = report_year(d)
        if fy and fy in chosen:
            kept, drop = scan_fidelity(chosen[fy]), scan_fidelity(d)
            year_dupes.append({"document": d["id"], "fiscal_year": fy,
                               "chosen_instead": chosen[fy]["id"],
                               "chosen_bits_per_pixel": kept[0],
                               "this_bits_per_pixel": drop[0],
                               "reason": f"a higher-fidelity scan of FY{fy} is used instead "
                                         f"({chosen[fy]['id']}, {kept[0]} bits/pixel vs "
                                         f"{drop[0]}) — same report, and recognising both "
                                         f"would give the warehouse two competing "
                                         f"scan-derived readings"})
            continue
        if fy:
            chosen[fy] = d
    dupe_ids = {y["document"] for y in year_dupes}
    targets = [d for d in targets if d["id"] not in dupe_ids]

    skipped = [{"document": d["id"],
                "reason": ("a digital original of the same report is available and is used instead"
                           if SUPERSEDED_BY_DIGITAL.get(d["id"]) in digital_ids
                           else "duplicate with no recoverable content")}
               for d in docs if d.get("text_layer") == "scan" and d not in targets
               and d["id"] not in {y["document"] for y in year_dupes}] + year_dupes

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
