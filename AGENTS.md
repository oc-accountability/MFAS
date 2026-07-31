# AGENTS.md — instructions for an AI coding agent working in this repo

Read this before changing anything. It is short, and every rule in it exists because breaking it
would publish a wrong number about a real, named public official.

## What this project is

A fiscal transparency dataset and website for the **Town of Hillsborough, North Carolina**, built
from the town's own published documents for the Orange County Efficiency & Accountability
Initiative. The site is read by residents. Its only asset is being checkable.

## The one rule that matters most

**Never read a numeric value out of a scanned PDF's text layer.**

Ten of the thirty source documents — including every annual financial report from FY2018 to FY2025 —
are page scans with an invisible OCR text layer that **transposes digits**. The page reads
`4,610,003`; every extractor returns `460,100,3`. A stated ten-year change of `61.02%` comes out as
`601.2%`. Sorting characters by coordinate does **not** fix it, because the OCR layer's own character
positions are wrong.

`data/datasets/documents.json` marks these with `"text_layer": "scan"` and
`"values_extractable": false`. `etl/s90_build.py` refuses to publish anything extracted that way, and
`tests/test_data_integrity.py::test_no_published_fact_comes_from_a_scanned_document` enforces it.

**Do not "fix" a failing build by widening `TRUSTWORTHY` in `etl/common.py` or by relaxing that
test.** If a value must come from a scan, render the page (`pdftoppm -r 130 -png`), read it with your
own eyes, and record it as `extraction: "transcribed"`.

Full detail: `docs/EXTRACTION_NOTES.md`. Read it before writing any parser.

## How to work here

```bash
make venv     # once
make etl      # rebuild data/ from sources/
make test     # 16 integrity gates — must pass before you commit
make serve    # http://127.0.0.1:8771/  (opening index.html from disk will NOT work)
```

The pipeline runs in order, and `s90_build.py` is a hard gate:

```
etl/s00_manifest.py         hash + classify every file in sources/
etl/s20_xlsx.py             the issues log and the records-request scoreboard
etl/s30_budget_messages.py  fiscal figures from the digital-text budget documents
etl/s90_build.py            merge + validate + emit the site payload
```

## Adding new documents

1. Drop the file in `sources/` (it is gitignored — source documents are never committed).
2. `make etl`. `s00_manifest.py` will hash it, classify it digital-vs-scan, and add it to the
   manifest automatically. **This step alone extracts no figures.**
3. To pull figures out of it, add a pattern to the `SCALARS` list in `etl/s30_budget_messages.py`,
   or write a new `etl/s40_*.py` stage for a new document family.
4. Every new metric needs an entry in the `METRICS` registry in `etl/s90_build.py` — label, unit,
   category. The build fails on an unregistered metric rather than letting an unlabelled series
   reach a chart.
5. `make test`, then commit.

## Adding a figure by hand

Sometimes the right answer is transcription, not parsing. Emit a `Fact` (see `etl/common.py`) with:

- `extraction: "transcribed"` and a `note` saying who read it and from which rendered page
- `source_doc` matching an `id` in `documents.json`, and `source_page` (1-indexed **PDF** page)
- the correct `unit` — see the warning below

## Traps that have already bitten

- **A tax rate is `cents_per_100_valuation`, not a percent.** 51.3 cents per $100 is 0.513%.
  Formatting it as "51.3%" overstates it ~19.5×. The site has separate `cents()` and `pctPlain()`
  formatters; keep them straight.
- **Parenthesised percentages lose their minus sign if you are careless.** `(3.5%)` is *negative*
  three and a half percent. The `%` may fall inside or outside the closing paren, so test the
  **leading** paren, not the trailing one.
- **Budget messages do not share one template.** FY2026 uses an en-dash in row labels where FY2027
  uses a hyphen; the FY2025 message has no projection table at all. Match `[‐-―\-]`.
- **Do not anchor a table parser on the first run of `FY..` labels on a page** — that page also holds
  a chart whose x-axis is ten FY labels. Anchor on the table title.
- Extraction failures must be **loud**. A silently missing figure renders as `0` on a chart, which
  reads as a factual claim of zero. Append to `extraction_problems` and let the build report it.

## Editorial standards

This is a data project, not an advocacy project. Keep it that way.

- Separate **audited actuals** from **budgets**, **projections**, and things a person merely
  **asserted**. That is the `basis` field. Never collapse them.
- A figure attributed to a named person is a claim to verify, not a finding. The administrative-spend
  series is attributed to a commissioner and ships as `extraction: "stated"` for this reason.
- Where the town's numbers move in its own favour, say so and quote its explanation. The site's
  projection-drift section does this deliberately — it presents the gap as calibration, alongside the
  town's own statement that it budgets conservatively.
- Never publish a number without its document and page.
- If you are unsure whether something is fair, leave it out and note the gap in the README's
  "Known gaps" section. An acknowledged gap costs nothing; a wrong accusation costs everything.

## Do not commit

Source PDFs, spreadsheets, or anything under `sources/`. The archive is 925 MiB and one file exceeds
GitHub's hard 100 MB per-file limit, so a stray `git add -f` produces a repo that cannot be pushed.
`tests/test_data_integrity.py` guards this.
