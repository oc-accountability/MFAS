# Data dictionary

The published data is a small star schema in `data/`. The website loads it and does every
calculation in the browser, so adding a fact to the pipeline changes the site with no code edit.

```
data/index.json                 entry point: counts, year range, dataset paths
data/datasets/facts.json        every observation (the fact table)
data/datasets/metrics.json      metric definitions: label, unit, category, description
data/datasets/documents.json    source manifest: hashes, page counts, text-layer quality
data/datasets/projections.json  fiscal years reported by more than one document
data/datasets/requests.json     the records request, as a fill-state scoreboard
data/datasets/issues.json       the initiative's working topic list
```

## `facts.json` — one row per observation

Long/tidy format deliberately: the site pivots and aggregates client-side, so a new metric never
requires a schema change or a new file.

| Field | Type | Notes |
|---|---|---|
| `jurisdiction` | string | `Town of Hillsborough, NC` or `Orange County, NC`. See the scope note below. |
| `fiscal_year` | int \| null | `2027` means FY2027, the year ending June 30 2027. Null where the figure is not year-specific (e.g. a project's original budget). |
| `metric` | string | Key into `metrics.json`. The build fails on an unregistered key. |
| `value` | number | Never null in published data. Deficits are negative. |
| `unit` | string | `USD`, `percent`, `cents_per_100_valuation`, `count`. |
| `basis` | string | `actual`, `budget`, `recommended`, `projected`, `estimate`, `stated`, `derived`. |
| `source_doc` | string | `id` in `documents.json`. |
| `source_page` | int \| null | 1-indexed **PDF** page, which may differ from the printed page number. |
| `source_detail` | string | Sheet name, table title, or the matched phrase. |
| `extraction` | string | How it was read — see `PROVENANCE.md`. |
| `note` | string | Caveats, interpretation decisions, attribution. |

### `unit` is load-bearing, not decorative

`cents_per_100_valuation` is **not** a percentage. A rate of 51.3 cents per $100 of assessed value
is 0.513% — formatting it as "51.3%" overstates it about 19.5×. The site has separate `cents()` and
`pctPlain()` formatters for exactly this reason, and `s90_build.py` warns when a fact's unit
disagrees with its metric registry entry.

### `basis` separates three very different kinds of number

Audited actuals, adopted budgets, and forward projections are not interchangeable, and neither is a
figure somebody asserted. Filter on `basis` before comparing anything. The same
`(metric, fiscal_year)` pair legitimately appears more than once with different bases — that is the
input to `projections.json`, not a duplicate to be deduplicated away.

## `metrics.json` — the registry

Maps each metric key to `label`, `unit`, `category`, and usually a `description`. This is the single
source of truth for how a metric is presented; the dictionary you are reading does not list the
metrics individually so the two can never drift. To see the current list:

```bash
python3 -c "import json;m=json.load(open('data/datasets/metrics.json'))['metrics'];\
[print(f'{k:46} {v[\"unit\"]:24} {v[\"label\"]}') for k,v in sorted(m.items())]"
```

Adding a metric means adding an entry here. `s90_build.py` fails the build on an unknown key rather
than letting an unlabelled series reach a chart.

## `documents.json` — the manifest

One entry per unique source file, keyed by `id` (a slug of the filename). Duplicate copies in the
original archive are collapsed into `duplicate_paths` — the archive held 9 of them.

The fields that decide whether a document may be parsed at all:

| Field | Notes |
|---|---|
| `sha256` | Proves your copy matches ours. |
| `text_layer` | `digital` = embedded-font text, safe. `scan` = page images with an unreliable OCR layer. |
| `values_extractable` | `false` for every scan. |
| `extraction_warning` | Present on scans, explaining the digit transposition. |
| `official_url` | Canonical URL on the issuing government's site. Currently `null` — see `PROVENANCE.md`. |

## `requests.json` — the records request as a scoreboard

The source workbook is a **blank template** sent to the Town: 23 data tables, 436 requested figures,
10 provided. Reading it as data would be a mistake; it is modelled as a request-status scoreboard
instead.

Per table: `sheet`, `section`, `title`, `columns_requested`, `rows_requested`, `cells_expected`,
`cells_provided`, and `status` (`unanswered` / `partial` / `answered`).

`cells_expected` is a **structural** count — row labels × year columns as laid out in the sheet. It
measures the size of the ask, not a legal obligation, and the fill state reflects the copy in this
archive at the time it was collected. It is not evidence that anyone refused to respond.

`projects_with_cost_changes` additionally carries `raw_cells` (the literal spreadsheet text) and
`arithmetic_consistent`, so an interpreted value like the `$1,124M` typo can be audited rather than
taken on faith.

## Scope: the name says Orange County, the data is the Town of Hillsborough

The initiative is named for **Orange County, North Carolina**; every document currently in the
archive is from the **Town of Hillsborough**, its county seat. The source archive has empty folders
for County Budget, Schools, Libraries, EMS, Parks and Affordable Housing — the county-level work is
scoped but not yet collected.

`jurisdiction` exists on every fact from day one so that county data can be added later without a
migration, and so no chart ever silently mixes a town figure with a county one. The site says which
jurisdiction it is showing.
