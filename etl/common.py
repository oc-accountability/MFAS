"""Shared helpers for the hoa-funds ETL.

Design rule that everything here exists to enforce: **no number reaches the
website without provenance.** Every observation carries the document it came
from, the page it was on, and how confident we are in the reading.

The reason this is not paranoia: several of the source PDFs are *scans with a
broken OCR text layer*. Their embedded text renders "4,610,003" as "460,100,3".
Any pipeline that trusts that text layer publishes wrong numbers about named
public officials. See docs/EXTRACTION_NOTES.md.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCES = REPO / "sources"
DATA = REPO / "data"
DATASETS = DATA / "datasets"
BUILD = REPO / "build"

# --- extraction confidence vocabulary -------------------------------------
# Used verbatim in the published JSON so a reader can filter on it.
DIGITAL = "digital-text"      # embedded font text, read directly. Reliable.
OCR = "ocr-unverified"        # from a scanned page's OCR layer. NOT reliable.
TRANSCRIBED = "transcribed"   # a human/vision read of the rendered page image.
DERIVED = "derived"           # computed by this ETL from other observations.
STATED = "stated"             # a figure a document asserts in prose.

# Recovered by character recognition from a scan, AND proven by the page itself:
# the individual lines add up exactly to the total printed beside them. Character
# recognition fails by altering a digit, and an altered digit breaks that sum — so
# unlike a bare OCR reading, this one cannot be silently wrong. Measured accuracy
# on these documents was 141/141 figures (etl/ocr_accuracy_probe.py), but the
# arithmetic check is what makes it publishable, not the measurement.
#
# A digital original still beats this and removes the need for it entirely; where
# one exists it is always used in preference to the scan.
OCR_VERIFIED = "ocr-arithmetic-verified"

TRUSTWORTHY = {DIGITAL, TRANSCRIBED, DERIVED, STATED, OCR_VERIFIED}


@dataclass
class Fact:
    """One observation. The atomic unit the website charts.

    Long/tidy format on purpose: the site pivots and aggregates in the browser,
    so adding a metric never requires a schema change or a new file.
    """
    jurisdiction: str          # "Town of Hillsborough" | "Orange County, NC"
    fiscal_year: int | None    # 2027 = FY2027 (year ending June 30, 2027)
    metric: str                # key into metrics.json
    value: float | None
    unit: str                  # "USD" | "USD_thousands" | "cents_per_100" | "ratio" | "count"
    basis: str = ""            # "actual" | "budget" | "recommended" | "projected" | "estimate"
    source_doc: str = ""       # document id in documents.json
    source_page: int | None = None   # 1-indexed PDF page
    source_detail: str = ""    # sheet name, table number, line label
    extraction: str = DIGITAL
    note: str = ""

    def as_row(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in ("", None) or k in ("value", "fiscal_year")}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_MONEY = re.compile(r"^\(?\$?\s*(-?[\d,]+(?:\.\d+)?)\s*\)?%?$")


def parse_money(s) -> float | None:
    """Parse '$1,234,567', '(1,234)' -> -1234, '51.3', '73%' -> 73.0.

    Returns None rather than guessing. A silent 0.0 would be a published lie.
    """
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip()
    if not t or t in {"-", "--", "n/a", "N/A", "TBD"}:
        return None
    neg = t.startswith("(") and t.endswith(")")
    m = _MONEY.match(t)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return -v if neg else v


def fiscal_year_from_text(s: str) -> int | None:
    """FY27 / FY2027 / 'Year Ended June 30, 2027' -> 2027."""
    if not s:
        return None
    m = re.search(r"June\s*30,?\s*(20\d{2})", s)
    if m:
        return int(m.group(1))
    m = re.search(r"\bFY\s?(20\d{2})\b", s, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"\bFY\s?(\d{2})\b", s, re.I)
    if m:
        return 2000 + int(m.group(1))
    m = re.search(r"Fiscal\s+Year\s+(20\d{2})", s, re.I)
    if m:
        return int(m.group(1))
    return None


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")
    print(f"  wrote {path.relative_to(REPO)}  ({path.stat().st_size:,} bytes)")


def read_json(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
