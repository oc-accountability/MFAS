# Handoff — how this is built, and where you take over

Written for Amy. It assumes no programming knowledge, and it is specific about which parts are
yours to change.

Short version: **your design workbook and this website are two halves of one system.** You built a
curated warehouse for Orange County by hand; this repository is an automated pipeline that reads
published documents and puts the results on a public page. They now feed each other, and your
workbook is the authority for the county figures.

---

## 0. Where the pieces sit relative to each other

Amy has clarified the relationship between her documents, and it matters:

| Artefact | What it is |
|---|---|
| **MFAS** (3 Word docs) | The **current** conceptual architecture. Phase I is complete and baselined at v1.0. Working notes kept from a design conversation, used as a decision log — not polished specification. |
| **Excel v2.2** | An **earlier** implementation. It predates the expanded MFAS thinking, so it has not caught up with it. |
| **This pipeline** | A working data layer: extraction, verification, publication. |

So the Excel is not "behind" so much as **a different phase**. MFAS sets out Phase I
(conceptual) → Phase II (information architecture / data dictionary) → Phase III (dimensional
model, database, Excel or otherwise). The Excel warehouse and this pipeline are both Phase III-ish
work built against the earlier framing.

**What that means practically.** MFAS names five core objects — Community, Fiscal Change Event,
Financial Fact, Decision, Outcome. This pipeline currently implements **Financial Fact** thoroughly
(with metadata, traceability, and analytical views) and implements the others **not at all**.

The most consequential gap is **Fiscal Change Event / Decision**: treating a decision as a
first-class thing linked to its financial consequence. Notably, that is the same capability this
project independently identified as its single most valuable missing feature — telling residents
about a decision *before* it is taken, rather than reporting it afterwards. MFAS had already
named it.

Nothing built so far is wasted by this: MFAS's design principles ("fact-based", "traceable",
"separate facts from interpretation", "define once, reuse everywhere") are the principles this
pipeline already enforces. What MFAS adds is a larger frame the data layer sits inside.

## 1. What you already built, and what happened to it

Your `Orange_County_Municipal_Financial_Information_System_v2.2_Foundation.xlsx` is a real star
schema: permanent IDs, a source register, a data dictionary, dimension tables, and thirteen fact
tables holding **396 rows covering FY2018–FY2025**.

The pipeline now **imports it** (`etl/s85_warehouse.py`) and does three things:

1. **Reads it — never writes to it.** Your file is untouched. You keep editing in Excel.
2. **Adopts your vocabulary.** `Entity_ID`, `Fiscal_Year_ID`, `Scenario`, `Category_ID`,
   `Source_ID`, `Confidence` are your field names, and the warehouse output uses them. Where this
   project had its own word for the same idea, yours won.
3. **Re-checks your figures against the documents you cited.** For every row whose citation names a
   PDF page we hold, each monetary figure in that row must actually appear on that page.

**Result of that check: 41 of 41 checkable rows matched exactly.** Your FY2018 General Fund rows
were verified line by line against page 42 of the 2018 CAFR — property taxes, sales tax,
intergovernmental, the totals, the expenditure lines. All exact, and the page reference was right.

The check runs on every build, so it is not a one-off compliment — it is a standing safety net for
your work.

### Drop in a new version and it just happens

The pipeline automatically uses the **highest version number** it finds. Save
`..._v2.3_....xlsx` into `11 Design Documents` and the next build uses v2.3 instead of v2.2. You do
not have to tell anyone.

---

## 2. Two things the check noticed (yours to decide on)

Neither is an error. Both are the kind of thing your `Data_Quality_Gaps` sheet exists for.

**a. Source_IDs don't quite line up.** Your `Source_Register` lists IDs like
`SRC_OC_ACFR_2025_GFS`, while fact rows use `OC_CAFR_2018`, `OC_ACFR_2021`, and so on. The pipeline
resolves the difference by matching the year, which works — but it is guessing where it should be
looking things up. Aligning them in a future version would make the link exact.

**b. 26 rows have no Confidence value.** They are imported, but marked *not publishable on their
own*, because turning a blank into "trusted" would misstate your own assessment. Setting those to
High / Medium / Working / Pending is a five-minute job in Excel and releases them.

