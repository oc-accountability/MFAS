"""Shared helpers for the MFAS (Municipal Financial Analysis System) ETL.

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
import io
import json
import re
import os
import sys
from dataclasses import dataclass, asdict
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


def report_and_gate(stage: str, problems, checks=None, *, info_ok=()) -> None:
    """Print a stage's diagnostics and EXIT NONZERO if any of them are real failures.

    Every extraction stage used to collect its misses and failed cross-checks, write
    them into JSON, print them, and exit 0. The documented rebuild command therefore
    succeeded while publishing partial or inconsistent data, and only the separate
    `make test` target — which `make etl` never ran — would have caught it. A gate
    that cannot fail is a log line.

    The distinction that makes this usable: a problem line beginning `INFO` is a
    deliberate, known observation (a document that legitimately has no appendix, a
    template note), and anything else is a defect. `info_ok` additionally allows exact
    substrings for known-benign conditions, so an allowlist entry is a decision
    someone wrote down rather than a silently swallowed message.
    """
    problems = list(problems or [])
    checks = list(checks or [])
    failed = [c for c in checks
              if c.get("agree") is False or c.get("agree_within_5pct") is False
              or c.get("reconciles") is False]
    # The project's existing convention puts the marker AFTER the document id
    # ("fiscal-year-2025-budget-message: INFO no … table in this document"), so match
    # the word anywhere rather than only at the start.
    real = [p for p in problems
            if not re.search(r"\bINFO\b", str(p))
            and not any(tok in str(p) for tok in info_ok)]

    for c in checks:
        ok = c.get("agree", c.get("agree_within_5pct", c.get("reconciles")))
        print(f"  check {c.get('check', '?')}: {'OK' if ok else 'FAILED'}")
    for p in problems:
        print(f"      {p}")

    if real or failed:
        print(f"\n{stage} FAILED — {len(real)} extraction problem(s), "
              f"{len(failed)} failed consistency check(s).")
        for x in (real + [str(c) for c in failed])[:20]:
            print(f"   {x}")
        sys.exit(1)


def content_cache_dir(kind: str, sha256: str, extractor: str,
                      version: str = "1", **options) -> Path:
    """A cache directory bound to the source's CONTENT, not its name.

    Every extraction cache in this project used to be keyed on some combination of
    document id, filename stem, file size and mtime. All of those describe the
    *slot* a document occupies rather than the document, so replacing a PDF under
    the same name — exactly what happens when a government re-issues a corrected
    report, or when a scan is upgraded to a digital original — could leave the
    manifest recording the NEW sha256 while OCR text, page text and project
    extraction silently came from the OLD file. That severs the fact-to-source
    chain the whole project is built on, and a routine resumable `make etl` was
    enough to trigger it.

    The namespace therefore contains the full source hash plus the extractor's
    name, version and options, and a `_meta.json` records them. A cache hit is
    only honoured when that metadata matches; anything else is treated as a miss
    and rebuilt. Copying a stale directory in cannot fool it.
    """
    opt = "-".join(f"{k}={v}" for k, v in sorted(options.items()))
    tag = hashlib.sha256(f"{extractor}|{version}|{opt}".encode()).hexdigest()[:8]
    d = BUILD / kind / f"{sha256[:16]}-{tag}"
    meta = d / "_meta.json"
    want = {"sha256": sha256, "extractor": extractor, "version": version,
            "options": {k: str(v) for k, v in sorted(options.items())}}
    if meta.exists():
        try:
            if json.loads(meta.read_text(encoding="utf-8")) == want:
                return d
        except Exception:
            pass
        # Metadata missing or mismatched: the directory cannot be trusted.
        for f in d.glob("*"):
            f.unlink()
    d.mkdir(parents=True, exist_ok=True)
    meta.write_text(json.dumps(want, indent=2, sort_keys=True), encoding="utf-8")
    return d


def build_stamp() -> str:
    """What generated this file — a property of the DATA, not of the day you ran it.

    `date.today()` in a generated workbook means identical inputs produce different
    cells on different days, which contradicts docs/PROVENANCE.md's instruction to
    expect a clean `git diff --stat data/` after a rebuild: the rebuild always
    dirtied the exports, so the one signal that would reveal a real change was
    permanently noisy.

    Two honest options, and NOT a third. Set `MFAS_BUILD_DATE` for a dated release
    and that wins. Otherwise this returns a short digest of the source set, which is
    stable across machines and across days and changes exactly when the sources do.

    The third option — deriving a date from source file mtimes — was written first and
    is wrong for the same reason half this audit was: an mtime describes the copy, not
    the document. Cloning the archive or restoring it from a backup changes every
    mtime without changing a single figure. Do not reintroduce it.
    """
    override = os.environ.get("MFAS_BUILD_DATE")
    if override:
        return override
    try:
        docs = read_json(DATASETS / "documents.json")["documents"]
        digest = hashlib.sha256(
            "".join(sorted(d["sha256"] for d in docs)).encode()).hexdigest()[:12]
        return f"source-set {digest}"
    except Exception:
        return "unknown"


def normalise_xlsx(path: Path) -> None:
    """Rewrite an .xlsx with fixed ZIP member timestamps so rebuilds are byte-identical.

    An .xlsx is a ZIP, and OpenPyXL stamps every member with the wall-clock time of
    the save. So even after the *cells* were made deterministic, two rebuilds of
    identical data still produced different bytes — which keeps
    `git diff --stat data/` permanently dirty and destroys the one signal that would
    reveal a real change. docs/PROVENANCE.md promises a clean diff after a rebuild;
    this is what makes that true rather than aspirational.

    1980-01-01 is the ZIP format's own epoch — the earliest value it can store — and
    is the conventional choice for reproducible archives.

    There are TWO clocks in an .xlsx and fixing only the obvious one achieves nothing:
    the ZIP member timestamps, and `docProps/core.xml`, into which OpenPyXL writes
    `<dcterms:created>` and `<dcterms:modified>` as the current instant. Normalising
    the ZIP alone still produced different bytes on every run.
    """
    import zipfile
    epoch = "1980-01-01T00:00:00Z"
    src = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(src)) as zin:
        items = [(i, zin.read(i.filename)) for i in zin.infolist()]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in items:
            if info.filename == "docProps/core.xml":
                text = data.decode("utf-8")
                text = re.sub(r"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:)",
                              rf"\g<1>{epoch}\g<2>", text)
                data = text.encode("utf-8")
            fixed = zipfile.ZipInfo(info.filename, date_time=(1980, 1, 1, 0, 0, 0))
            fixed.compress_type = info.compress_type
            fixed.external_attr = info.external_attr
            zout.writestr(fixed, data)
    path.write_bytes(buf.getvalue())


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


def doc_id_for_filename(filename: str) -> str | None:
    """Resolve a source filename to its manifest document id.

    The workbook-import stages historically recorded provenance as a bare
    filename ('imported_from'), which no machine could join back to the
    manifest — so the documents those figures trace to were invisible to any
    citation count. Returns None rather than guessing; callers must treat a
    None as a problem to report, not to swallow.
    """
    docs = read_json(DATASETS / "documents.json")["documents"]
    for d in docs:
        if d["filename"] == filename:
            return d["id"]
    return None
