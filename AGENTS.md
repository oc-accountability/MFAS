# AGENTS.md — instructions for an AI coding agent working in this repo

Read this before changing anything. It is short, and every rule in it exists because breaking it
would publish a wrong number about a real, named public official.

## What this project is

A fiscal transparency dataset and website for the **Town of Hillsborough, North Carolina**, built
from the town's own published documents for the Orange County Efficiency & Accountability
Initiative. The site is read by residents. Its only asset is being checkable.

## The two rules that matter most

### 1. Never publish a figure that cannot be traced to a document and a page.

The build **fails** rather than publish one. That is the project's only asset. Every published
fact cites a `Source_ID` that must resolve to a document in `data/datasets/documents.json`, and
`etl/s87_fact_financial.py` exits non-zero if any does not.

### 2. Never read a numeric value out of a scanned PDF's *text layer*.

Many source documents are page scans carrying an invisible OCR text layer that **transposes
digits**. The page reads `4,610,003`; that layer returns `460,100,3`. Sorting characters by
coordinate does **not** fix it, because the layer's own character positions are wrong.

**Reading the scanned IMAGE is different, and is allowed** — that is what `s71`/`s62` do, and it
is held to two gates: a recovered figure publishes only where its column sums exactly to the
printed total, and `s63` compares the result against a digital original wherever one exists
(**5,394 figures compared, 5,394 identical**). Such figures are labelled
`ocr-arithmetic-verified`, never `digital-text`, and are capped at `Medium` confidence.

**Do not "fix" a failing build by widening `TRUSTWORTHY` in `etl/common.py` or by relaxing a
test.** Full detail: `docs/EXTRACTION_NOTES.md`. Read it before writing any parser.

## How to work here

```bash
make venv     # once
make verify   # ⬅ THE RELEASE GATE: full rebuild + every check. Use this before publishing.
make etl      # rebuild data/ from sources/ only (does NOT run the checks)
make test     # the integrity gates alone
make serve    # http://127.0.0.1:8771/  (opening index.html from disk will NOT work)
```

`make etl` alone was once the documented rebuild command and it never ran the tests, which is
how three high-severity defects lived alongside a green suite. **Anything that publishes runs
`make verify`.**

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

## Rules two external audits installed — do not undo these

Two independent audits (`docs/2026-07-31_EXTERNAL_CODE_AUDIT.md`,
`docs/2026-08-01_EXTERNAL_AUDIT.md`). Each finding below shipped past a **green** test suite.

- **Key on the THING, never the SLOT.** Every defect in the first audit had this shape: a
  filename, a jurisdiction substring, a file size, an mtime. Ownership is recorded in an explicit
  table; caches are content-addressed by sha256.
- **Confidence is a CEILING derived from extraction** (`s87.confidence_for`), applied in ONE
  place. It may lower a caller's claim, never raise it. 1,110 rows once claimed `High` while
  being OCR or workbook imports — a caveat that is present but wrong is worse than none, because
  it gets relied on.
- **Never guard on a cached boolean about the world.** A flag saying "no digital original exists"
  was stamped before the digital audits arrived, so 36 recognised rows published for years read
  directly, 16 duplicating a digital row exactly. Ask the live set. And check EVERY path can
  reach the rule — three loaders emit recognition and one had no guard at all.
- **A test that compares a claim with a second copy of the same claim is not a control.** The
  workbook cover was checked against `coverage.json`; both were partial and agreed with each
  other while neither agreed with the actual tabs.
- **Revert your fix and confirm the test fails.** Every gate added since is verified this way.
- **Render the artefact and look at it.** Layout defects and three of four calculator surfaces
  were invisible to a passing build.
- **Never invent a source URL.** A plausible link resolving to a different revision of the same
  report is worse than a blank. Verify by downloading and matching sha256 — guessing sequential
  IDs produced a plausible hit that was a different document.

## Do not commit

Source PDFs, spreadsheets, or anything under `sources/`. The archive is 945 MiB and one file exceeds
GitHub's hard 100 MB per-file limit, so a stray `git add -f` produces a repo that cannot be pushed.
`tests/test_data_integrity.py` guards this.
