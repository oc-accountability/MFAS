# Extraction notes — read this before writing any parser

## The trap: the annual financial reports are scans, and their OCR layer transposes digits

**Do not read numeric values out of the annual financial reports' text layer. It is wrong.**

This is not a subtle rounding problem. It reorders digits, so a wrong number looks like a
perfectly plausible number.

### The evidence

FY2020 Annual Comprehensive Financial Report, PDF page 132 (printed page 115), *Table 6 — Tax
Revenues by Source*. What the page **visually** shows for fiscal 2011 ad valorem revenue:

```
2011        4,610,003
```

What three different extraction methods return:

| Method | Output for that cell |
|---|---|
| `pdftotext -layout` | `4,` / `003` / `610,` — split across three lines, reordered |
| `pdfplumber` `extract_text()` | `460,100,3` |
| character coordinates, sorted by `(top, x0)` | `460,100,3` |

The same corruption hits the summary figure on that page: the document states the ten-year change
as **61.02%**; every extractor returns **601.2%**. A pipeline that trusted this would publish a
ten-year tax growth figure inflated roughly tenfold.

Sorting characters by coordinate does *not* rescue it. The OCR layer's own character positions are
wrong, so there is no ordering of them that reconstructs the number.

### The mechanism

Every page of these files is a **full-page 612×792 raster image** with an invisible OCR text layer
on top. Two signals identify it, and `etl/s00_manifest.py` checks both:

1. `page.images` contains an image covering >90% of the page in both dimensions.
2. `pdffonts` reports **zero embedded fonts** — just non-embedded base-14 `Helvetica`. That is the
   characteristic signature of an OCR layer. A genuine digital PDF from these same offices carries
   embedded subset fonts (`GMPFID+TimesNewRoman`, `GMPHHP+Arial`, …).

### Which documents are affected

Ten documents are scans. `data/datasets/documents.json` marks each with
`"text_layer": "scan"` and `"values_extractable": false`:

- Annual (Comprehensive) Financial Report, FY2018 through FY2025 — the whole audited series
- `Comprehensive Annual Financial Report (FY18).pdf` — a second FY18 copy with **no text layer at
  all** (0 characters across 175 pages)
- `Fiscal Year 2024 2026 Strategic Plan 20230626.pdf`

Sixteen documents have real digital text and are safe to parse. All 62 published figures come from
those.

### One piece of good news

`Fiscal Year 2025 Financial Report.pdf` (2 MB, 131 pages) is the **digital original** of
`Annual Financial Report_ Year Ended June 30, 2025.pdf` (61 MB, 131 pages). The large file is
merely a scan of the same document. Their extracted text differs only in whitespace and line
wrapping, and the small one carries embedded TrueType fonts. **For FY2025, parse the 2 MB file.**

That is worth knowing generally: where a scan exists, a digital original may also exist. Before
committing to OCR for FY2018–FY2024, look for digital originals on the Town of Hillsborough's own
website. Fetching the authoritative file from the issuing government is both better data and
better provenance than OCR-ing somebody's scan.

### If you do need FY2018–FY2024 history

Options, in order of preference:

1. **Find the digital originals** on the town's website (see above). Best data, best provenance.
2. **Transcribe from the rendered page image.** Render with
   `pdftoppm -f <page> -l <page> -r 150 -png <file> out`, read the numbers off the image, and record
   them with `extraction: "transcribed"`. Slow but honest.
3. **Run real OCR** (`tesseract` / `ocrmypdf --redo-ocr`) over the page images and treat every
   result as provisional until spot-checked against the rendered image. Mark it
   `extraction: "ocr-unverified"` — and note that `etl/s90_build.py` **refuses to publish** that
   value, by design. Promote it to `transcribed` only after a human has confirmed it.

Never quietly widen `TRUSTWORTHY` in `etl/common.py` to make a build pass.

## Other traps found in these documents

**Percentages in parentheses lose their minus sign if you are careless.** Accounting notation writes
a deficit as `(3.5%)`, and the `%` may fall inside or outside the closing paren. A regex ending
`\)?%?` matches `(3.5%` — no closing paren — so a naive "ends with `)`" test reads it as positive.
`etl/s30_budget_messages.py` treats a **leading** paren as the negative marker for this reason.

**A tax rate is cents per $100 of value, not a percentage.** Formatting 51.3 cents as "51.3%"
overstates the rate by a factor of about 19.5. The site has a separate `cents()` formatter.

