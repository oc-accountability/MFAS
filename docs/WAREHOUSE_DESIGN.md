# Data warehouse — a design proposal

*For Amy, 2026-07-28. This is a proposal, not a decision. The open questions at the end are
genuinely open, and several of them are yours to settle rather than mine.*

> **Status, 2026-07-29 — she decided, and steps 2–4 are built.** Amy agreed 100% to "one
> warehouse, several marts" and to "the government is a COLUMN"; confirmed the pipeline as
> the system of record with Excel as a generated view ("I strongly support a process that is
> 'closed'"); and answered the four-files question — they are all working files with FY2025
> sample loads, so **the design is the parent, not any file**. Register items Q046/Q047
> carry her words. `etl/s87_fact_financial.py` now builds the frozen dimensions and
> `Fact_Financial` — Hillsborough all years and scenarios, Orange County loaded through the
> identical constructor with zero schema change (the `step4_proof` block in
> `data/datasets/warehouse.json` records it). Questions 2–4 below remain genuinely open;
> the account crosswalk remains the highest-value item outstanding with the town.

You asked for suggestions on the approach. Here is what I would build, what I would change
about the current shape, and where I think you already got it right and should not be talked
out of it.

---

## The short version

**One warehouse. Several analysis marts. Not several warehouses.**

You floated plural warehouses — one for basic governmental data, others for analysis
(waterfall bridges, major events, commentary). I think the instinct is right and the wording
is worth changing, for one reason: **an analysis that keeps its own copy of the numbers drifts
away from the warehouse, silently.** The moment a waterfall holds its own revenue figures, you
have two versions of FY2025 revenue and no way to know which is stale.

So: analysis **references** the warehouse by key and never restates a number.

That is also a distinction you already made and named — **Workbook A / Workbook B** in your
Design Manual. A is the database, B is the analysis. You settled this in early July. I am
proposing you keep it.

---

## The three layers

| Layer | What it is | Changes when… |
|---|---|---|
| **0. Sources** | The documents themselves, each fingerprinted, with a Source_Register | A new document arrives |
| **1. Warehouse** | Conformed dimensions + fact tables at a declared grain. Append-only. | New data arrives (a year, a government) |
| **2. Analysis marts** | Waterfalls, bridges, change events, driver commentary, risk model | The *questions* change |

Layer 1 is boring on purpose. Boring is what makes it last.

---

## The one structural rule that matters most

> **The government is a COLUMN. Never a tab name. Never a file name.**

This is the whole answer to "what if I add Chapel Hill", and it is the single biggest change
from the current shape. Right now the *file names* carry the government —
`Hillsborough_Municipal_Financial_Database`, `Orange_County_Municipal_Finance_Database`. That
means adding a third municipality means a third file, a third set of tabs, and three places to
maintain the same schema.

With `Organization_ID` as a column, adding Chapel Hill is **loading rows**.

**And you already designed this.** `Hillsborough_Municipal_Financial_Database_v1` declares
`ORG_CH`, `ORG_CB` and `ORG_MB` with `Status = Future` — the IDs exist before the data does.
That is exactly the right pattern. It just needs to govern the file layout too, not only the
ID list.

---

## Grain — the thing to write down before building anything

Most warehouse pain comes from a fact table whose grain nobody wrote down. Proposed:

**`Fact_Financial`** — one row per:

`Organization_ID · Fiscal_Year_ID · Scenario · Fund_ID · Account_ID · Measure` → `Amount`

That single table holds revenue, expenditure and transfers. What distinguishes them is
`Account_ID`, not a separate tab. Your eleven topic tabs (`Fact_Revenue_GF`,
`Fact_Expense_Function`, `Fact_Debt_Service`, …) then become **views** onto it — pivot tables,
not stores.

**Why this way round.** Eleven fact tables means eleven things to extend every time you add a
government or a year. One fact table means one. The topic views stay, because they are how a
human reads it — they just stop being the place the data lives.

**Trade-off, stated honestly:** a single long fact table is harder to eyeball in Excel than a
topic tab. If that is too uncomfortable, the fallback is a small number of fact tables at
*consistent* grain (financial / staffing / debt / capital), never one per report.

### Dimensions

| Dimension | Key | Notes |
|---|---|---|
| `Dim_Organization` | ORG_HB, ORG_OC, ORG_CH… | Your existing IDs. Add `Status` (Active/Future) as you already do. |
| `Dim_Fiscal_Year` | FY18…FY35 | You already carry Data Scenario and revaluation context here. Keep both. |
| `Dim_Fund` | FUND_GF, FUND_WS… | Per organization — Chapel Hill's funds are not Hillsborough's. |
| `Dim_Account` | REV_/EXP_/TYPE_ | **See the crosswalk warning below.** |
| `Dim_Scenario` | Actual / Adopted / Recommended / Estimate / Projection | You already treat this as first-class. It is load-bearing. |
| `Dim_Source` | SRC_… | Source_ID + Source_Detail, exactly as you have it. |
| `Dim_Project` | PROJ_… | Yours. Nothing else in the project has this. |
| `Dim_Initiative` | STRAT_… | Also yours, also unique. This is what links spending to policy. |

---

## ⚠ The crosswalk, which is the trap you have already hit

`Dim_Account` needs a **crosswalk**, because **ACFR functional categories are not budget
ordinance categories**, and they changed beginning FY26. Your Design Manual already asks the
town for exactly this (Section 9: "General Ledger or Chart of Accounts crosswalk"). Your own
Lessons Learned already records it.

Without the crosswalk, any comparison spanning that change is quietly wrong. **You have
already seen this happen:** the FY18→FY27 budget waterfall in Workbook B carries a
`-$8,628,296` row labelled "Calculated plug — used to bridge budget presentation changes".
That plug is larger than most of the real components. It is not an error in your work — it is
the honest residue of a mapping that does not exist yet.

**So the crosswalk is not a nice-to-have. It is the thing standing between you and a
trustworthy multi-year bridge**, and it is the highest-value item outstanding with the town.

---

## Your three extensibility tests

You named three. They are the right acceptance criteria, so here is how each plays out:

**1. FY2027-28 budget arrives.**
Append rows: `Fiscal_Year_ID = FY28`, `Scenario = Adopted Budget`. Add one row to
`Dim_Fiscal_Year`. **No new columns, no new tabs, no schema change.**

**2. FY2026 actuals final in July 2027.**
Append rows with `Scenario = Actual`. **Do not overwrite the Estimate.**

Keeping both is not bookkeeping fussiness — it is one of the most valuable things this project
can show. *What the town projected, versus what happened.* You cannot show that if the forecast
is overwritten by the outturn, and nobody else is keeping that history.

**3. Chapel Hill joins.**
Append rows with `Organization_ID = ORG_CH` — an ID you already reserved. Add their funds to
`Dim_Fund` and their accounts to `Dim_Account`. **No structural change**, provided the rule
above holds and the government is never encoded in a file or tab name.

The honest caveat: their chart of accounts will not match Hillsborough's, so cross-municipal
comparison needs the same crosswalk problem solved a second time. Loading them is cheap;
*comparing* them is the work.

---

## What I would add that is not there yet

- **`Fact_Change_Event`** — one row per decision, with the cost, the debt created, the years
  affected, and the commentary. You named Fiscal Change Events as a core MFAS object; it is
  the bridge between "a decision was taken" and "these numbers moved". Everything needed for
  it already exists scattered across Material_Change_Drivers, the capital register and the
  funded/declined lists.
- **`Fact_Forecast_Vintage`** — which forecast said what, and when. You already hold FY2027
  projected two different ways by two different budget messages (68.3% and 78% fund balance).
  That disagreement is *information*, and right now it has nowhere to live.
- **A grain statement on every fact tab.** One sentence in row 1: "one row per …". It prevents
  most future confusion at nearly zero cost.

## What I would not change

- The Confidence vocabulary. Four levels, used consistently.
- `Source_ID` + `Source_Detail` on every fact.
- The `Accounting_Roadmap`. It is the clearest short statement of the hardest trap in the
  project and it should be promoted, not buried on a tab.
- Data_Quality_Gaps as a standing sheet.
- Lessons Learned. Your own note — *"they shouldn't disappear into old chats"* — is the most
  valuable sentence in the sixteen workbooks.

---

## Open questions — yours, not mine

1. **Is Excel the system of record, or the window onto it?** Everything above works in Excel,
   and Excel is where you work. But a warehouse in a spreadsheet has real ceilings: no
   referential integrity, no constraints, and version control by filename. The pipeline in
   this repository already *is* a warehouse with those properties. One option is that it
   becomes the store and Excel becomes the view — generated, always current, never hand-edited.
   That is a genuine trade of convenience against safety and it should be your call.
   **→ ANSWERED 2026-07-29 (Q046): the pipeline is the store, Excel the generated view —
   "I strongly support a process that is 'closed'."**

2. **What grain for `Dim_Account`?** Natural account (SALARIES, GASOLINE), function (Public
   Safety), or both with a mapping? Both is more work and more truthful.

3. **Are the school district, the sheriff and EMS Organizations, or Funds under `ORG_OC`?**
   Still open from the earlier conversation. It determines whether county-funded bodies can
   ever be compared with municipalities.

4. **How far forward do projections go?** FY29 in the current budget, FY35 in your v5. Pick
   one horizon and label anything beyond it as scenario rather than projection.

5. **Which of the four Hillsborough database files is the real parent?** Three were saved
   within an hour of each other and two are 33 seconds apart. The file dates cannot tell us,
   and I would rather build on the one you *meant* than the one that happened to be saved last.
   **→ ANSWERED 2026-07-29 (Q047): all working files, FY2025 sample loads only — the design
   is the parent, and no file's data seeds the warehouse.**

---

## Suggested sequence

1. ~~Settle questions 1 and 5 above~~ — **done 2026-07-29** (her email; register Q046/Q047).
2. ~~Freeze `Dim_Organization`, `Dim_Fiscal_Year`, `Dim_Scenario`~~ — **done**, in
   `etl/s87_fact_financial.py` and the export's `Dim_*` tabs.
3. ~~Build `Fact_Financial` for Hillsborough only, all years, all scenarios~~ — **done**:
   3,757 rows, FY2018–FY2029, all five scenarios, from the pipeline's verified datasets.
   Two grain lessons were paid for immediately and are recorded in the stage docstring:
   the documents themselves repeat account labels (hence `Line`), and revenue must never
   sum with expenditure (hence `Flow`, which also keeps the budget-vs-audited presentation
   difference visible instead of resolving it by guesswork).
4. ~~**Load Orange County into it without changing the schema.**~~ — **done, and the test
   passed**: 448 county rows through the identical row constructor, zero schema change
   (`step4_proof` in the dataset; a test pins it). Her county tables that are not
   fund-level dollar facts are recorded as `not_loaded` rather than forced in.
5. Then the analysis marts — waterfalls and change events — reading from it. **Next.**
   (The waterfall still waits on the account crosswalk; the plug row is why.)
6. Chapel Hill last, as the final proof that step 4 worked. *(Register Q048: digital
   PDFs — adopted budget + ACFR — when this approaches.)*

Step 4 was the real test, and doing it early was the point.
