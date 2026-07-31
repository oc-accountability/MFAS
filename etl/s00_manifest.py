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
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATA, DATASETS, SOURCES, sha256_file, write_json,  # noqa: E402
                    read_json, fiscal_year_from_text)

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


INITIATIVE = "Orange County Efficiency & Accountability Initiative"

# Jurisdiction -> (Organization_ID, authority). EXPLICIT, never inferred from a
# substring. The export used to decide the owner with `"ORG_OC" if "Orange" in
# jurisdiction else "ORG_HB"`, which labelled all ten of the initiative's OWN
# documents as Orange County government publications, and — once Chapel Hill
# arrived — labelled all thirteen Chapel Hill files as Town of Hillsborough,
# because "Chapel Hill" does not contain the word "Orange". Twenty-three source
# rows in a published workbook claimed the wrong government. A table is not
# clever, and that is the point.
#
# `authority` answers a different question from `values_extractable`: who PUBLISHED
# this, not whether a machine can read it. Readability is not authority — an
# initiative spreadsheet is perfectly machine-readable and is not a government
# record.
ORG_BY_JURISDICTION = {
    "Town of Hillsborough, NC": ("ORG_HB", "government"),
    "Orange County, NC": ("ORG_OC", "government"),
    "Town of Chapel Hill, NC": ("ORG_CH", "government"),
    "Town of Carrboro, NC": ("ORG_CB", "government"),
    "City of Mebane, NC": ("ORG_MB", "government"),
    INITIATIVE: ("ORG_INIT", "initiative"),
}

# Tracked, hand-editable, keyed by FULL sha256. Solves two problems at once:
#
#   * Document IDs were derived from filenames and collisions were resolved by
#     appending a number in archive traversal order, so adding a same-named file
#     in an earlier-sorting directory could hand the unsuffixed ID to different
#     bytes while every published fact kept citing that string.
#   * Every rebuild rewrote `official_url` to None, silently erasing the exact
#     contribution docs/PROVENANCE.md asks maintainers to make.
#
# The registry is the memory that survives a rebuild. s00 only ADDS to it and
# never clobbers a value someone typed.
REGISTRY_PATH = DATA / "source_registry.json"


def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return read_json(REGISTRY_PATH).get("sources", {})
    return {}


ANNUAL_REPORT = re.compile(r"CAFR|ACFR|Annual\s+(Comprehensive\s+)?Financial|Audit", re.I)


def report_fiscal_year(filename: str) -> int | None:
    """The fiscal year a document covers, including the shapes the generic parser misses.

    `fiscal_year_from_text` handles "FY2027", "June 30, 2027" and "Fiscal Year 2027".
    It returns None for two filename styles the town actually uses, and both mattered:

      * `CAFR_Issued_TOH_FY2019.pdf` — the underscore before FY is a WORD character,
        so the `\\bFY` boundary never matches.
      * `Audit 2019.pdf` — a bare year with no marker at all.

    A null year is not cosmetic here. It is what let two scans of the same report
    escape deduplication, and what left the recognition path with figures the
    ground-truth check could not match to any year — so the check reported
    "not measurable" when the data to measure was sitting right there.

    The bare-year fallback is deliberately scoped to annual reports. A four-digit
    number in an arbitrary filename is not a fiscal year, and guessing one would put a
    figure in the wrong year, which is worse than having no year at all.
    """
    fy = fiscal_year_from_text(filename)
    if fy:
        return fy
    m = re.search(r"FY[\s_]?(\d{4})|FY[\s_]?(\d{2})(?!\d)", filename, re.I)
    if m:
        raw = int(m.group(1) or m.group(2))
        return raw if raw > 99 else 2000 + raw
    if ANNUAL_REPORT.search(filename):
        m = re.search(r"\b(20\d{2})\b", filename)
        if m:
            return int(m.group(1))
    return None


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

    # OTHER MUNICIPALITIES ARE TESTED FIRST, AND THE ORDER IS LOAD-BEARING.
    # Chapel Hill, Carrboro and Mebane are all IN Orange County, so their annual
    # reports name the county on nearly every page — testing the county first would
    # file every Chapel Hill document as a county document. Amy reserved ORG_CH,
    # ORG_CB and ORG_MB in her design before any of their data existed; all three are
    # handled here so the next folder to arrive is catalogued correctly on the first
    # run rather than after someone notices.
    #
    # Without this, the thirteen Chapel Hill files she uploaded on 2026-07-30 were
    # catalogued as the INITIATIVE's own working papers — the same bucket as her
    # design manual — because their filenames ("2023-2024-annual-comprehensive-
    # financial-report.pdf") name no government at all.
    for pattern, name in ((r"chapel[ _]?hill|\bCHCCS\b", "Town of Chapel Hill, NC"),
                          (r"\bcarrboro\b", "Town of Carrboro, NC"),
                          (r"\bmebane\b", "City of Mebane, NC")):
        if re.search(pattern, blob, re.I):
            return name

    county = bool(re.search(r"orange[ _]?county|\bOC\b", blob, re.I))
    town = bool(re.search(r"Hillsborough", blob, re.I))
    if county and not town:
        return "Orange County, NC"
    if town and not county:
        return "Town of Hillsborough, NC"
    return INITIATIVE


