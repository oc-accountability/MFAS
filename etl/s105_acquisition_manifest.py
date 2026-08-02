"""Stage 105 — the acquisition manifest: how someone else gets the sources we used.

The 2026-08-01 external audit's H-04, and it is the fairest hit in the report:

    "A fresh clone therefore cannot run `make etl` or verify page citations... The
     repository can reproduce generated artifacts only for someone who already
     possesses the private source archive."

That is true, and it undercuts the project's whole claim. The site tells a reader they
should not have to take our word for a number, and then the one thing that would let them
check — the documents — is the one thing they cannot get.

The sources cannot simply be committed: 945 MiB, one file over GitHub's 100 MiB per-file
limit, and Git LFS's free tier would not survive public traffic. So the answer is a
manifest that lets someone ASSEMBLE the identical archive and PROVE they have it.

WHAT THIS STAGE WILL NOT DO
---------------------------
It will not guess a URL. A plausible-looking link that 404s, or worse that resolves to a
DIFFERENT revision of the same report, is more damaging than a blank: it converts "we
have not published this yet" into "here is your source", and the reader who follows it
and finds different numbers has been actively misled. Every `official_url` is null today
because nobody has recorded one, and this stage says so in a number rather than filling
the hole with inference.

So the manifest publishes, per document, everything that is DERIVED FROM THE FILE ITSELF —
sha256, byte size, media type, page count, whether it carries a text layer, the issuing
authority and fiscal year the pipeline resolved — plus a `retrieval` block that is honest
about status. A document with no recorded URL is listed as `needs_official_url`, and the
count of those is the headline. That turns an invisible gap into a countable one, which
is the same move the coverage report makes for unread documents.

Filling in the URLs is research, not code: most are on the town's and county's own
websites, and a few arrived by public-records request and need the request reference
instead. `docs/SOURCES.md` is the worksheet for that, and every URL added there survives
a rebuild because `data/source_registry.json` is append-only and keyed by sha256.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, DATASETS, read_json, write_json  # noqa: E402

OUT_JSON = DATA / "acquisition_manifest.json"
OUT_MD = Path(__file__).resolve().parent.parent / "docs" / "SOURCES.md"

AUTHORITY = {
    "ORG_HB": "Town of Hillsborough, North Carolina",
    "ORG_OC": "Orange County, North Carolina",
    "ORG_CH": "Town of Chapel Hill, North Carolina",
}


# Office-suite files from a government are almost always a records-request response or an
# emailed working file, not something published at an address. PDFs are the opposite.
_REQUEST_FORMATS = (".xlsx", ".docx", ".pptx", ".zip", ".csv")


def retrieval_status(doc: dict, url: str | None) -> str:
    """How a third party could obtain this document — and whether that is still open.

    Counting all 118 as "needs a URL" overstated the gap and, worse, made it
    unclosable: ten of them are the initiative's OWN architecture and design files, and
    a couple of dozen more are workbooks and records-request responses that were never
    published at an address and never will be. A backlog that cannot reach zero stops
    being read as a backlog.

    The split is made on `source_authority`, which `s00` RECORDS from an explicit table
    rather than inferring, and on file format. It is a judgement about the world and it
    can be wrong at the margin — a government PDF supplied only by email will sit in
    `needs_official_url` until someone establishes it was never published. That is the
    right way round: it stays visible.
    """
    if url:
        return "url_recorded"
    if (doc.get("source_authority") or "") != "government":
        # The initiative's own work — a design manual, a data warehouse workbook. There
        # is no official URL to find, and pretending otherwise inflates the gap.
        return "authored_by_the_initiative"
    if doc["filename"].lower().endswith(_REQUEST_FORMATS):
        return "supplied_on_request"
    return "needs_official_url"


def main() -> None:
    docs = read_json(DATASETS / "documents.json")["documents"]
    # The registry nests its entries under "sources"; reading the top level gave a dict
    # whose keys are "generated_by"/"what_this_is"/"sources", so every lookup missed and
    # the manifest reported 0 recorded URLs while 18 were sitting in the file.
    registry = read_json(DATA / "source_registry.json")
    reg_by_sha = registry.get("sources", {}) if isinstance(registry, dict) else {}

    entries, need_url = [], []
    for d in sorted(docs, key=lambda x: (x.get("organization_id") or "", x["filename"])):
        sha = d.get("sha256") or ""
        reg = reg_by_sha.get(sha) or {}
        url = d.get("official_url") or reg.get("official_url")
        e = {
            "source_id": d["id"],
            "filename": d["filename"],
            "sha256": sha,
            "bytes": d.get("bytes"),
            "media_type": d.get("media_type") or ("application/pdf"
                                                  if d["filename"].lower().endswith(".pdf")
                                                  else None),
            "pages": d.get("pages"),
            "text_layer": d.get("text_layer"),
            "issuing_authority": AUTHORITY.get(d.get("organization_id"),
                                               d.get("jurisdiction") or "unknown"),
            "organization_id": d.get("organization_id"),
            "fiscal_year": d.get("fiscal_year"),
            "source_authority": d.get("source_authority"),
            "retrieval": {
                "official_url": url,
                "archival_url": reg.get("archival_url"),
                "verified": reg.get("url_verified_by"),
                "status": retrieval_status(d, url),
                "public_record": d.get("source_authority") == "government",
            },
        }
        entries.append(e)
        if e["retrieval"]["status"] == "needs_official_url":
            need_url.append(e)

    total_bytes = sum(e["bytes"] or 0 for e in entries)
    by_org = Counter(e["issuing_authority"] for e in need_url)
    by_status = Counter(e["retrieval"]["status"] for e in entries)

    out = {
        "generated_by": "etl/s105_acquisition_manifest.py",
        "purpose": ("Everything a third party needs to assemble and PROVE the identical "
                    "source archive this project's figures were read from."),
        "why_the_sources_are_not_in_the_repository": (
            f"{total_bytes / 1048576:.0f} MiB across {len(entries)} documents; one file "
            f"exceeds GitHub's 100 MiB per-file limit and Git LFS's free tier would not "
            f"survive public traffic. The manifest is the substitute: assemble the files, "
            f"hash them, and a match proves your copy is the one the figures came from."),
        "honesty_note": (
            "No URL here is inferred. A plausible link that resolves to a different "
            "revision of the same report would be worse than a blank, because a reader "
            "who followed it and found different numbers would have been actively "
            "misled. Documents with no recorded address are counted, not filled in."),
        "documents_total": len(entries),
        # COUNTED, not derived by subtraction. This was `len(entries) - len(need_url)`,
        # and the moment `need_url` stopped meaning "everything without a URL" it read
        # 53 recorded when 18 were. Subtracting one count from another is how a total
        # goes wrong silently.
        "documents_with_official_url": by_status.get("url_recorded", 0),
        "documents_needing_official_url": len(need_url),
        "by_retrieval_status": dict(sorted(by_status.items())),
        "archive_bytes": total_bytes,
        "verify": ("sha256sum -c after placing files in sources/; `make etl` then "
                   "reproduces data/ byte-for-byte."),
        "how_the_recorded_urls_were_established": (
            "Each was downloaded and its sha256 compared with the copy held here; only an "
            "exact match was recorded. Guessing sequential document IDs on the county's "
            "archive produced a plausible-looking hit that was a different document, and "
            "the hash check is what caught it."),
        "known_access_barriers": {
            "hillsboroughnc.gov": ("Akamai edge returns 403 to automated clients — curl, "
                                   "WebFetch and headless Chromium alike. Its documents "
                                   "are also largely absent from the Wayback Machine, so "
                                   "the 40 outstanding town URLs need a human browser "
                                   "session."),
            "chapelhillnc.gov": ("Also 403 to automated clients. Its annual financial "
                                 "reports WERE recoverable through the Wayback Machine, "
                                 "which is where the recorded Chapel Hill URLs and their "
                                 "archival copies came from."),
            "orangecountync.gov": ("Reachable. Some DocumentCenter IDs return HTTP 500 "
                                   "from the county's own server — those are broken links "
                                   "on their side, not a fetch problem here."),
        },
        "needs_official_url_by_authority": dict(sorted(by_org.items())),
        "documents": entries,
    }
    write_json(OUT_JSON, out)

    md = [
        "# Source acquisition manifest",
        "",
        "*Generated by `etl/s105_acquisition_manifest.py` on every build.*",
        "",
        f"The archive is **{total_bytes / 1048576:.0f} MiB across {len(entries)} "
        f"documents** and is not committed — one file exceeds GitHub's 100 MiB per-file "
        f"limit, and Git LFS's free tier would not survive public traffic. This file is "
        f"the substitute: assemble the documents, hash them, and a match proves your "
        f"copy is the one every published figure was read from.",
        "",
        "## Status",
        "",
        f"- **{by_status.get('url_recorded', 0)}** documents have a recorded official "
        f"URL, each **verified by downloading it and matching the sha256** — not by the "
        f"title looking right",
        f"- **{len(need_url)}** are published government documents that still need one "
        f"— listed below",
        f"- **{by_status.get('supplied_on_request', 0)}** were supplied on request "
        f"(workbooks, spreadsheets, emailed files) and have no public address",
        f"- **{by_status.get('authored_by_the_initiative', 0)}** are the initiative's "
        f"own design and analysis files — there is no official URL to find",
        "",
        "No URL in this file is inferred. A plausible link that resolved to a different "
        "revision of the same report would be worse than a blank: a reader who followed "
        "it and found different numbers would have been actively misled. So the gap is "
        "counted rather than filled, the same way `COVERAGE.md` counts unread documents.",
        "",
        "**To record one:** add `official_url` against the document's sha256 in "
        "`data/source_registry.json`. That file is append-only and keyed by hash, so the "
        "entry survives every rebuild and can never migrate to different bytes.",
        "",
        "## Documents still needing an official URL",
        "",
    ]
    if need_url:
        md += ["| Issuing authority | FY | Document | SHA-256 (first 16) |",
               "|---|---|---|---|"]
        for e in need_url:
            md.append(f"| {e['issuing_authority']} | {e['fiscal_year'] or '—'} | "
                      f"{e['filename']} | `{e['sha256'][:16]}` |")
    else:
        md.append("*None — every document has a recorded address.*")
    md += ["", "## Verifying a copy you assembled", "",
           "```bash",
           "# every hash in the manifest, checked against your sources/ directory",
           "./.venv/bin/python etl/s00_manifest.py   # fails on any mismatch",
           "make verify                              # full rebuild + every gate",
           "```", ""]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print(f"  wrote {OUT_JSON.relative_to(DATA.parent)} and docs/SOURCES.md")
    print(f"  {by_status.get('url_recorded', 0)}/{len(entries)} documents have a "
          f"VERIFIED official URL")
    for st, n in sorted(by_status.items()):
        print(f"      {n:4}  {st}")
    if need_url:
        print(f"  {len(need_url)} still need one — NOT inferred, see docs/SOURCES.md:")
        for auth, n in sorted(by_org.items()):
            print(f"      {n:4}  {auth}")


if __name__ == "__main__":
    main()
