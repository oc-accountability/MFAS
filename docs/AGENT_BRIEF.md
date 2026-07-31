# Agent brief — how to work on MFAS

*For any AI agent picking this project up cold, and for anyone who wants to know the rules the
work follows. Read this before changing anything.*

MFAS — the Municipal Financial Analysis System — turns the published budget documents of the
Town of Hillsborough and Orange County, North Carolina into a checkable dataset and a
resident-facing website. It is Amy Jensen's project, part of the Orange County Efficiency &
Accountability Initiative.

- **Live site:** https://oc-accountability.github.io/MFAS/ *(case-sensitive; `/mfas/` 404s)*
- **Repo:** https://github.com/oc-accountability/MFAS

---

## The one rule everything else serves

> **Never publish a number that cannot be traced to a document and a page.**

A transparency project that gets a figure wrong about a real public official has done more
harm than not existing. Every other rule here is downstream of that one.

Concretely: **the build fails rather than publishes.** The integrity gates in
`tests/test_data_integrity.py` enforce it (`make test`; the count grows — do not quote it in
prose, it drifts), and the important ones are not style checks — they refuse to ship a fact
from a scanned page, a metric with no registered unit, a share computed against a total its
parts do not sum to.

---

## Editorial doctrine — Amy's, and binding

She stated the constraint herself, and it governs the site, the film, and every dataset:

> *"I don't want my opinion or me to tell anybody what is right or wrong."*

What that means in practice:

1. **Pose the question; do not answer it.** The structural section counts what a resident must
   read to understand their bill, then states plainly that no document in the archive says
   whether two administrations cost more than one — and publishes no figure for it.
2. **Include the evidence that cuts against the thesis.** Tax collection looks like obvious
   duplication until you find the town pays the county 0.5% of collections against a 1.5%
   peer average. That fact stays in, prominently, because leaving it out would make the site
   an argument rather than a record.
3. **Withhold rather than caveat.** A figure that cannot be trusted is not published with a
   warning attached; it is left out and the gap is named.
4. **Report a source's errors; never silently correct them.** The county ACFR prints its own
   tax rate with a misplaced decimal. That is recorded as a finding with the proof, and the
   correct figure is taken from a different table in the same document — not "fixed".
5. **No implication that anyone hid anything.** Every figure came from documents the
   governments published themselves.

---

## Verification doctrine

- **Reconcile to the source's own printed totals** before publishing a breakdown. Per column
  or per year, not just on the grand total — one bad column hides inside a correct sum.
- **Scanned PDFs are excluded.** The FY2018–FY2025 annual reports are scans whose OCR layer
  transposes digits (`4,610,003` → `460,100,3`). Ten documents are marked unextractable and a
  test enforces it. Fresh OCR was measured against a digital twin before any of it was used —
  141/141 figures exact — but a broken embedded text layer says nothing about fresh OCR either
  way, so *measure, don't assume*.
- **When a source looks wrong, check whether the bug is yours first.** This has happened
  repeatedly and every single time the first suspicion was wrong:
  - "Five of her workbook rows failed verification" → the checker mishandled a zero printed as
    a dash.
  - "Her fund balance disagrees with mine" → two documents report the same year and the
    comparison had grabbed last year's projection.
  - "Three of her workbooks are empty" → openpyxl's read-only mode trusts a stored dimension
    those files do not carry.
  - "Nine capital projects do not reconcile" → the parser was appending continuation rows
    instead of merging them.
  **Never report a source or a collaborator as wrong until you have tried to falsify your own
  tooling.**
- **Verify the artifact, not the process.** `finish` reported "verified against the picture"
  while muxing the ungraded one; only comparing video stream md5s caught it. A tool saying it
  succeeded is not evidence that it did the thing you wanted.

---

## Working with Amy

She is the domain expert and the author. The pipeline serves her workbooks, not the reverse.

- **Her workbooks are READ, never written.** A test fails the build if a stage ever gains a
  write path to one.
- **Import and verify rather than rebuild.** When she has already built something — the
  material change drivers, the tax-equivalent exposure — import it, check its arithmetic,
  cross-check it against this project's independent reading, and say so. Twice her figures
  matched to the dollar; that is worth more than a second implementation.
- **Her schema is the contract:** `Organization_ID` (ORG_HB, ORG_OC), `Fiscal_Year_ID` as
  `FY27`, `Source_ID` + `Source_Detail`, `Confidence` ∈ High/Medium/Working/Pending, and her
  `STRAT_` / `PROJ_` ID prefixes. A key that does not match hers will not join to her data.
- **Every open item has an owner.** `docs/OPEN_QUESTIONS.md` is generated on every run and
  sorted by who can actually resolve it — her, the town, the county, or this project. A
  question that quietly vanishes is indistinguishable from one that was forgotten, so answered
  items stay with their answer.

---

## What the external audit changed (2026-07-31)

An independent code audit found four high-severity defects. None was a wrong number;
**all four were in the rebuild and export path**, which is worse in a project whose
promise is traceability. They are fixed, each with a test, and the pattern connecting
them is worth more than the individual fixes:

