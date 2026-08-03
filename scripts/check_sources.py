#!/usr/bin/env python3
"""Which of the archive's 118 documents are on THIS machine, and which are not.

WHY THIS EXISTS
---------------
The 945 MiB of source documents are not in the repository — one file exceeds GitHub's
per-file limit and several were sent privately rather than published. So a fresh clone
ships the recipe and the operator supplies the ingredients, and until now the only way to
find out whether the ingredients were complete was to run the whole 15-minute rebuild and
read what it could not find.

That is the wrong shape for the person this project was handed to. "Did I get everything?"
should be a question you can answer in ten seconds, before you start, and the answer should
be a list of filenames rather than a number.

WHAT IT MEASURES, AND WHAT IT REFUSES TO
----------------------------------------
Documents are matched by **sha256 of their contents**, never by filename, size or path.
That is not fussiness — it is the rule the rest of this pipeline already runs on, and it
has been paid for twice:

  * Three "new" files the town sent turned out to be byte-identical to files already held.
    Their names were different. Only the hash said so.
  * Two files in Drive named "…Audit Report from Treasurer.pdf" are byte-identical to two
    already in the archive under completely different names — so a name-based check would
    have reported four documents where there are two.

A file whose bytes we have never seen is reported as EXTRA rather than ignored. It is
usually a newer revision of something, and that is worth knowing.

    python3 scripts/check_sources.py            # human-readable
    python3 scripts/check_sources.py --json     # for an assistant to read
    python3 scripts/check_sources.py --sources /some/other/path
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "data" / "acquisition_manifest.json"
CHUNK = 1 << 20


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n / 1:,.1f} {unit}"
        n /= 1024
    return f"{n} B"


def size(n: int) -> str:
    for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sources", default=str(REPO / "sources"),
                    help="the folder your documents are in (default: sources/)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if not MANIFEST.exists():
        print(f"missing {MANIFEST} — run `make etl` once, or pull a build that has it",
              file=sys.stderr)
        return 2
    man = json.loads(MANIFEST.read_text())
    wanted = {d["sha256"]: d for d in man["documents"]}

    root = Path(args.sources)
    if not root.exists():
        print(f"\n  There is no folder at {root}.\n"
              f"  Your documents go there — see docs/START_HERE_AMY.md, section 4.\n")
        return 1

    seen: dict[str, list[Path]] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        seen.setdefault(sha256(p), []).append(p)

    present = [wanted[h] for h in wanted if h in seen]
    missing = [wanted[h] for h in wanted if h not in seen]
    extra = [(h, paths) for h, paths in seen.items() if h not in wanted]

    if args.json:
        print(json.dumps({
            "sources_root": str(root),
            "documents_expected": len(wanted),
            "documents_present": len(present),
            "documents_missing": len(missing),
            "files_not_in_the_manifest": len(extra),
            "missing": [
                {"filename": d["filename"], "sha256": d["sha256"], "bytes": d["bytes"],
                 "issuing_authority": d["issuing_authority"], "fiscal_year": d["fiscal_year"],
                 "retrieval_status": d["retrieval"]["status"],
                 "official_url": d["retrieval"]["official_url"]}
                for d in sorted(missing, key=lambda x: -x["bytes"])],
            "not_in_the_manifest": [
                {"path": str(p.relative_to(root)), "sha256": h, "bytes": p.stat().st_size}
                for h, ps in extra for p in ps],
        }, indent=2))
        return 0 if not missing else 1

    print(f"\n  Looking in: {root}")
    print(f"  {len(present)} of {len(wanted)} documents are here.\n")

    if missing:
        total = sum(d["bytes"] for d in missing)
        print(f"  MISSING — {len(missing)} document(s), {size(total)}:\n")
        for d in sorted(missing, key=lambda x: -x["bytes"]):
            fy = f"FY{d['fiscal_year']}" if d["fiscal_year"] else "  —  "
            print(f"    {size(d['bytes']):>9}  {fy}  {d['filename']}")
            print(f"               {d['issuing_authority']}")
            url = d["retrieval"]["official_url"]
            if url:
                print(f"               published at: {url}")
            elif d["retrieval"]["status"] == "supplied_on_request":
                print(f"               sent privately — no public address; ask whoever sent it")
            elif d["retrieval"]["status"] == "authored_by_the_initiative":
                print(f"               one of your own files")
            else:
                print(f"               no public address recorded yet — see docs/SOURCES.md")
        print()
        print("  Nothing is guessed to fill these in. The figures that would have come")
        print("  from them are simply not published, and docs/COVERAGE.md will say so.\n")
    else:
        print("  Nothing is missing.\n")

    if extra:
        n = sum(len(ps) for _, ps in extra)
        print(f"  {n} file(s) here are not in the manifest. Usually that means a newer")
        print(f"  revision of something, or a file that arrived after the last build:\n")
        for h, ps in sorted(extra, key=lambda x: -x[1][0].stat().st_size)[:12]:
            p = ps[0]
            print(f"    {size(p.stat().st_size):>9}  {p.relative_to(root)}")
        if len(extra) > 12:
            print(f"    … and {len(extra) - 12} more")
        print()

    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
