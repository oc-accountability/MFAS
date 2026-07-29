"""Stage 00 — inventory every source document and classify how readable it is.

Produces data/datasets/documents.json, the provenance backbone. Every Fact in
the published data references a document id from here, so a resident can trace
any number on the website back to a specific page of a specific file whose
sha256 is recorded.

The critical output field is `text_layer`:

  digital  — real embedded-font text. Tables extract correctly.
  scan     — page images with an OCR layer whose character positions are wrong.
             Usable for locating a table, NEVER for reading a value.

That distinction is not cosmetic. The FY2019-FY2024 annual financial reports are
all scans, and their OCR layer silently transposes digits.
"""
from __future__ import annotations

import re
import subprocess
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, SOURCES, sha256_file, write_json, fiscal_year_from_text  # noqa: E402

warnings.filterwarnings("ignore")

# Folder name in the source archive -> topical category
CATEGORY_HINTS = [
    ("Budget & Financial Analysis", "financial-report"),
    ("Hillsborough Budget", "budget"),
    ("Public Records Requests", "records-request"),
    ("Master Issues List", "issues"),
    ("Media & News", "media"),
    ("Meeting Notes", "meeting"),
    ("Stakeholder Interviews", "interview"),
    ("Taxpayer Impact", "analysis"),
    ("Public Messaging", "messaging"),
]


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"\.(pdf|xlsx|docx|zip)$", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = re.sub(r"-+", "-", s)
    return s