> **Every one of them keyed on something that describes the SLOT a document occupies
> rather than the document itself** — a filename, a jurisdiction substring, a file size,
> a modification time. If you are about to key on any of those, that is the defect.

| Was | Now |
|---|---|
| Owner inferred: `"ORG_OC" if "Orange" in jurisdiction else "ORG_HB"` | `organization_id` recorded explicitly in `s00` from `ORG_BY_JURISDICTION` |
| Confidence from readability — every non-scan was `High` | Confidence from **authority × extraction**; initiative material is `Working` |
| Caches keyed on doc-id / filename stem / size+mtime | `common.content_cache_dir()` — sha256 + extractor version, `_meta.json` verified on read |
| `s75` globbed `build/ocr` | `s75` consumes the OCR manifest and rejects a hash mismatch |
| IDs from basenames, collisions renumbered by traversal order | `data/source_registry.json`, keyed by sha256; collision is a hard error |
| `official_url` reset to `None` every rebuild | preserved in the registry; `s00` is append-only |
| Stages printed failures and exited 0 | `common.report_and_gate()` exits nonzero unless the line is marked `INFO` |
| Unit mismatch was a warning; scan-text figures only counted | both are build errors in `s90` |
| Exports ran before `s90` merged `facts.json` | `s90` runs first; a test compares export rows to the JSON |
| `make etl` was the release command and never ran tests | **`make verify`** is the release gate; CI enforces it |
| Volatile counts pinned in prose — the README's document count and archive size had both drifted well behind the manifest | a test scans the trust documents for stale counts and sizes; point at `docs/COVERAGE.md` instead of quoting a number |

The audit's own summary of why this could happen is worth keeping: the tests validate
committed artifacts and source strings, but **do not execute the ETL against fixture
documents**, so cache invalidation, a clean one-pass build and export/JSON agreement had
no coverage at all. That gap is still open and is the most valuable testing work left.

One claim was softened rather than fixed, and it matters because it appears in emails:
the per-page arithmetic check makes an undetected OCR misread **very unlikely**; it is
not a *proof* of digit accuracy, because offsetting errors could in principle survive it.

## Operational traps, each paid for once

- **Google Drive exports are PARTIAL.** One export held 71 files where the archive held 108.
  **Merge, never sync** — a mirror would have deleted 37 source documents.
- **Verify a zip is complete before extracting.** A half-written archive looks valid until you
  open it.
- **GitHub Pages does not redirect and its paths are case-sensitive.** `/MFAS/` is 200;
  `/mfas/` and the old `/hoa-funds/` are both 404. Git URLs *do* redirect permanently, which
  makes the asymmetry easy to miss — a push to the old remote succeeds.
- **`.gitignore` carries `*.xlsx`, and `git add -A` skips ignored files silently.** The
  generated exports are negated explicitly. A commit can succeed, tests pass, the README link
  render, and the file simply not be there.
- **A repo-hosted mp4 will not play from a GitHub blob link.** Serve video from Pages, which
  sends `video/mp4` with range support; `raw.githubusercontent` sends `application/octet-stream`
  and downloads instead.

---

## Layout

| Path | What |
|---|---|
| `etl/s00…s104` | The pipeline, in order. `make etl` runs it. Each stage's docstring explains *why*, including what went wrong. |
| `etl/statement_parser.py` | Shared reader for nested PDF financial statements (stages 61 and 81). Six traps documented at the function that defends against each. |
| `docs/COVERAGE.md` | Generated. Which documents feed the warehouse, which do not, and why. |
| `data/datasets/` | Published JSON, one file per topic |
| `data/exports/` | Generated Excel — the warehouse and the workbook tab map |
| `docs/HANDOFF_FOR_AMY.md` | Plain-language guide for her |
| `docs/OPEN_QUESTIONS.md` | The register, by owner |
| `docs/WORKBOOK_CATALOGUE.md` | Her 20 workbooks, 5 families, which to build on |
| `docs/WAREHOUSE_DESIGN.md` | The warehouse proposal and its open questions |
| `index.html`, `assets/` | The site. Runs entirely in the browser; no server. |
| `sources/` | Source documents. **Never committed** — one exceeds GitHub's 100 MiB limit and a second sits at 98 MiB. |

**A stage docstring is the real documentation.** They record the reasoning and the failures,
not just the behaviour. Read the one next to whatever you are changing.

---

## Where the project is

The warehouse Amy commissioned is built and loaded. As of 2026-07-29 it holds **21,461 facts**
across three tables, both governments, every audited year FY2018–FY2025, each figure traceable
to a document and — where the source prints one — a page:

- **`Fact_Financial`** (11,759 rows) — the core. One table, government as a column.
- **`Fact_Metric`** (109 rows) — facts that are not fund dollars: fund balance, net position,
  debt and capital, schools, outlook. `Unit` is load-bearing here.
- **`Fact_Statement_Line`** (10,275 rows) — verified and cited, but the statement's column
  meaning is not yet established, so the basis is explicitly unknown. See below.

`docs/COVERAGE.md` is regenerated every build and is the honest answer to "is it full?" — it
names every document that contributes nothing, and distinguishes *correctly empty* from
*backlog*. Do not replace that measurement with a claim.