**The budget messages do not share one template.** FY2026 and FY2027 carry a
`Projected Surplus/(Deficit)` grid; the FY2025 message is prose only. FY2026 uses an **en-dash** in
row labels where FY2027 uses a hyphen. Match `[‐-―\-]`, not `-`.

**Do not anchor on the first run of FY labels on a page.** The page holding the projection table
also holds a sales-tax chart whose x-axis is ten FY labels. The parser anchors on the table title
and accepts only a 3–6 column header.

**`$1,124M` in the request workbook is a typo.** The row's own arithmetic
($791k original + $333k increase) fixes it at $1.124M. The ETL records the interpretation and the
raw cell text so the reading is auditable rather than silent.

## The line-item appendix (stage 50) — six traps, each found the hard way

The FY27 plan's "Line-Item Budget" appendix yields ~3,600 account-level observations. Every one of
these traps produced *plausible* wrong output, which is why they are written down.

**1. The departments appear twice in the document.** Once in the narrative section with a
category-level summary, once in the appendix with full account detail. Parsing both double-counts
everything. Only the appendix is parsed.

**2. The `Line-Item Budget: <Fund>` running header prints on a minority of appendix pages** — 7 of 28
in FY27. Using it as a per-page filter looked like it worked and silently dropped ~80% of the rows
(135 accounts instead of 766). It marks where the appendix *starts*; the last page with a column
header marks where it ends.

**3. State runs across page breaks.** A department's accounts continue onto pages that repeat neither
the fund header nor the department name, so fund/department/category/columns must persist.

**4. The page-number footer is appended to the END of data lines.**

```
SALARIES - COMMISSIONERS $36,110 $41,000 $41,000 $41,000 $41,000 249
Debt Service 259
```

That trailing integer breaks an end-of-line anchor on the money run, so whole rows vanish silently —
this alone lost Governing Body's $41,000 — and it invented a phantom department called
`Debt Service 259` that stole Solid Waste's total. Strip it only from lines that carry money, so a
label legitimately ending in a number (`TRANSFER TO FUND 69`) keeps its digits.

**5. A category name can be a data row.** `Debt Service` alone is a header; `Debt Service $80,277 …`
is data belonging to that category, *not* to the category printed above it. Getting this wrong moved
$366,781 of debt service into Operating while leaving both subtotals looking plausible. Test the
**extracted label**, not the whole line — testing the line never matches.

**6. Wrapped labels leave fragments that attach to the wrong row.** PDF extraction emits a wrapped
cell as label-part-1 / values / label-part-2. A surviving fragment latches onto the next values-only
line, which is how $300,000 of interfund transfers was recorded as Capital — right value, wrong
category, nothing visibly broken. Fragments are discarded at every section boundary and logged.

Also worth knowing: **only the FY27 plan has this appendix.** The FY26 adopted, FY26 recommended and
FY25 manager's plans were each checked and stop at category-level summaries, so FY2025 actuals reach
this project only through the FY27 document's five-column layout.

### The parse proves itself

`etl/s50_line_items.py` reconciles the account detail against the category totals the town publishes
on its own Financial Summary pages, then **fails the build** on any variance that is not explicitly
documented. Currently 55 of 60 published totals reconcile, and **FY2027 budget — the year the site
leads with — reconciles 12 of 12**.

Five variances are disclosed but unexplained, all in prior-year actual/estimate columns. Those slices
are marked `verified: false` in `lineitem_validation.json`, and the site shows a warning instead of
presenting them as checked. Two rules follow from this:

- Never widen `ROUNDING_TOLERANCE` or add to `KNOWN_VARIANCES` to make a red build go green. A
  documented variance needs a *cause*, not a bigger tolerance.
- If a variance changes size, it stops matching its recorded amount and fails. That is deliberate.

One known source characteristic, as an example of what a real explanation looks like: the
`Disaster - General Fund` unit is budgeted $10,000 of Operating at **category** level with no
account-level line, so an account-level listing correctly shows $0 for it. The appendix is internally
consistent; the money exists only above account grain.

## Reproducing the diagnosis

```bash
# is this file a scan?
pdffonts "sources/.../Annual Financial Report_ Year Ended June 30, 2023.pdf" | head
#   -> no embedded fonts, Helvetica only = OCR layer

# look at what the page actually says
pdftoppm -f 132 -l 132 -r 130 -png "<file>" /tmp/page && xdg-open /tmp/page-132.png

# what the text layer claims
pdftotext -layout -f 132 -l 132 "<file>" - | head -40
```
