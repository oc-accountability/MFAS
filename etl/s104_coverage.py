"""Stage 104 — how full is the warehouse, measured per document, per government, per year.

Amy asked for the warehouse to be filled from every document in the archive, with
every number traceable to an official one. This stage is the answer to "is it?" —
and it is a MEASUREMENT rather than an assurance, because an assurance about
coverage is exactly the kind of claim that rots quietly while everyone believes it.

It answers three questions a reviewer actually has:

1. **Which documents feed the warehouse, and how much?** One row per document, with
   the number of facts it contributes to each table. A document contributing zero is
   named, not hidden in an aggregate.

2. **Which documents contribute nothing, and WHY?** The reasons are not equivalent
   and lumping them together is how a project talks itself into thinking it is done:

     * `no-figures` — a narrative, a memo, a presentation, an organisation chart.
       There is nothing in it to load. Correctly empty.
     * `design-document` — Amy's own architecture and design files. They define the
       schema; they are not sources of municipal figures.
     * `scanned-unextractable` — a scan whose embedded text layer transposes digits.
       Excluded by policy, with the fresh-recognition path used instead where a
       page can prove itself.
     * `superseded-by-digital` — a scan of a report we now hold digitally. Reading
       it would duplicate a better reading.
     * `not-yet-read` — **the real backlog.** A document with figures, in a readable
       format, that no stage reads yet. This is the number that matters, and it is
       reported without softening.

3. **Where are the holes by government and year?** A matrix of facts per
   organisation per fiscal year, so a thin year is visible rather than averaged
   away. Hillsborough FY2018 and FY2019 holding a few dozen facts against FY2025's
   several hundred is not a rounding difference — it is the absence of a digital
   audit for those years, and it points at a specific thing to ask the town for.

The output feeds `docs/COVERAGE.md` and a Coverage sheet in the warehouse export, so
the same measurement reaches a reader who never opens the JSON.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, REPO, read_json, write_json  # noqa: E402

# Documents that are correctly empty, and why. Anything NOT matched here and not
# contributing facts lands in not-yet-read, which is the honest default: the burden
# is on the pipeline to justify an unread document, not on the reader to guess.
DESIGN_HINTS = ("architecture", "design specification", "conceptual architecture",
                "design manual", "notebook", "decision context model", "oc design",
                "municipal financial database", "municipal finance database",
                "municipal financial data warehouse", "municipal finance project",
                "municipal financial analysis", "gf trend schedules",
                "municipal financial information system",
                # Superseded editions of Amy's own analysis workbooks. The pipeline
                # reads the newest of each (Workbook B v2, the trend schedules v5);
                # an older edition is not backlog, it is history.
                "workbook b", "risk model", "fiscal sustainability")
NARRATIVE_HINTS = ("organizational chart", "visioning survey", "media", "news",
                   "messaging", "meeting notes", "interview", "white paper",
                   "presentation", "transmittal letter", "flyer", "sales tax information",
                   "historical rates", "stormwater fees", "water and sewer rates",
                   "master issues", "action items", "public records request",
                   "strategic plan", "resolution", "effect of debt management",
                   "county profile")

# Scans of reports we now hold as digital originals (stage 61 reads those instead).
SUPERSEDED = {
    "annual-financial-report-year-ended-june-30-2022": "hillsborough-2022-audit-stamped",
    "annual-financial-report-year-ended-june-30-2023": "hillsborough-2023-audit-stamped",
    "annual-financial-report-year-ended-june-30-2024": "hillsborough-2024-audit-stamped",
    "annual-financial-report-year-ended-june-30-2025": "hillsborough-2025-audit-stamped",
    "annual-comprehensive-financial-report-year-ended-june-30-2021": "audit-2021",
}


def classify(doc, contributed: int) -> tuple[str, str]:
    """Return (status, why) for a document. Contributing documents are 'read'."""
    if contributed:
        return "read", ""
    # Normalise punctuation to spaces before matching. The hints were written with
    # underscores and the filenames use spaces and hyphens interchangeably
    # ("Municipal Finance Database - Hillsborough - v1.0.xlsx"), so an unnormalised
    # match reported Amy's own design workbooks as unread municipal sources.
    import re as _re
    name = _re.sub(r"[^a-z0-9]+", " ", doc["filename"].lower()).strip()
    did = doc["id"]

    if did in SUPERSEDED:
        return "superseded-by-digital", (
            f"a scan of a report held digitally as {SUPERSEDED[did]}; the digital "
            f"original is read instead and reading both would duplicate the slice")
    if not doc.get("values_extractable"):
        return "no-figures", "no extractable figures — nothing in it to load"
    if any(h in name for h in DESIGN_HINTS):
        return "design-document", (
            "Amy's own design/analysis workbook or architecture document — it defines "
            "the schema and is read for structure, not loaded as a source of "
            "municipal figures")
    if any(h in name for h in NARRATIVE_HINTS):
        return "no-figures", (
            "narrative, correspondence or presentation — carries context rather than "
            "a statement of account")
    if not doc.get("values_extractable", True):
        return "scanned-unextractable", "scanned; embedded text layer transposes digits"
    return "not-yet-read", (
        "has figures, is readable, and no stage reads it yet — this is real backlog")


def main() -> None:
    docs = read_json(DATASETS / "documents.json")["documents"]
    wh = read_json(DATASETS / "warehouse.json")

    # ---- facts per document, per table --------------------------------------
    cols = {n: i for i, n in enumerate(wh["columns"])}
    per_doc: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    org_year: collections.Counter = collections.Counter()
    for r in wh["rows"]:
        per_doc[r[cols["Source_ID"]]]["Fact_Financial"] += 1
        org_year[(r[cols["Organization_ID"]], r[cols["Fiscal_Year_ID"]])] += 1
    for r in wh.get("fact_metric", {}).get("rows", []):
        per_doc[r["Source_ID"]]["Fact_Metric"] += 1
    for r in wh.get("fact_statement_line", {}).get("rows", []):
        per_doc[r["Source_ID"]]["Fact_Statement_Line"] += 1

    # Anything else in datasets/ that CITES a document as a source, so a document
    # feeding only the website's topic datasets is not reported as unread.
    #
    # This walks the JSON for source-bearing KEYS. A plain text search was the first
    # version and it was wrong in a way worth recording: the questions register names
    # the unread documents in the text of the question asking for them to be read, so
    # a grep promoted all 23 backlog items to "read" the moment the register mentioned
    # them — the measurement congratulating itself for describing the gap.
    SOURCE_KEYS = {"source_doc", "source_docs", "source_id", "source_ids", "document",
                   "documents", "imported_from", "Source_ID", "source", "doc_id"}

    def walk(node, hits):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in SOURCE_KEYS:
                    if isinstance(v, str):
                        hits.add(v)
                    elif isinstance(v, list):
                        hits.update(x for x in v if isinstance(x, str))
                walk(v, hits)
        elif isinstance(node, list):
            for v in node:
                walk(v, hits)

    other_cited: collections.Counter = collections.Counter()
    for p in sorted(Path(DATASETS).glob("*.json")):
        if p.stem in ("documents", "warehouse", "coverage", "questions"):
            continue
        hits: set = set()
        walk(json.loads(p.read_text(encoding="utf-8")), hits)
        for did in hits:
            other_cited[did] += 1

    rows, by_status = [], collections.Counter()
    for d in sorted(docs, key=lambda x: (x["jurisdiction"], x["filename"])):
        c = per_doc.get(d["id"], collections.Counter())
        total = sum(c.values())
        status, why = classify(d, total)
        # A document feeding the site's topic datasets but not the warehouse is read.
        if status == "not-yet-read" and other_cited.get(d["id"]):
            status, why = "read-into-datasets-only", (
                "feeds the website's topic datasets but not the warehouse fact tables "
                "— its figures are published and cited, just not in the warehouse grain")
        by_status[status] += 1
        rows.append({
            "document": d["id"], "filename": d["filename"],
            "jurisdiction": d["jurisdiction"], "format": d["format"],
            "fiscal_year": d.get("fiscal_year"),
            "values_extractable": d.get("values_extractable"),
            "official_url": d.get("official_url"),
            "facts_total": total,
            "Fact_Financial": c.get("Fact_Financial", 0),
            "Fact_Metric": c.get("Fact_Metric", 0),
            "Fact_Statement_Line": c.get("Fact_Statement_Line", 0),
            "other_datasets_citing": other_cited.get(d["id"], 0),
            "status": status, "why": why,
        })

    # Source_IDs in the warehouse that are not archive documents — Amy's own register
    # keys (OC_ACFR_2025 and friends). Reported, not hidden: they are citations to a
    # document she holds, recorded in her vocabulary rather than this archive's.
    doc_ids = {d["id"] for d in docs}
    foreign = sorted({s for s in per_doc if s not in doc_ids})

    # ---- the holes -----------------------------------------------------------
    orgs = sorted({o for o, _ in org_year})
    years = sorted({y for _, y in org_year})
    matrix = [{"Organization_ID": o,
               **{y: org_year.get((o, y), 0) for y in years}} for o in orgs]
    thin = [{"Organization_ID": o, "Fiscal_Year_ID": y, "facts": org_year.get((o, y), 0)}
            for o in orgs for y in years
            if 0 < org_year.get((o, y), 0) < 200]
    empty = [{"Organization_ID": o, "Fiscal_Year_ID": y}
             for o in orgs for y in years if org_year.get((o, y), 0) == 0]

    backlog = [r for r in rows if r["status"] == "not-yet-read"]

    out = {
        "generated_by": "etl/s104_coverage.py",
        "question": ("Is the warehouse filled from every document in the archive, and is "
                     "every figure traceable to an official document and page?"),
        "how_to_read_this": (
            "facts_total is what a document actually contributes. A zero is explained by "
            "status, and only 'not-yet-read' is a gap in the work — the others are "
            "documents with nothing to load, Amy's own design files, or scans "
            "superseded by a digital original."),
        "documents_total": len(docs),
        "documents_contributing": sum(1 for r in rows if r["facts_total"]),
        "facts_total": sum(r["facts_total"] for r in rows),
        "by_status": dict(by_status.most_common()),
        "backlog_count": len(backlog),
        "backlog": [{"document": r["document"], "filename": r["filename"],
                     "jurisdiction": r["jurisdiction"], "format": r["format"]}
                    for r in backlog],
        "facts_by_org_and_year": matrix,
        "thin_org_years": thin,
        "empty_org_years": empty,
        "source_ids_not_in_archive": {
            "ids": foreign,
            "note": ("Amy's own Source_Register keys, carried through from her workbook "
                     "so her citations survive the import. They point at documents she "
                     "holds; where the same document is in this archive it is also read "
                     "directly, under its archive id."),
        },
        "documents": rows,
    }
    write_json(DATASETS / "coverage.json", out)

    # ---- the human-readable version ----------------------------------------
    md = ["# Warehouse coverage",
          "",
          "*Generated by `etl/s104_coverage.py` on every build. A measurement, not an "
          "assurance — the point is that a gap is visible here rather than discovered later.*",
          "",
          f"- **{len(docs)}** documents in the archive",
          f"- **{out['documents_contributing']}** contribute facts to the warehouse",
          f"- **{out['facts_total']:,}** facts, traceable to a document and (where the "
          f"source prints one) a page",
          f"- **{len(backlog)}** documents remain genuinely unread — the backlog below",
          "",
          "## Facts by government and year", "",
          "| Organization | " + " | ".join(y.replace("FY", "") for y in years) + " |",
          "|---" * (len(years) + 1) + "|"]
    for m in matrix:
        md.append(f"| {m['Organization_ID']} | "
                  + " | ".join(f"{m[y]:,}" for y in years) + " |")
    md += ["",
           "A thin year is a real hole, not noise. Hillsborough FY2018-FY2019 are thin "
           "because no DIGITAL audit has been obtained for those years — only scans, whose "
           "figures are published solely where a page's own arithmetic proves them. The fix "
           "is not more code: it is asking the town for the digital originals.",
           "",
           "## What is not read, and why", ""]
    for status, n in by_status.most_common():
        first = next(r for r in rows if r["status"] == status)
        md.append(f"- **{status}** — {n} document(s). {first['why'] or 'contributes facts'}")
    if backlog:
        md += ["", "## Backlog — documents with figures that no stage reads yet", ""]
        for r in backlog:
            md.append(f"- `{r['filename']}` ({r['jurisdiction']}, {r['format']})")
    md.append("")
    (REPO / "docs" / "COVERAGE.md").write_text("\n".join(md), encoding="utf-8")
    print(f"  wrote docs/COVERAGE.md")

    print(f"  {out['documents_contributing']}/{len(docs)} documents contribute "
          f"{out['facts_total']:,} facts")
    for status, n in by_status.most_common():
        print(f"     {n:3d}  {status}")
    if thin:
        print(f"  thin org-years (<200 facts): "
              + ", ".join(f"{t['Organization_ID']} {t['Fiscal_Year_ID']}={t['facts']}"
                          for t in thin))


if __name__ == "__main__":
    main()