Three things to know before extending it:

1. **The highest-leverage piece of work left is reading statement COLUMN HEADERS.** Stages 61
   and 81 prove which column is budget and which is actual from each statement's own variance
   identity. Statements with no variance column — balance sheets, net position, cash flows —
   use columns for *funds* or *activity types* instead, so nothing confirms them, and 10,275
   verified figures sit in `Fact_Statement_Line` with no basis. The same header-reading also
   unlocks the unread budget documents, whose columns are fiscal years. One piece of work,
   two payoffs (Q053).
2. **A number of documents with figures are still unread** — `docs/COVERAGE.md` has the
   current count and names every one, because pinning it here is exactly how this file
   drifts. They are mostly budget plans — the
   town's FY26 Adopted/Recommended/Ordinance and FY2025 Recommended, the county's FY25-26 and
   FY26-27. The FY27 plan's line-item appendix, the one structure this pipeline reads deeply,
   **does not exist in any of them** (measured: 9 hits in FY27, 0 in the other five). Q054.
3. **Hillsborough FY2018–FY2020 are thin** (31, 28 and 197 facts against FY2025's 983) because
   no *digital* audit has been obtained for those years. That is a documents problem, not a
   code problem — Q055 asks Amy to request them.

### The chart-of-accounts crosswalk — SOLVED 2026-07-30, and it was never the town's to give

For weeks this was recorded as the highest-value item outstanding, blocked on the Town of
Hillsborough. It was not blocked. **The town's audit already publishes the crosswalk**, and the
pipeline had been reading the page for a day without anyone noticing what it was.

Schedule 1 — the six-page General Fund schedule in every annual audit — does not merely list
departments. It **groups them under the seven GASB functional headings**, with subtotals that
reconcile exactly. That grouping *is* the crosswalk, for every year an audit exists. From the
FY2025 audit:

| Audit function | FY2025 actual | Departments the audit puts inside it |
|---|---:|---|
| Public safety | 6,713,159 | Police department · Safety · Fire protection |
| Transportation | 1,826,906 | Fleet maintenance · Street department/Powell Bill |
| Environmental protection | 744,869 | Sanitation department · **Cemetery** |
| Economic and physical development | 644,688 | **Tourism** |
| General government | 3,178,752 | Governing body · Facility management · Administration · Finance · Human resources · Communications · Information services · **Planning** · Engineering services · Disaster |

**Nobody could have guessed this, and two people tried.** Amy's mapping (via Gemini) and this
project's independent guess both put Cemetery under Parks and recreation — it is Environmental
protection. Both put Planning under Economic and physical development — that function is
Tourism, and Planning is General government. The two guesses missed by −$531,649 and +$862,123
on single functions. The lesson is the general one in rule 3 above: *the documents answer more
than they appear to, and a guess that sounds authoritative still fails the arithmetic.*

Matching the audit's department names to the BUDGET book's names is then done by amount, not by
judgement — nine match to the dollar (Police 4,490,983≈4,490,984, Finance 428,864≈Accounting
428,865, Governing body 118,167≈118,168, Engineering services −6,934≈−6,935, …). The residuals
are informative rather than noise: the budget book's **Planning ($1,506,811)** is the audit's
**Planning ($862,121) + Tourism ($644,688)** = $1,506,809, two dollars apart. One budget
department, two audit functions — exactly the kind of split that silently breaks a multi-year
category chart.

**What remains** is to extract this into a published `Dim_Account` crosswalk across all years
rather than the ad-hoc analysis it is today. That is ordinary work on data already held.

**On whether it was even needed** — Amy's challenge was fair and partly right: the audit series
and the budget series are each internally comparable, and no government publishes an
audit↔budget reconciliation because they serve different audiences (GASB functional reporting
vs departmental operational control). The crosswalk is needed only for the narrow cases: putting
an audited actual and a budget figure in one chart, and bridging the town's own FY26 category
change — which is what her FY18→FY27 waterfall's −$8.6M plug is absorbing.

### What the 2026-07-29 fill taught, beyond the parser

Four of the six defects found that day were **this pipeline discarding its own evidence**, not
bad sources — which is the brief's rule #3 showing up again at a larger scale:

- Stage 75 verified each column by summing its component lines and then published only the
  column total, throwing away the lines its own arithmetic had proven.
- Stage 85's workbook import kept a hardcoded list of eleven fields and dropped `Metric`,
  `Unit`, `Fund` and `Activity_Type`. Nine of Amy's county tables arrived as a bare `Amount`
  with nothing to say what it measured — and were then held out of the warehouse as "not
  fund-level dollar facts". They were fine; their labels had been thrown away.
- The same import looked for `ACFR_Page` while nine of her tabs spell it `ACFR Page`, so
  hundreds of rows imported with no citation and were counted as unverifiable.
- The page filter required the words "Exhibit" or "Schedule" — Hillsborough's house style. The
  county titles its statements in caps with no such label, so the single most important
  statement in each county ACFR was skipped, and 122 of Amy's figures looked unfindable.

Before reporting a source or a collaborator as wrong, check what the pipeline threw away.
