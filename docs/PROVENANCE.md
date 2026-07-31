# Provenance — how a number on the site traces back to a page

The rule this project runs on: **every published figure names the document and page it came from,
and says how it was read.** A transparency site that cannot be checked is just an opinion with
charts.

## Why the source PDFs are not in this repository

The source archive is **925 MiB across 115 unique documents**. Two files exceed GitHub's hard
100 MB per-file limit outright (the FY2019 and FY2020 reports, 101 MB and 98 MB), so the archive
cannot be pushed as-is even if we wanted to. Git LFS is not a fix either: the free quota is 1 GB of
storage and 1 GB of bandwidth per month, which a public site would exhaust in a few dozen visits.

So the repository commits **extracted data plus a hash manifest**, and the documents stay out.
Concretely, `data/datasets/documents.json` records for every source file:

- `filename`, `archive_path`, and any `duplicate_paths` (the archive contains 43 duplicate copies)
- `bytes`, `pages`, `format`
- **`sha256`** — so you can prove your copy is byte-identical to the one the figures came from
- `text_layer` (`digital` / `scan`) and `values_extractable`
- `official_url` — the canonical URL on the issuing government's own site

## `official_url` is deliberately unfilled

It is `null` for every document right now, and that is honest rather than lazy: the archive arrived
as a folder of files, not as a set of links, so we do not yet know which published URL each file
corresponds to.

**Linking to the town's own copy is stronger provenance than hosting our own.** A reader who follows
a link to `hillsboroughnc.gov` is checking the government's published record, not our transcription
of it. Filling these in is the highest-value next contribution to this repo, and it does not require
re-running any extraction — just set the field and rebuild.

## How a figure is labelled

Every fact in `data/datasets/facts.json` carries an `extraction` field. The vocabulary is small on
purpose:

| Value | Means | Published? |
|---|---|---|
| `digital-text` | read directly from a PDF's embedded font text | yes |
| `stated` | a figure a document asserts in prose, or that a named person supplied | yes, labelled |
| `derived` | computed by this pipeline from other facts | yes, labelled |
| `transcribed` | a human read it off a rendered page image | yes |
| `ocr-arithmetic-verified` | recognised from a scan **and** its column adds up exactly to the total printed beside it | yes, labelled |
| `ocr-unverified` | from a scanned page's character-recognition layer, unchecked | **no — build fails** |

### Why `ocr-arithmetic-verified` is publishable and `ocr-unverified` is not

Character recognition fails by altering a digit. An altered digit breaks the column's arithmetic, so
a page whose lines sum exactly to its own printed total has checked itself. That is a structural
guarantee, not an estimate of quality — a figure either survives it or is withheld.

Measured recognition accuracy on these documents is 141/141 figures
(`etl/ocr_accuracy_probe.py`), but the arithmetic check is what makes a figure publishable, not the
measurement. Columns that do not balance are withheld entirely rather than published with a caveat,
because a caveat on a wrong number is still a wrong number.

## Best practice: replace scanned PDFs with the original digital copies

**Every figure recovered by character recognition would be safer read from a digital original.**

A digital PDF carries the characters themselves, so a figure is read rather than recognised, and the
whole class of recognition risk disappears. A scan is a photograph of a page; anything read from it
is an inference, however well verified.

This project already prefers digital wherever it can:

- The FY2025 annual report exists in **both** forms. The digital file is used and the 61 MB scan is
  ignored entirely, so the audited FY2025 figures on the site carry no recognition risk at all.
- Stage 70 skips any scan that a digital original supersedes, and records why in
  `ocr_manifest.json`.

**The single most valuable thing anyone could do for the accuracy of this site is to obtain digital
originals of the remaining annual reports from the town** and drop them into `sources/`. The
pipeline will prefer them automatically, the recognition step becomes unnecessary for those years,
and the verification machinery becomes a belt-and-braces check rather than a load-bearing one. It is
a request worth making of the town directly: publishing digital originals costs them nothing and
makes their own record easier for residents to check.

`etl/s90_build.py` enforces that last row. It also fails the build if a fact references a
`source_doc` that is not in the manifest, if a metric is missing from the registry, or if a value is
null. A missing number rendered as `0` on a chart is a lie, so the pipeline refuses to produce one.

## The distinction that matters most here

Some figures are **audited**, some are **budgeted or projected**, and some are simply **asserted by
someone**. Collapsing those together would be the single easiest way to mislead a reader, so the
data keeps them apart in the `basis` field (`actual`, `budget`, `recommended`, `projected`,
`estimate`, `stated`).

Two examples of why this matters in this dataset:

- The administrative-spend series (FY2023–FY2027, rising 32.6%) is attributed in the source workbook
  to **Commissioner Matt Hughes**. It is a claim worth checking, not an audited total. It ships as
  `extraction: "stated"` and the site says so on the chart.
- The same fiscal year often appears in several budget documents on different bases. The pipeline
  keeps **all** readings rather than collapsing to one, because the divergence is informative —
  see `data/datasets/projections.json`.

## Where projections and outcomes diverge

Because Hillsborough publishes a rolling three-year plan, FY2027 appears as a *projection* in the
FY2026 document and as a *budget* in the FY2027 document. Comparing them shows the town's forward
projections have consistently understated its fund balance:

| Fiscal year | Earlier document | Later document | Difference |
|---|---|---|---|
| FY2026 | $13,541,421 (budget) | $15,733,111 (estimate) | +$2.19 M |
| FY2027 | $12,710,817 (projected) | $15,266,880 (budget) | +$2.56 M |
| FY2028 | $11,379,358 (projected) | $14,380,540 (projected) | +$3.00 M |

**This is presented as calibration, not as an accusation.** Conservative budgeting is normal and
defensible practice, and the town says so itself: its FY2025 budget message states that it is
"conservative on revenue projections and cautious on expenditure amounts" and that most years "end
up with deficits less than projected or with an actual surplus generated." The useful conclusion for
a resident is about how much weight a three-year projection deserves — not that anyone misled
anyone.

## Verifying the whole chain yourself

```bash
# 1. confirm your copy of a source file matches ours
sha256sum "sources/.../FY27 Budget Message.pdf"
#    compare against the sha256 in data/datasets/documents.json

# 2. rebuild every published number from the sources
make etl            # or: ./.venv/bin/python etl/s00_manifest.py && ... && s90_build.py

# 3. confirm the rebuild is byte-identical to what is committed
git diff --stat data/
#    a clean diff means the committed data is exactly what the sources produce
```

That last step is the real guarantee: the data in this repo is reproducible from the documents, so
nobody has to trust us — including us.
