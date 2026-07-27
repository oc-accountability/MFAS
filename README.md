# hoa-funds — Hillsborough & Orange County fiscal transparency

Budget and financial data for the **Town of Hillsborough, North Carolina**, extracted from the
town's own published documents into a checkable dataset, with a website that runs the analysis in
the reader's browser.

Built for the **Orange County Efficiency & Accountability Initiative**.

**Every number carries the document and page it came from.** Nothing is presented as a finding
unless it can be traced, and figures that are somebody's claim rather than an audited total are
labelled as claims.

---

## What is here

| Path | What it is |
|---|---|
| `index.html`, `assets/` | The public site. Static, no build step, no dependencies. |
| `data/` | The published dataset — a small star schema of JSON. |
| `etl/` | The pipeline that produces `data/` from the source documents. |
| `docs/` | Provenance, data dictionary, and extraction notes. |
| `tests/` | Integrity gates, including one that stops source PDFs being committed. |
| `sources/` | The source documents. **Not committed** — see below. |

## Quick start

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r etl/requirements.txt

# rebuild the dataset from the source documents (needs sources/ populated)
make etl

# check the published data is internally consistent
make test

# serve the site — opening index.html from disk will not work, the browser blocks the fetch
make serve      # then open http://127.0.0.1:8771/
```

## Read this before touching the ETL

**The annual financial reports for FY2018–FY2025 are scans, and their embedded OCR text transposes
digits.** It renders `4,610,003` as `460,100,3` and a ten-year change of `61.02%` as `601.2%`.
Sorting by character coordinates does not fix it — the OCR layer's own positions are wrong.

A pipeline built on that text would publish confidently wrong figures about named public officials.
So the manifest classifies every document, the build **refuses** to publish a value marked
`ocr-unverified`, and none of the 62 figures on the site come from a scanned file.

Full diagnosis, evidence, and the safe paths to recovering the audited history:
**[`docs/EXTRACTION_NOTES.md`](docs/EXTRACTION_NOTES.md)**.

## Why the source documents are not in this repo

726 MB across 30 documents, and two files exceed GitHub's hard 100 MB per-file limit. Git LFS's free
tier (1 GB storage, 1 GB bandwidth/month) would not survive public traffic either.

Instead the repo commits the extracted data plus a **SHA-256 manifest** of every source file, so
anyone can prove their copy is the one the figures came from. Put the unpacked archive in `sources/`
to re-run the pipeline. See [`docs/PROVENANCE.md`](docs/PROVENANCE.md).

## The pipeline

```
etl/s00_manifest.py         hash + inventory every source file; classify digital vs scan
etl/s20_xlsx.py             the issues log, and the records request as a fill-state scoreboard
etl/s30_budget_messages.py  fiscal indicators from the digital-text budget documents
etl/s90_build.py            merge, validate, emit the site payload  ← fails the build on bad data
```

`s90_build.py` is a hard gate. It fails if a fact cites a document not in the manifest, uses an
unregistered metric, has a null value, or was read by a method not fit to publish. A missing number
rendered as `0` on a chart is a lie, so the pipeline will not produce one.

## What the data currently covers

- **62 figures**, FY2023–FY2029, from **16 digital-text documents** (10 scans pending transcription)
- General Fund budget, expenditures, surplus/deficit, and fund balance
- Property tax rate, and the town's own conversion factor: **one cent on the rate raises $240,000**
- Water/sewer/stormwater rate changes, affordable-housing and capital-project tax-rate equivalents
- Administrative spending FY2023–FY2027 (attributed to a commissioner, not audited)
- **12 multi-document comparisons** — the same fiscal year as first projected vs later reported

## What the site does

- A **household calculator**: enter an assessed home value, get the town's share of the tax bill,
  what one cent costs you, and what the town's own deficit scenarios would add
- Charts of budget, savings, deficits and spending, each with a table view and per-point citations
- **How the town's projections moved** — the same year across successive budget documents
- The **open records request** scoreboard: 10 of 436 requested figures provided
- The full source-document manifest with hashes and text-layer quality

## Known gaps, stated plainly

- **No county-level data yet.** The initiative is named for Orange County; every document in hand is
  from the Town of Hillsborough. `jurisdiction` is on every fact so county data can be added without
  a migration.
- **No audited multi-year history yet.** It exists only in the scanned reports. FY2019 and FY2020
  contain "Last Ten Fiscal Years" tables reaching back to FY2011 — a decade of trends — but they must
  be transcribed from page images, not scraped.
- **`official_url` is empty for every document.** Filling these in is the highest-value next
  contribution: it points readers at the government's own published record.
- Tax-rate history before FY2023 is charted in the source documents as images, not tables.

## A note on what this is and isn't

This is a data project. It shows what the town published, what it asked to be told and hasn't been,
and where its own projections and outcomes diverge. Where projections have come in better than
forecast, the site says so and quotes the town's own explanation that it budgets conservatively.

Conclusions are the reader's to draw. The job here is to make them checkable.

## Licence

Code: MIT (`LICENSE`). Extracted data: the underlying documents are public records of the Town of
Hillsborough; the extraction, structure, and annotations here are released under CC0.