**Most rows could not be checked at all (355 of 396)** — not because anything is wrong, but because
their citation points at a section (`pp. 16–25`) rather than a specific PDF page. If you ever add a
`PDF p. N` to a row, that row starts being verified automatically on the next build. No other change
needed.

---

## 3. What the pipeline does, in order

Each step writes a file the next one reads. You can run any of them alone.

| Step | What it does |
|---|---|
| `s00_manifest` | Lists every source document, fingerprints it, and decides whether it is real digital text or a scan |
| `s20_xlsx` | Reads your Issues Log and your records-request workbook |
| `s30`, `s40` | Pulls the town's headline figures and household costs out of the budget messages |
| `s50` | The town's line-by-line spending — 3,600 figures |
| `s60` | The town's audited FY2025 statement |
| `s70`, `s75` | Reads the scanned town reports by character recognition, then verifies |
| `s80` | Orange County's tax rate and headline figures |
| **`s85`** | **Imports and re-verifies your workbook** |
| `s90` | Assembles everything the website loads, and refuses to build if anything is inconsistent |

`make etl` runs them all. `make test` runs 28 checks. `make serve` shows the site locally.

---

## 4. The rule everything obeys

**A number is only published if it can be checked.**

That takes a different form in each place, but it is always the same idea:

- Town spending detail must **add up to the town's own published totals** — 55 of 60 category
  totals reconcile, and the five that do not are listed openly rather than hidden.
- Figures recovered from **scanned** pages are published only where the lines on that page add up
  exactly to the total printed beside them. Character recognition fails by changing a digit, and a
  changed digit breaks the sum.
- **Your rows** are checked against the pages you cited.
- Anything that fails is **withheld**, not published with a footnote. A caveat on a wrong number is
  still a wrong number.

This is why the site can say "check us" and mean it.

---

## 5. Where to fine-tune — easiest first

**Anyone can do these:**

1. **Set the 26 blank Confidence values** in your workbook. Releases those rows.
2. **Add `PDF p. N` to more citations.** Each one you add gets automatically verified.
3. **Fill in `official_url`** in `data/datasets/documents.json` — the town's own web link for each
   document. Right now the site names a document; with this it can link to the government's own
   copy, which is much stronger.
4. **Rename the project.** It is called `hoa-funds`, which reads like a homeowners association. It
   is town and county government. One click on GitHub, and old links redirect.

**With help from your Codex:**

5. **Change any wording on the site.** All of it lives in `assets/app.js` as plain sentences. Ask
   Codex to change a phrase and it will find it.
6. **Add county detail to the site.** Your workbook has far more than the site currently shows —
   fund balance classifications, net position, debt and capital, enterprise funds, schools. The
   import already reads all 396 rows; only the General Fund summary is displayed so far.
7. **Add FY2026 actuals** when the audit lands. Append rows to your workbook in the same shape; the
   pipeline picks them up.

**Worth asking someone to do:**

8. **Get digital originals of the town's 2018–2024 annual reports.** Those are scans, and every
   figure from them is recovered by recognition. Digital files would remove that risk entirely.
   There is a draft request letter in the email David forwarded.

---

## 6. The one thing not to do

Do not "fix" a failed check by loosening the check.

If a build fails saying figures do not reconcile, the honest responses are to correct the
extraction, or to record the discrepancy openly with its cause. There are places in the code
(`KNOWN_VARIANCES`, `ROUNDING_TOLERANCE`) where a documented exception can be recorded — each one
requires a stated reason, not just a bigger tolerance. If a number cannot be justified, it should
not appear.

That discipline is the whole reason this can be shown to a town commissioner without flinching.

---

## 7. Honest state of things

**Solid:** the town's spending detail and audited record; the county's tax rate; your 396 imported
rows; the household calculator; every figure carrying a document and page.

**Partial:** the county is currently represented on the site only by its tax rate and its General
Fund totals, though your workbook holds much more. The town's 2019, 2021 and 2023 audited columns
are missing where the arithmetic did not verify.

**Not started:** advance notice of meetings and hearings — the ability to tell residents *before* a
decision rather than after. That is the single most useful thing this could become, and it needs a
source for the town's meeting agendas.

---

## 8. If something looks wrong

Use the **Report a problem** button on the site. It opens a pre-filled report carrying the figure,
the document and the page, so it arrives as something someone can act on. That applies to you too —
it is the fastest way to flag something without editing anything.