def classify_pdf(path: Path) -> dict:
    """Decide whether a PDF's text can be trusted for numeric values.

    Two independent signals, because either alone gives false readings:
      1. Are pages covered by a full-page raster image? (a scan)
      2. Does the font table contain *embedded* fonts? An OCR layer is
         characteristically non-embedded base-14 Helvetica.
    """
    info = {"pages": None, "text_layer": "unknown", "embedded_fonts": 0,
            "total_fonts": 0, "full_page_images": 0, "sampled_pages": 0,
            "chars_per_page": 0}
    try:
        with pdfplumber.open(path) as pdf:
            n = len(pdf.pages)
            info["pages"] = n
            # Sample rather than open all 181 pages of a 101 MB scan.
            idxs = sorted({0, n // 4, n // 3, n // 2, (2 * n) // 3, n - 1})
            idxs = [i for i in idxs if 0 <= i < n]
            chars = 0
            for i in idxs:
                pg = pdf.pages[i]
                chars += len(pg.chars)
                if any(im.get("width", 0) > pg.width * 0.9
                       and im.get("height", 0) > pg.height * 0.9
                       for im in pg.images):
                    info["full_page_images"] += 1
            info["sampled_pages"] = len(idxs)
            info["chars_per_page"] = round(chars / max(len(idxs), 1))
    except Exception as exc:  # a damaged file must not abort the manifest
        info["error"] = f"{type(exc).__name__}: {exc}"
        return info

    try:
        out = subprocess.run(["pdffonts", str(path)], capture_output=True,
                             text=True, timeout=120).stdout.splitlines()[2:]
        rows = [l for l in out if l.strip()]
        info["total_fonts"] = len(rows)
        # column layout of pdffonts: ... emb sub uni object ID
        info["embedded_fonts"] = sum(1 for l in rows if re.search(r"\syes\s+(yes|no)\s+(yes|no)\s", l))
    except Exception:
        pass

    scanned = info["full_page_images"] >= max(1, int(info["sampled_pages"] * 0.6))
    if scanned:
        info["text_layer"] = "scan"
    elif info["embedded_fonts"] > 0:
        info["text_layer"] = "digital"
    elif info["chars_per_page"] > 200:
        info["text_layer"] = "digital"
    else:
        info["text_layer"] = "unknown"
    return info


INITIATIVE = "Orange County Efficiency & Accountability Initiative"


def jurisdiction_for(name: str, text_sample: str = "") -> str:
    """Which government a document concerns — or the initiative itself.

    Every archive path begins with the initiative's own folder, whose name contains
    "Orange County", so matching the raw path made the county test match EVERY
    document and the rule silently collapsed to "does the path mention
    Hillsborough". That mislabelled the initiative's own working files (the design
    manual, the issues log) as county documents. The root is stripped first now,
    and a document that names neither government — or names both, which only the
    initiative's own framing documents do — is recorded as the initiative's."""
    blob = f"{name} {text_sample}"
    if blob.startswith(INITIATIVE):
        blob = blob[len(INITIATIVE):]
    # The town's response to the initiative's fiscal-trend data request arrived as a
    # zip whose name (and extracted folder) carries neither government's name. Its
    # contents are town staff answering about town finances, so it is the town's.
    if re.search(r"redatarequest", blob, re.I):
        return "Town of Hillsborough, NC"
    county = bool(re.search(r"orange[ _]?county|\bOC\b", blob, re.I))
    town = bool(re.search(r"Hillsborough", blob, re.I))
    if county and not town:
        return "Orange County, NC"
    if town and not county:
        return "Town of Hillsborough, NC"
    return INITIATIVE


def main() -> None:
    if not SOURCES.exists():
        sys.exit(f"missing {SOURCES} — unpack the source archive there first")

    by_hash: dict[str, dict] = {}
    order: list[str] = []

    # When the archive holds the same bytes twice, the first one seen becomes the
    # canonical entry and lends the document its id. Prefer the clean filename
    # over a browser's " (1)" download artifact so ids stay readable and stable.
    def canonical_first(p: Path):
        return (1 if re.search(r"\(\d+\)", p.name) else 0, str(p))

    files = sorted((p for p in SOURCES.rglob("*") if p.is_file()), key=canonical_first)
    print(f"inventorying {len(files)} files under sources/ ...")

    for p in files:
        # An interrupted transfer once left a 0-byte PDF in sources/, and it was
        # catalogued as a real document with a fingerprint. An empty file is
        # always an error, never a source.
        if p.stat().st_size == 0:
            sys.exit(f"EMPTY FILE in sources/ — an interrupted download? {p}")
        digest = sha256_file(p)
        rel = str(p.relative_to(SOURCES))
        if digest in by_hash:
            by_hash[digest]["duplicate_paths"].append(rel)
            continue

        ext = p.suffix.lower().lstrip(".")
        category = next((c for hint, c in CATEGORY_HINTS if hint in rel), "other")
        doc = {
            "id": slugify(p.name),
            "filename": p.name,
            "archive_path": rel,
            "duplicate_paths": [],
            "format": ext,
            "bytes": p.stat().st_size,
            "sha256": digest,
            "category": category,
            "fiscal_year": fiscal_year_from_text(p.name),
            "jurisdiction": jurisdiction_for(rel),
            # Filled in by a maintainer; the canonical public URL on the
            # issuing government's own site is stronger provenance than a
            # copy we host. See docs/PROVENANCE.md.
            "official_url": None,
        }
        if ext == "pdf":
            doc.update(classify_pdf(p))
            trust = doc["text_layer"] == "digital"
            doc["values_extractable"] = trust
            if not trust:
                doc["extraction_warning"] = (
                    "Scanned pages with an unreliable OCR text layer. Digits are "
                    "transposed by the embedded text (e.g. 4,610,003 reads as "
                    "460,100,3). Values must be transcribed from the rendered "
                    "page image, never parsed from this file's text."
                )
        else:
            doc["values_extractable"] = ext in {"xlsx", "xls"}

        by_hash[digest] = doc
        order.append(digest)

    docs = [by_hash[h] for h in order]

    # id collisions would break Fact -> document joins
    seen: dict[str, int] = defaultdict(int)
    for d in docs:
        seen[d["id"]] += 1
        if seen[d["id"]] > 1:
            d["id"] = f"{d['id']}-{seen[d['id']]}"

    dupes = sum(len(d["duplicate_paths"]) for d in docs)
    scans = [d for d in docs if d.get("text_layer") == "scan"]
    digital = [d for d in docs if d.get("text_layer") == "digital"]

    write_json(DATASETS / "documents.json", {
        "generated_by": "etl/s00_manifest.py",
        "summary": {
            "unique_documents": len(docs),
            "duplicate_copies_in_archive": dupes,
            "total_bytes": sum(d["bytes"] for d in docs),
            "pdf_digital_text": len(digital),
            "pdf_scanned_ocr": len(scans),
            "oversize_for_github": [d["filename"] for d in docs
                                    if d["bytes"] > 100 * 1024 * 1024],
        },
        "documents": docs,
    })

    print(f"\n  {len(docs)} unique documents ({dupes} duplicate copies collapsed)")
    print(f"  {len(digital)} PDFs with trustworthy digital text")
    print(f"  {len(scans)} PDFs are scans -> values require transcription:")
    for d in scans:
        print(f"      {d['filename']}")


if __name__ == "__main__":
    main()
