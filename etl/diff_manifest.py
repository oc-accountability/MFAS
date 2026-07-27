"""Compare the source archive against the last committed manifest.

Run this after replacing `sources/` and re-running `s00_manifest.py`, BEFORE
trusting anything downstream.

Why it exists: a document can be **amended in place** — same filename, different
contents. Nothing about that is visible in a folder listing, and the site would go
on citing "FY27 Budget Message, page 1" for a figure that page may no longer
contain. Filenames lie; hashes do not.

So this reports four things, and the third is the dangerous one:

    added      new documents, nothing to worry about
    removed    documents that vanished — anything citing them is now orphaned
    CHANGED    same name, different bytes — every figure quoted from them is
               suspect until re-extracted and re-checked
    unchanged  the boring majority

It exits non-zero if a changed or removed document is still cited by a published
figure, because that is the case where the site would be showing a number that its
own source no longer supports.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, REPO, read_json  # noqa: E402


def committed_manifest() -> dict | None:
    """The manifest as of the last commit, read from git rather than disk."""
    try:
        out = subprocess.run(
            ["git", "show", "HEAD:data/datasets/documents.json"],
            cwd=REPO, capture_output=True, text=True, check=True).stdout
        return json.loads(out)
    except Exception:
        return None


def main() -> None:
    old = committed_manifest()
    if old is None:
        print("  no committed manifest to compare against — treating everything as new")
        return
    new = read_json(DATASETS / "documents.json")

    o = {d["filename"]: d for d in old["documents"]}
    n = {d["filename"]: d for d in new["documents"]}

    added = sorted(set(n) - set(o))
    removed = sorted(set(o) - set(n))
    changed = sorted(f for f in set(o) & set(n) if o[f]["sha256"] != n[f]["sha256"])
    unchanged = len(set(o) & set(n)) - len(changed)

    print(f"  added:     {len(added)}")
    for f in added[:40]:
        print(f"      + {f}")
    print(f"  removed:   {len(removed)}")
    for f in removed:
        print(f"      - {f}")
    print(f"  CHANGED:   {len(changed)}   (same name, different contents)")
    for f in changed:
        print(f"      ~ {f}")
        print(f"          was {o[f]['sha256'][:16]}…  {o[f]['bytes']:,} bytes")
        print(f"          now {n[f]['sha256'][:16]}…  {n[f]['bytes']:,} bytes")
    print(f"  unchanged: {unchanged}")

    # Which published figures are now standing on moved ground?
    at_risk = {}
    suspect_ids = {o[f]["id"] for f in changed} | {o[f]["id"] for f in removed}
    facts_path = DATASETS / "facts.json"
    if facts_path.exists() and suspect_ids:
        for fact in read_json(facts_path)["facts"]:
            if fact.get("source_doc") in suspect_ids:
                at_risk.setdefault(fact["source_doc"], 0)
                at_risk[fact["source_doc"]] += 1

    report = {
        "generated_by": "etl/diff_manifest.py",
        "note": ("Filenames lie; hashes do not. A document amended in place keeps its name while "
                 "its contents move underneath every figure quoted from it."),
        "added": added, "removed": removed,
        "changed": [{"filename": f, "old_sha256": o[f]["sha256"], "new_sha256": n[f]["sha256"],
                     "old_bytes": o[f]["bytes"], "new_bytes": n[f]["bytes"]} for f in changed],
        "unchanged_count": unchanged,
        "published_figures_at_risk": at_risk,
    }
    (DATASETS / "manifest_diff.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\n  wrote data/datasets/manifest_diff.json")

    if at_risk:
        total = sum(at_risk.values())
        print(f"\n  {total} published figure(s) cite a document that changed or disappeared:")
        for doc, c in sorted(at_risk.items(), key=lambda x: -x[1]):
            print(f"      {c:4}  {doc}")
        sys.exit("\nSTOP — re-run the extraction stages and re-check these before publishing. "
                 "The site would otherwise cite a page that may no longer say what it said.")
    print("\n  no published figure depends on a changed or removed document")


if __name__ == "__main__":
    main()