def main() -> None:
    registry = load_registry()
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
        jur = jurisdiction_for(rel)
        org, authority = ORG_BY_JURISDICTION.get(jur, ("ORG_UNKNOWN", "unknown"))
        known = registry.get(digest, {})
        doc = {
            # The registry's ID wins, because it is keyed by content: the same
            # bytes keep the same ID forever, whatever the file is renamed to.
            "id": known.get("id") or slugify(p.name),
            "filename": p.name,
            "archive_path": rel,
            "duplicate_paths": [],
            "format": ext,
            "bytes": p.stat().st_size,
            "sha256": digest,
            "category": category,
            "fiscal_year": report_fiscal_year(p.name),
            "jurisdiction": jur,
            "organization_id": known.get("organization_id") or org,
            # WHO PUBLISHED IT, not whether it can be parsed. Downstream confidence
            # is derived from this, so a readable initiative workbook can never be
            # presented with the standing of a government record.
            "source_authority": known.get("source_authority") or authority,
            # Filled in by a maintainer; the canonical public URL on the
            # issuing government's own site is stronger provenance than a
            # copy we host. See docs/PROVENANCE.md. Preserved across rebuilds
            # via the registry — this line used to reset it to None every run.
            "official_url": known.get("official_url"),
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

    # ---- ID assignment: stable, content-keyed, and loud on collision ---------
    # The old rule appended a counter in traversal order, so dropping another
    # file of the same name into an earlier-sorting folder could silently move
    # the unsuffixed ID onto different bytes while every published fact went on
    # citing that string. An ID must mean one document forever.
    claimed = {v["id"]: h for h, v in registry.items() if v.get("id")}
    for d in docs:
        h = d["sha256"]
        if registry.get(h, {}).get("id"):
            continue                       # already registered: keep its ID
        base, n = d["id"], 1
        while d["id"] in claimed and claimed[d["id"]] != h:
            owner = claimed[d["id"]]
            if owner in {x["sha256"] for x in docs}:
                # Two documents in THIS archive want the same ID. Suffix the
                # newcomer — the registered one keeps what it already had.
                n += 1
                d["id"] = f"{base}-{n}"
            else:
                sys.exit(
                    f"ID COLLISION: {d['filename']} wants id {d['id']!r}, which the "
                    f"source registry already assigns to sha256 {owner[:16]}… . "
                    f"That other document is not in this archive, so the ID would "
                    f"silently change meaning. Assign an explicit id in "
                    f"{REGISTRY_PATH.name} before rebuilding.")
        claimed[d["id"]] = h

    # Grow the registry with anything new; never clobber a hand-entered value.
    for d in docs:
        entry = registry.setdefault(d["sha256"], {})
        entry.setdefault("id", d["id"])
        entry.setdefault("filename", d["filename"])
        entry.setdefault("organization_id", d["organization_id"])
        entry.setdefault("source_authority", d["source_authority"])
        entry.setdefault("official_url", None)
    write_json(REGISTRY_PATH, {
        "generated_by": "etl/s00_manifest.py (append-only; hand-editable)",
        "what_this_is": (
            "The durable identity of every source document, keyed by full sha256. "
            "IDs assigned here are permanent: the same bytes keep the same ID no "
            "matter how the file is renamed or where it moves. official_url, "
            "organization_id and source_authority are yours to edit — a rebuild "
            "adds new entries and never overwrites what you typed."),
        "sources": dict(sorted(registry.items(), key=lambda kv: kv[1].get("id", ""))),
    })

    unknown = [d["id"] for d in docs if d["organization_id"] == "ORG_UNKNOWN"]
    if unknown:
        sys.exit(f"{len(unknown)} document(s) have no organization mapping — add the "
                 f"jurisdiction to ORG_BY_JURISDICTION: {unknown[:5]}")

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
