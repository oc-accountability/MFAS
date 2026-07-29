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
| `etl/s00…s103` | The pipeline, in order. `make etl` runs it. Each stage's docstring explains *why*, including what went wrong. |
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

The build is done and handed over. The **questions** are not, and that is the normal state:
30-odd open items, most needing an answer from a government rather than more code.

The next substantial piece is the warehouse design in `docs/WAREHOUSE_DESIGN.md` — one
warehouse, several analysis marts, with the government as a *column* so adding a municipality
is loading rows rather than redesigning. Two questions there are Amy's to settle before
building: whether Excel is the system of record or a generated view, and which of her four
Hillsborough database files is the real parent.

**The highest-value outstanding item is not code.** It is the chart-of-accounts crosswalk from
the town. Without it, any comparison spanning the FY26 category change is quietly wrong — which
is why her own FY18→FY27 waterfall carries a −$8.6M balancing plug, and why no waterfall has
been published here.
