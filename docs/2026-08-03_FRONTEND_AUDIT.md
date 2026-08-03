# Frontend audit — the structure that produced the out-of-town defect

**Date:** 2026-08-03
**Scope:** `assets/app.js` (3,148 lines), `index.html` (168), `tests/test_data_integrity.py` (2,093 lines, 117 tests), `.github/workflows/verify.yml`
**Occasion:** finding **M-04** of the 2026-08-01 external audit — *"Frontend behavior is untested and too hard-coded for county expansion"*
**Baseline:** `make verify` green, full rebuild byte-identical, 117 Python tests, **0 JavaScript tests**

---

## Why this audit exists

On 2026-08-01 an external audit found the calculator charging **town** property tax to homes
**outside** the town limits. A $500,000 home was shown $5,944 instead of $3,379 — a 76%
overstatement — on the site's primary trust surface. Every one of the 111 tests passed while
that was live, because the tests validate **data** and never execute the **page**.

That defect is fixed and has a browser regression test. **The shape that produced it is not.**

The bug survived in four surfaces at once — the hero readout, the printable takeaway, the
spending explorer, and the "what it pays for" sentence — because each surface kept its own copy
of the calculation. One was fixed; three were not; and nothing could tell.

This audit looked for that shape everywhere else. It found it intact in five more places, and
found that **both** gates written after the incident are blind to the surfaces where it lives.

Two facts frame everything below.

> `assets/app.js:726` `townLevyIfInTown()` and `assets/app.js:735` `totalPropertyTax()` — the two
> helpers written *specifically* to be the single source for these calculations — have **zero call
> sites**. `grep -n 'townLevyIfInTown\|totalPropertyTax' assets/app.js` returns the definitions and
> nothing else. **The documented design is not the implemented one.**

> `tests/test_data_integrity.py:1907-1909` is `for call in re.findall(r"\btownLevyIfInTown\(\)", js): pass`
> — a loop with an empty body. It asserts nothing, and CI reports the rule as covered.

---

## Method

Six independent audit lenses were run over the source — calculation/render entanglement,
jurisdiction and fiscal-year hard-coding, duplicated calculation surfaces, divergent state,
untested branches, and prose that asserts more than the data guarantees. Every finding was then
handed to a separate adversarial reviewer instructed to **refute** it: reopen the cited line,
check the claim against current code, trace whether the failure state is actually reachable, and
default to *refuted* when uncertain. **13 findings were killed that way** — including two of the
auditor's own — and are recorded below so nobody re-raises them.

Findings were not accepted on reading alone. The page was served and rendered:

```
python -m http.server 8771 --bind 127.0.0.1
chromium --headless --disable-gpu --no-sandbox --virtual-time-budget=9000 --dump-dom <url>
```

for `?home=500000&where=intown` and `?home=500000&where=outoftown`, at desktop and at 390 px.
Because the printable takeaway and the copied text are built inside click handlers and therefore
**never appear in a DOM dump** (see F-04 — this is itself a finding), those two artefacts were
captured by a probe page that loads the real `assets/app.js` and calls the real builders. Every
figure quoted below as "rendered" was read out of a live DOM, not inferred from source.

---

## Ranking

Ranked by **(probability a wrong figure reaches a reader) × (number of surfaces carrying it) ×
(invisibility to the current suite)**. A dormant defect that fires on the next data refresh
outranks a cosmetic one that is live today.

| ID | Defect | Severity | Status |
|---|---|---|---|
| F-01 | Five ungated copies of the one-cent town-rate conversion charge town tax to out-of-town homes | wrong number | **live** |
| F-02 | Year-keyed JSON property names read by literal access → `$NaN` and `$0` | wrong number | dormant |
| F-03 | The browser gate samples the hero mid count-up; the primary figure is unassertable | coverage | **live** |
| F-04 | The browser gate never renders the printed takeaway or the copied text | coverage | **live** |
| F-05 | Both single-source helpers are dead code; the test policing them asserts nothing | coverage | **live** |
| F-06 | Fund balance selected by literal `forYear(…, 2027)` on two surfaces | wrong number | dormant |
| F-07 | FY2029 cliff paragraph attached by `f.fiscal_year === 2029`, not by the fact's year | wrong number | dormant |
| F-08 | Capital-plan split is positional and its year range is prose | wrong number | dormant |
| F-09 | "Your property tax rate is not going up this year" — the county's rose 3.75 cents | wrong label | **live, all readers** |
| F-10 | A missing county rate collapses to "$0 in property tax this year" | wrong number | dormant |
| F-11 | Fund shares divide by the sum of parts but are labelled "of the total" | wrong number | dormant |
| F-12 | "So next year costs you about +$X" structurally cannot include a town rate rise | wrong number | dormant |
| F-13 | "What's coming" timeline pinned to `>= 2027` | wrong label | dormant |
| F-14 | `\|\| 240000` fabricates a divisor under the card's own "n/a" | wrong number | dormant |
| F-15 | Audited variance sentence has no sign branch | wrong label | dormant |
| F-16 | The 50% fund-balance floor is hardcoded in five places and drives a ✓/! verdict | wrong label | dormant |
| F-17 | One optional dataset 404 amputates sections 04–06 with no error | trust surface | dormant |
| F-18 | Utility fallback names stormwater in a total that excludes it | wrong number | degraded-mode |
| F-19 | The copied snapshot exports the town rate as "Tax rate" for every reader | wrong label | **live** |
| F-20 | localStorage fabricates "Welcome back — a home assessed at $400,000" | wrong label | **live** |
| F-21 | The explorer's personalised share omits the slice year | wrong label | **live** |
| F-22 | Utility rows labelled "FY2027 rates" / "on FY2026" from string literals | wrong label | dormant |
| F-23 | The glossary hardcodes 51.3 cents and a $513 worked example | wrong number | dormant |
| F-24 | "Your property tax funds two separate governments" rendered unconditionally | wrong label | **live** |
| F-25 | Hero caption "town and county combined" over a county-only figure | wrong label | **live** |
| F-26 | Explorer default year + hardcoded "the FY2027 budget figures reconcile exactly" | wrong label | dormant |
| F-27 | Transfer schedule selected by literal 2027; disappears silently | disclosure loss | dormant |
| F-28 | "about a third" is a hand-computed ratio in prose between two live percentages | wrong label | dormant |
| F-29 | Four live WCAG scrollable-region failures — the a11y fix covers only the tables rendered at load | access | **live** |

---

## Status after the 2026-08-03 commits

Four commits followed this audit. What they closed, and what they deliberately did not:

| | Findings | State |
|---|---|---|
| **Closed** | **F-03** the gate sampled the hero mid count-up · **F-04** the gate never saw the takeaway or the copied text · **F-05** the two dead helpers and the body-less loop that policed one of them · **F-29** the a11y rescan missing from both toggle handlers | fixed, each with a test proven to fail on revert |
| **Made one-line fixes** | **F-01**, **F-10**, **F-19**, **F-25** | the arithmetic now lives in one tested place (`assets/domain.js`), and `propertyTaxBill()` already distinguishes *does not apply* from *unknown* from *zero*. The remaining change at each site is a call and a word. |
| **Untouched** | **F-02**, **F-06**–**F-09**, **F-11**–**F-18**, **F-20**–**F-24**, **F-26**–**F-28** | see below |

Nothing in those commits changed a published figure. That was checked rather than
asserted: both DOMs were dumped before and after, and all 676 in-town and 671
out-of-town dollar, percent and cents strings are identical.

**Why the rest were left.** Every one of them changes what a reader sees — a label, a
verdict, a sentence, a suppressed row. The brief for this work was a structural
refactor under an explicit rule that no published figure may move, and several of these
sit on top of an editorial question that is not the engineer's to answer (see *Not
closed by the stated sequence*, below). They are one-line changes on top of the
extraction, and each needs a decision, not a technique.

---

## The findings

### F-01 — Five ungated copies of the one-cent town-rate conversion

**Defect.** `const oneCent = state.homeValue / 100 * 0.01` is written inline five separate times
and multiplied by town-rate cent figures with **no reference to `state.location`**, so roughly
eighteen personalised dollar amounts for *town* rate changes are published to a household the same
page has just told pays the town nothing.

**Sites.** Definitions: `assets/app.js:901` (`draw`), `:1173` (`takeawayHTML`), `:2348`
(`renderComing`), `:2479` (`driversBlock`), `:2549` (`tradeoffBlock`).
Consumers: `:968`, `:976-979`, `:1198`, `:1222-1224`, `:2366`, `:2389`, `:2407`, `:2410`,
`:2501-2507`, `:2524`, `:2563`.

**Failure — verified in a live DOM dump.** `?home=500000&where=outoftown` renders a hero of
`$3,379` and the sub-line "**No town property tax** — the home is outside the town limits". The row
list two inches below it, in the same `#bd`, prints:

- "One cent on the tax rate costs **you** · across the whole town it raises $240,000 · **$50 / yr**"
- "If the rate rose 10 cents · **at least +$500 / yr**"

Section 04 adds "at least **$500 a year** for a home like yours", "roughly **$210 a year** for your
home", "about **$100 a year** for you", the FY2029 cliff "roughly **$743 a year** on a home like
yours", the tradeoff card "about **$59 a year** on a home like yours", and **twelve** driver rows
reading "· $729/yr on your home", "$131", "$78", "$77", "$70", "$67", "$67", "$63", "$46", "$23",
"$16", "$13". Every one is $0 for this household.

The printed takeaway carries two of them **onto paper** — captured from the real builder:

```
One cent on the town tax rate   what a single cent of rate costs a home assessed at this value
                                                                                    $50 / yr
…
Closing the FY2029 shortfall the town projects would take a rise it puts at over 10 cents
— at least $500 a year on this home.
```

That is the one artefact a resident carries into a board meeting, where they cannot click through.

Reachability is not limited to share links: `refreshDependents()` (`:1339-1346`) re-renders
`renderComing`, which calls `driversBlock` and `tradeoffBlock` at `:2436-2437`, so toggling
"No, outside" live repaints all three cards with the same figures.

**Why the 117 tests miss it.** `test_out_of_town_pages_never_show_the_town_levy` asserts only that
the strings `2,565` and `5,944` are absent. `$50`, `$500`, `$210`, `$743` and `/yr on your home`
are not asserted. The source-regex test at `:1908` is a no-op loop (F-05).

**Nuance that must survive the fix.** The comment at `:723-725` says the unconditional levy is
*deliberate* for these rows, because they are "town POLICY comparisons rather than components of
this household's bill". That reading is defensible for the **cents** figure. It is not defensible
for the second-person **dollar** column. The defect is the mismatch between an unconditional
calculation and copy that says *costs you / on your home / on this home / for you / a home like
yours* — inside a row list sitting under a total reading "So next year costs you about".

**Smallest remedy.** One pure `townPolicyDollarsOnThisHome(homeValue, location, cents)` returning
`null` outside the limits; delete the five inline constants and the dead `townLevyIfInTown()`.
Where the cents figure is still worth showing to a non-resident, render it without the
personalised dollar column. Extend the chromium gate to assert the out-of-town DOM contains no
`on your home` / `for your home` / `for a home like yours` / `for you` / `on this home` dollar
string.

---

### F-02 — Year-keyed JSON property names read by literal access

**Defect.** Four renderers reach into datasets by a property name containing the fiscal year
(`fy2027_total_asked`, `.fy2027`, `general_fund_fy2027_budget`); each guards the **parent object**
but not the **key**, so a roll-forward yields `usd(undefined)` — the literal string `$NaN` — or
falls back to `$0`.

**Sites.** `assets/app.js:2557`, `:2558`, `:2559`, `:2586`, `:1632`, `:1633`, `:1429`, `:1442`.
Format helper: `:148` `const usd = n => '$' + Math.round(n).toLocaleString('en-US')`.

**Failure.** The FY28 budget lands; `etl` regenerates `tradeoffs.json` with
`summary.fy2028_total_asked / fy2028_funded / fy2028_declined` and `declined[].fy2028`. The guard
at `:2546` is `if (!d || !d.declined) return;` — it passes. Section 04 then publishes:

> "Departments asked for **$NaN** of new spending next year. The town funded **$NaN** of it and
> **declined $NaN** — 4 requests"

and every declined-request row shows **$0** (from `r.fy2027 || 0` at `:2586`) beside a real
three-year total, so four requests appear to cost the town nothing. `:1632` renders "A proposed
increase — **$NaN** next year, $1,155,500 over three — was not funded". At `:1429`,
`rd.general_fund_fy2027_budget || {}` collapses to `{}`, so "How much of it is already committed?"
publishes a live **86.6%** (a sibling field that is *not* year-keyed and does advance) above an
empty row list.

**Why the tests miss it.** All 117 validate the datasets as they are. None executes a renderer, and
none runs any block against a dataset whose year keys have been bumped.

**Smallest remedy.** The year-agnostic form already exists in the published data:
`data/datasets/tradeoffs.json` carries a top-level `"years": [2027,2028,2029]` and every row carries
an `amounts` array whose `[0]` is FY2027 (`etl/s95_tradeoffs.py:119`). Read `d.years[0]` and
`r.amounts[0]` — no schema change needed. Separately, make `usd()` render `—` for a non-finite
input so no arithmetic path can ever emit `$NaN`.

---

### F-03 — The browser gate samples the hero mid count-up

**Defect.** `setFigure()` animates the hero over 620 ms via `requestAnimationFrame`; the
`--dump-dom` capture the only browser test uses reads `#heroV` **before the animation finishes**,
so the page's largest figure is never observed at its final value — and the value sampled is
nondeterministic.

**Sites.** `tests/test_data_integrity.py:1937-1941` (the chromium argv), `:1946`, `:1954`;
`assets/app.js:1309-1319` (`setFigure`), `:1119` (`draw(!REDUCED && !state.returning)` — animation
is on for exactly the share-link path the test drives).

**Failure — measured.** Running the test's own command produced `id="heroV">$4,968` in one run and
`$4,892` in another; a third observer got `$783`. Out of town the hero read `$2,729` / `$2,717` /
`$2,859` against a correct `$3,379`. The string `5,944` appears exactly once in the 155 KB in-town
DOM — **in the snapshot card, never in the hero**.

Consequence: `assert both not in doms["outoftown"]` derives all its force from the snapshot card
and the row list.

> **If a future edit wired the dead `townLevyIfInTown()` into `#heroV` alone — reinstating the exact
> $5,944-instead-of-$3,379 defect on the primary trust surface — the hero's dumped text would be
> some arbitrary intermediate and would almost certainly not contain `5,944`. The test passes and
> the 76% overstatement ships again.**

**Why the tests miss it.** This *is* the test.

**Smallest remedy.** Add `--force-prefers-reduced-motion` to the argv at `:1938` — verified: it
makes `REDUCED` true, `draw()` passes `animate=false`, `setFigure` takes the early return at
`:1312`, and `#heroV` reads `$5,944`. Then assert **by element**, not by whole-page substring:
`re.search(r'id="heroV">([^<]*)', dom)`.

---

### F-04 — The browser gate never renders the printed takeaway or the copied text

**Defect.** Both artefacts that *leave* the page are built inside click handlers, so a `--dump-dom`
capture contains neither — yet the test's docstring cites the takeaway as one of the surfaces its
assertions cover.

**Sites.** `tests/test_data_integrity.py:1917-1920` (the docstring claim); `assets/app.js:1294-1295`
(`printTakeaway()` is the only caller of `refreshTakeaway()`, the only caller of `takeawayHTML()`);
`assets/app.js:1047-1071` (the copied text, built inside `copySnap`).

**Failure — measured.** `id="takeaway"` is absent from the dumps for both locations. Reproducing
F-01's takeaway rows required a probe page that calls `takeawayHTML()` directly; reproducing F-19's
copied text required rebuilding the handler's own expression. So every assertion in
`test_out_of_town_pages_never_show_the_town_levy` — including `assert town not in doms["outoftown"]`
— is blind to the one-page sheet a resident prints and carries into a board meeting, and to the
block they paste into an email to a commissioner.

**That is precisely how the takeaway's copy of the original bug survived the first audit.**

**Smallest remedy.** Better than clicking: expose the takeaway's row list and the copy-text builder
as **pure string-returning functions** and assert their output in a JS unit test. Then click
`#printSnap`/`#copySnap` in the browser gate as a belt-and-braces check.

---

### F-05 — Both single-source helpers are dead code; the guard test asserts nothing

**Defect.** `townLevyIfInTown()` and `totalPropertyTax()` have zero call sites, while the Python
test that names the first is a `for … : pass` loop.

**Sites.** `assets/app.js:726-729` (+ the comment at `:723-725` documenting the intent), `:735-739`,
`tests/test_data_integrity.py:1907-1909`, `:1911`. Duplicated total: `assets/app.js:906-908` and
`:1169-1171`.

**Failure.** A maintainer reads `:723-725` — *"Kept as the unconditional town levy, for the 'one
cent on the tax rate' and FY-scenario rows … Never use it for the headline — that is the bug
above"* — and reasonably concludes the one-cent rows are routed through a named, documented helper
that a test polices. **Neither is true.**

Second-order: `totalPropertyTax()` uses the **opposite rounding rule** from the two live sites. At a
$250,000 in-town home the page renders `$2,973` (rows $1,283 + $1,690, each rounded);
`totalPropertyTax()` returns `1282.5 + 1689.5 = 2972.0`, which `usd()` renders as `$2,972`. Any new
surface wired to the obviously-named helper publishes a total **$1 below the hero** — on a page
whose own comment at `:904` was written to close exactly that $1 gap.

Third-order: `assert js.count("townTax()") >= 4` counts the declaration line itself, so it holds
even if callers drop to three.

**Smallest remedy.** Make `totalPropertyTax()` the single source both call sites use
(sum-of-rounded-rows), or delete it. Replace the no-op loop with the one assertion that would have
caught F-01: **fail if `homeValue / 100 * 0.01` appears anywhere outside a single named helper.**

---

### F-06 — Fund balance selected by literal `forYear(…, 2027)`

**Defect.** Two surfaces pin the "Right now" fund-balance percentage to the literal year 2027 while
two others **in the same file** already read `index.headline_fiscal_year`.

**Sites.** `assets/app.js:1884-1885` (`renderHealth`), `:1213-1214` (`takeawayHTML`). The correct
pattern, 34 lines below the first: `:1918` `const headlineFy = (state.data.index || {}).headline_fiscal_year || 2027;`
Also `:2395`. Data: `data/index.json` `"headline_fiscal_year": 2027`.

**Failure.** `headline_fiscal_year` becomes 2028 and the FY28 message republishes FY2027 as a 71%
*estimate*. `forYear(…, 2027)` returns that estimate, and section 03 opens with an unlabelled
present-tense claim: "Right now, yes — the town holds savings worth **71.0%** of a year's spending"
— a closed prior year's estimate presented as the current position, on the same screen as a timeline
that correctly calls FY2028 "This year's plan". The printed takeaway (`:1218`) carries the same 71%
onto paper, also unlabelled.

If FY2027 is dropped entirely, `forYear` returns null and the `|| one(...)` fallback at `:1885`
fires; `one()` breaks ties by source-document year only (`:203-207`), so with all rows from one
document it returns `rows[0]` — whichever year happens to be first in `facts.json` — presented as
"Right now".

**Smallest remedy.** One `headlineYear()` helper and one `currentFundBalance()` consumed by both
surfaces; drop the `|| one(...)` fallback so a missing headline-year row **withholds** the sentence.

---

### F-07 — FY2029 cliff paragraph attached by literal year

**Defect.** The paragraph converting the projected shortfall into cents-on-the-rate is bolted onto
whichever timeline card is FY2029, while the figures it prints come from facts whose own fiscal year
is read from the data.

**Sites.** `assets/app.js:2386-2390`. The already-corrected sibling twenty lines above: `:2357`
`const needYearDef = need ? forYear('general_fund_surplus_deficit', need.fiscal_year) : null;`

**Failure.** The FY28 message moves the cliff to FY2030. The FY2029 card — now a milder projected
deficit — still receives the paragraph: "FY2029 · projected … Closing that gap would take over
**12 cents** on the rate — the town's own example is **$528 a year** on a $400,000 home",
attributing FY2030's cliff arithmetic to FY2029's smaller gap. The answer paragraph twenty lines
above correctly names FY2030. Two statements about the same cliff, two different years, one screen.

**Smallest remedy.** `f.fiscal_year === need.fiscal_year`, and additionally require
`scenario.fiscal_year === need.fiscal_year` before rendering.

---

### F-08 — Capital-plan split is positional and its year range is prose

**Defect.** `already` and `window7` are computed by **array position** (`amounts[0]` = "current
project budget", `amounts.slice(1)` = the plan window) and printed beside a total that is never
checked against them, under a year range hardcoded in prose while `plan_window` sits unread in every
record.

**Sites.** `assets/app.js:2271-2275`, `:2279-2282`. The comment at `:2260-2270` records that this
split was added to *fix* a $14.5M misattribution. The check it should mirror: `:1404-1409`.

**Failure — the routine annual one.** Next year's CIP shifts the window to FY2028–FY2034 with the
array still 8 long. The split stays arithmetically self-consistent, nothing warns, and the page
publishes correct numbers under a wrong year range.
**Failure — the shape change.** The town drops the standalone current-budget column, leaving seven
entries: `amounts[0]` is now FY2028 spending, reported as money "**already in current project
budgets**" — a real number under a false description of what it is. That is the same $14.5M-class
error the split was written to correct.

**Smallest remedy.** Render the range from `plan_window`, assert
`already + window7 === s.total_planned_cost` beside the sentence (the check `renderPaysFor` already
performs), and assert `amounts.length === 8` in the ETL.

---

### F-09 — "Your property tax rate is not going up this year"

**Defect.** The health card derives a green ✓ purely from `townRateChange()` and states it in the
**second person**, so it asserts a fact about the reader's own bill that is false for **every**
reader — the county's rate rose 3.75 cents.

**Sites.** `assets/app.js:1930-1935`. `renderHealth` (`:1881`) reads no reader state at all and is
absent from `refreshDependents()` (`:1329-1347`). Contradicted on the same page by `:945` and
`:1206-1207`.

**Failure — rendered.** Section 03 renders, out of town:

```
[ok] ✓ Your property tax rate is not going up this year
       It stays at 51.3 cents per $100 of value in FY2027, the same as FY2026.
```

For an out-of-town household the only rate they pay went **up**, from 63.83 to 67.58 cents —
$187.50 more a year on a $500,000 home. For an in-town household the combined rate went up by the
same 3.75 cents. **The page awards a pass on a claim it disproves two sections earlier.**

**Smallest remedy.** Drop the possessive — "**The town's** property tax rate is not going up this
year" — which needs no location input and matches the section heading ("Is the town's money in good
shape?"). Optionally add a sibling item built from `county_tax_rate_increase_cents`.

---

### F-10 — A missing county rate collapses to "$0 in property tax this year"

**Defect.** `total = annualR + (countyR || 0)` turns an absent county rate into a **measured zero**,
bypassing `setFigure`'s own withholding path.

**Sites.** `assets/app.js:906-908`, `:1030`, `:1062`, `:1171`. The correct behaviour, never reached:
`:1311` `if (target == null) { el.textContent = '—'; return; }`. The correct rule, in dead code:
`:737` `if (t == null) return null;`.

**Failure.** `county_property_tax_rate` has exactly one fact in `facts.json`. If it is dropped,
renamed, or fails a unit check in a rebuild, then with `?where=outoftown` the hero renders **$0**,
`#heroN` is empty, no rows appear for either government, and the snapshot headline reads "**$0 in
property tax this year** … Based on a home assessed at $500,000, outside town limits." The copied
text carries "Town property tax: $0/yr" off the page with the site's sources attached.

Worse: the callout two elements above still says "Orange County's rate rose 3.75 cents, which adds
**$188 a year** for a home like yours" — driven by the separate `county_tax_rate_increase_cents`
metric, which survives the loss of the rate. **The page publishes "$0 in property tax this year"
directly beneath its own claim that the county rise costs this household $188.**

**Smallest remedy.** Route the hero and the snapshot through a total that returns `null` when an
applicable component is unknown, so `setFigure` prints `—`; suppress the snapshot figure and the
copy text when it is null.

---

### F-11 — Fund shares divide by the sum of parts, labelled "of the total"

**Defect.** Every bar width and legend percentage is `p.value / sum * 100` labelled "% of the
total", while the same function ten lines later renders a ⚠ branch for exactly the case where `sum`
differs from the published `total_budget`.

**Sites.** `assets/app.js:1395` (bar widths), `:1401` (legend label), `:1404-1409` (the warning).

**Failure.** The three funds sum to $36,420,539, exactly `total_budget`, so it is correct today.
Publish an FY2028 `total_budget` of $38,000,000 against the same fund rows — the audited-vs-budget
classification gap the site documents elsewhere is exactly this shape — and the page renders
"⚠ The three funds add to $36.42M, which differs from the stated total $38.00M by $1.58M"
*immediately below* a legend reading "General Fund $19.48M — **53.5% of the total**". Against the
total the page just named, it is 51.3%.

**Smallest remedy.** `const denom = diff < 1 ? total.value : sum;` for the legend, and switch the
label to "% of the three funds" when they disagree. **The bar widths at `:1395` must keep dividing
by `sum`** — a stacked bar has to fill — so the two uses are genuinely different and must not be
collapsed into one.

---

### F-12 — "So next year costs you about +$X" cannot include a town rate rise

**Defect.** `addedAll` is built inline from the county increase plus twelve months of utility
increase; `townRateChange()` has already been called eleven lines earlier and its `rc.delta` is used
only as a text label, never entering the total the row presents as the whole year-over-year
increase.

**Sites.** `assets/app.js:983-988`; `rc` in scope at `:932`, used as prose at `:935`. Fourth inline
copy of the `value/100 * rate/100` formula at `:984`, alongside `:721`, `:728`, `:733`.

**Failure.** The town rate is flat at 51.3 cents today, so the row is right **by luck**. Publish an
FY2028 `property_tax_rate` of 55.3 with no county change, in-town $500,000 home: `rc.delta` = 4.0,
the callout correctly renders "The town's rate rises 4 cents", and the row directly above it still
says "So next year costs you about **+$122 more**" — omitting the $200 town increase it just
announced. Understated by 62%.

**Smallest remedy.** `annualBillChange({homeValue, location, townDeltaCents, countyIncreaseCents,
utilityMonthlyDelta})` as a pure function taking the town delta as a **required** argument.
**It must be location-gated** — adding `rc.delta` unconditionally would quote a town rate rise to
an out-of-town household, which is F-01 all over again.

---

### F-13 — "What's coming" timeline pinned to `>= 2027`

**Defect.** `renderComing` filters with the literal `f.fiscal_year >= 2027`, hardcoding the boundary
that `renderHealth` deliberately reads from `index.headline_fiscal_year`.

**Sites.** `assets/app.js:2376`. Year-aware code inside the same map callback: `:2395`. The rule,
correctly implemented in the other section: `:1916-1920`.

**Failure.** `headline_fiscal_year` advances to 2028. Section 04 "What's coming for you" still opens
with a FY2027 card whose heading comes from the year-aware `hFy`, so it renders "FY2027 · budget /
**Projected** / The town plans to spend $466,231 more than it collects" — a closed, adopted budget
year filed under "What's coming" **and labelled a projection**, while section 03 three functions
away correctly starts at FY2028.

**Note.** `tests/test_data_integrity.py:288` contains a comment celebrating exactly this fix being
applied elsewhere — *"The hardcoded 2027 this replaced would have kept testing FY2027 forever while
the site auto-advanced"*. The lesson was written into the suite and not applied to `:2376`.

---

### F-14 — `|| 240000` fabricates a divisor under the card's own "n/a"

**Defect.** The FY2029 cliff card converts dollars to cents-on-the-rate by dividing **twice** by
`v.her_penny_assumption || 240000`; the literal is the FY2027 revenue-per-cent transcribed into the
JavaScript, and the note 28 lines above uses a different expression that renders "n/a" for the same
missing value.

**Sites.** `assets/app.js:2522-2525` (both divisions), `:2494-2495` (the honest note).

**Failure.** `verification.her_penny_assumption` disappears from `workbook_b.json` — the repo's own
test at `tests/test_data_integrity.py:932` warns that this exact rename has happened before. The
card then renders two contradictory statements: "The conversion uses the town's own published figure
of **n/a** raised by one cent", and immediately below, "$3,567,819 in that single year — about
**14.87 cents** on the tax rate, or roughly **$743 a year** on a home like yours". A sourced-looking
cents figure whose divisor the same card just admitted it does not have — on a site whose one rule
is that no number is published unless it traces to a document and a page.

**Scope correction.** A tax-base-growth variant is impossible: `etl/s96_workbook_b.py:142-143,298`
sets `her_penny_assumption` from the `revenue_per_cent_of_tax_rate` fact itself, so it advances
automatically. The only trigger is the metric disappearing. The drivers rows at `:2501-2507` use
`r.cents_equivalent` from the workbook, not this constant, so only the cliff card is exposed.

**Smallest remedy.** `const perCent = v.her_penny_assumption; if (!perCent) return;` — withhold the
sentence rather than fall back, the discipline the rest of the file follows.

---

### F-15 — Audited variance sentence has no sign branch

**Defect.** `underPct` is interpolated into a sentence whose wording assumes the sign, while the
revenue figure on the very next line **does** branch on its sign.

**Sites.** `assets/app.js:1971`, `:1983`; the correct pattern at `:1985`.

**Failure.** Publish a year with actual $17,000,000 against a final budget of $16,761,617:
`underPct` = −1.42, `pctPlain` renders `−1.4%`, and the panel titled "**Did they spend what they
said they would?**" publishes "the town budgeted $16,761,617 and actually spent $17,000,000,
**−1.4% less than planned**" — a double negative most readers parse as an underspend, about a named
board.

**Caveat on likelihood.** A General Fund total exceeding final appropriations violates the NC Local
Government Budget and Fiscal Control Act, so this is not the ordinary next year. It stays on the
list because it is the one sentence on the page whose entire job is the sign of a variance.

---

### F-16 — The 50% fund-balance floor is hardcoded in five places

**Defect.** A town policy number that exists in the data only as free text **inside a quotation** is
hardcoded in five places, one of which drives a ✓/! verdict.

**Sites.** `assets/app.js:1890` (`const FLOOR = 50`, verdict logic at `:1905-1908`), `:2200` (chart
reference line), `:2385` (`bl.value < 50` in the timeline), `:2682` (glossary), and **`:1218` — the
printed takeaway**, a raw string with no constant behind it. The only machine-readable trace is
prose: `facts_household.json` `town_statements.savings_floor`. No `fund_balance_floor_pct` metric
exists.

**Failure.** The board revises the policy to 60% and the ETL picks up the new sentence. Section 03
quotes the town saying "no lower than **60%**" in a blockquote at `:1958` — data-driven — directly
beneath a green tick reading "✓ **Savings are above the town's own floor** … The town's stated aim
is no lower than **50%**". The page contradicts the quotation it just printed, awards a pass on a
retired threshold, draws the chart line at the old figure, omits the "below its own floor" warning
that 54% < 60% should trigger, and carries the retired figure onto the printed sheet.

**Smallest remedy.** Publish `fund_balance_floor_pct` as a numeric fact cited to the same page as
the quotation; read it once into `floorPct()`. Add a data test asserting the numeral inside the
`savings_floor` quotation matches the metric.

---

### F-17 — One optional dataset 404 amputates sections 04–06

**Defect.** `boot()` deliberately lets non-CORE datasets fail alone, but three renderers dereference
them unguarded; the throw escapes `render()`, and the catch handler **then throws too** because
`#loading` was already removed — so the page truncates with no error.

**Sites.** `assets/app.js:2422` and `:2614` (`state.data.requests`), `:2211`
(`state.data.projections.comparisons`), `:3040` (`$('#loading').remove()` before `render()`),
`:3076` (`$('#loading').innerHTML` in the catch). Contract: `:3024-3032`.

**Failure — measured.** Serve with `data/datasets/requests.json` returning 404 — exactly the case
`boot()` logs and continues past. `id="you"` present; `id="coming"`, `id="voice"`, `id="receipts"`
**all absent**; `#verifySlot` never replaced, so the "How you can check this" card is gone;
`#footMeta` empty; `#chipCount` still showing its static markup placeholder "**Verified figures**";
no `#loading`, no error text anywhere.

A 40 KB page that looks finished, still carrying the masthead's promise at `index.html:80` —
"Every figure names the document it came from" — above an unqualified "Verified figures" chip, with
the **entire receipts section that substantiates that promise silently deleted**. No wrong number is
published; the worst-case failure for this project's one rule is published instead.

**Scope.** `revenue` (`:1541`), `structure` (`:1602`), `audited` (`:1967`), `tradeoffs` (`:2546`)
and `utility` (`:664`) **are** guarded. The fix is three guards, not a general audit.

---

### F-18 — Utility fallback names stormwater in a total that excludes it

**Defect.** `utilMonthly()`'s fallback returns `total = water + sewer` with **no stormwater
component**, while four surfaces each carry their own hardcoded sentence naming stormwater as part
of that same number.

**Sites.** `assets/app.js:688-689` (the fallback), `:1005`, `:1010-1011`, `:1034`, `:1065`.

**Failure.** `utility` is optional (`:3024`), so a 404 leaves it null and the fallback fires — and it
*also* fires with the dataset present if `rate_sets.water_inside`/`sewer_inside` are renamed, since
`:667-669` falls through on a missing key. An in-town reader then gets `u.total = 3.72 + 5.24 =
8.96` and the page prints "water, sewer and the stormwater fee together add about **$8.96 a
month**", and in the copied text "Water/sewer/stormwater increase: **+$8.96/mo**". The stormwater
block's own published rise is $105 → $120 per year; the exact path gives $10.21/mo. **The two paths
differ by exactly the omitted fee.** If both underlying facts are also absent, `total` is `0` and
the page prints "Plus about **$0** more over the year as water, sewer and stormwater rates rise" — a
sourced-looking zero.

---

### F-19 — The copied snapshot exports the town rate as "Tax rate"

**Defect.** `copySnap` builds a **third** hand-written row list with no location branch: it always
emits a "Town property tax" line, always titles the block "Town of Hillsborough — my share", and
always states the **town's** rate as "Tax rate".

**Sites.** `assets/app.js:1057` (header), `:1062` (town line), `:1066-1067` (rate line). Contrast the
gated hero sub-line at `:912-919`.

**Failure — captured from the real builder at `?home=500000&where=outoftown`:**

```
Town of Hillsborough — my share, FY2027
Home assessed at $500,000 (out of town)
Town property tax: $0/yr
Orange County property tax: $3,379/yr
Total property tax: $3,379/yr ($282/mo)
Water/sewer/stormwater increase: +$18.71/mo (about $225/yr)
Tax rate: 51.3 cents per $100 — unchanged for FY2027
Sources: FY27 Budget Message.pdf; …
```

51.3 cents on $500,000 is $2,565, which **does not reconcile** with the $3,379 three lines above it.
The reader's actual rate — 67.58 cents, up 3.75 — never appears, the whole artefact is titled with
the government they do not pay, and none of `OUT_OF_TOWN_CAVEAT` (the fire district tax the page
tells them about on screen) travels with it.

**Failure — in town.** The same line is wrong: an in-town household is charged 51.3 + 67.58 = 118.88
cents, and "Tax rate: 51.3 cents" fails to reconcile with "Total property tax: $5,944/yr". **Fixing
this out-of-town only leaves half the defect.**

---

### F-20 — localStorage fabricates "Welcome back"

**Defect.** `saveHome()` persists the **defaults** on a first visit where the reader touched nothing,
and `loadHome()` sets `state.returning = true` for any parseable stored value.

**Sites.** `assets/app.js:44-57` (`state.returning` set unconditionally at `:55`), `:68-74`
(`keep()` returns `state[key]` — the defaults — when nothing was touched), `:1086` (`saveHome()`
called unconditionally on every `renderYou()`), `:852-856` (the banner).

**Failure — reproduced with two fresh browser profiles.** Two consecutive plain visits, no query
string, no interaction: visit 1 shows no banner; visit 2 shows "**Welcome back — showing figures for
a home assessed at $400,000, inside town limits.**" The reader has never typed a value and has never
said they live in town.

On the share-link route it is worse: a reader who arrives on `?home=750000&where=outoftown&gal=9000`
— correctly told "These are the sender's figures, not yours" — has `"{}"` written on the first
paint, and on their next plain visit is told the site remembers them as an **in-town** $400,000
household. The page asserts a memory it does not have, on the one control the whole calculator hangs
off, and on **the exact question whose mis-answer produced the original 76% overstatement**.

---

### F-21 — The explorer's personalised share omits the slice year

**Defect.** `yourTax` is always the **current** published town levy, but it is apportioned by the
department shares of whatever `(fund, fy, basis)` slice the reader selected; the tax-funded branch
omits the year that the non-tax branch one line below states.

**Sites.** `assets/app.js:1762`, `:1785-1791`, `:1798`, `:1805-1806`.

**Failure.** An in-town reader with a $500,000 home switches the year dropdown to "FY2029
projected". The panel reads, in the present tense, "Of the **$2,565** you pay the town, this is
roughly how it divides", and each row shows e.g. "Police $5.24M · **$742 of yours**" — a real
current tax bill carved up by a *projected future budget's* department shares, with no year named
anywhere in the personalised claim. The very next branch of the same ternary does name it.

---

### F-22 — Utility rows labelled "FY2027 rates" / "on FY2026" from literals

**Sites.** `assets/app.js:953`, `:960`, `:1010`.

**Failure.** `etl/s93_utility_rates.py` re-runs against the FY28 fee schedule and emits the same JSON
shape with new charges. The calculator then shows "Your water bill — 4,000 gal/month, in town ·
**FY2027 rates** — $39.42/mo" where $39.42 is the FY2028 rate, on a page promising "Every figure
names the document it came from."

**Correction to the evidence.** The dataset **does** carry the year: `utility_rates.json` has
`fiscal_year` on every rate set's `current` and `recommended` blocks, plus a `basis` field. Only the
stormwater block lacks one. The remedy is a two-line read, not a schema change.

---

### F-23 — The glossary hardcodes 51.3 cents and a $513 worked example

**Sites.** `assets/app.js:2683`. Live data-driven path for the same value: `:720-721`.

**Failure.** The town adopts 54.0 cents for FY2028. The hero, the callout and the printed sheet all
move; the glossary in section 06 — the section headed "Where every number came from" — still teaches
"At **51.3 cents**, a $100,000 home pays **$513** a year to the town." A reader who uses that worked
example to sanity-check their own bill gets a figure 5% low and concludes the calculator is wrong.

**Scope note.** The adjacent claim at `:2689` — "The audited record on this page runs from FY2018 to
FY2025" — is **correct today** and is latent staleness, not an error.

---

### F-24 — "Two governments, one bill" rendered unconditionally

**Sites.** `assets/app.js:1682-1685`; the whole function `:1670-1701` never reads `state.location`.
The adjacent paragraph that *does* branch: `:1356-1357`.

**Failure — verified in the out-of-town DOM.** Section 02 opens "You pay **no town property tax** —
the home is outside the town limits", and the same section reads "**Your property tax funds two
separate governments** … Orange County charges 67.58 cents per $100 and the town 51.3 cents — **the
county's is the larger share**". For that household the town's 51.3 cents is not part of their bill,
so the comparison is not merely inclusive of a rate they do not pay — it is meaningless. Meanwhile
`OUT_OF_TOWN_CAVEAT` has just told them their real second levy is a fire district tax the page does
not compute. The honest out-of-town statement is **one** government plus an unresolved district.

---

### F-25 — Hero caption "town and county combined" over a county-only figure

**Defect.** The caption directly above the primary figure is written once into `panel.innerHTML`,
branches only on whether a county rate exists, and is **never rewritten by `draw()`**.

**Sites.** `assets/app.js:809-813`. `draw()` writes `#heroV` and `#heroN` (`:911-912`); nothing
writes `.cap`.

**Failure — rendered.** At `?home=500000&where=outoftown` the hero reads `$3,379` under
"Your property tax, per year — **town and county combined**". $3,379 is 67.58 cents on $500,000 —
county only. Clicking "No, outside" leaves the caption in place, because it lives in the
constructed-once layer while the number lives in the redraw layer.

**Mitigating.** `#heroN` one line below correctly says "all of it to Orange County … No town
property tax", so the correction is same-screen. **The finding is the layer split**, not the likely
misreading.

**Smallest remedy.** Give the caption an id and set it inside `draw()` from the `inTown` branch that
already decides the hero sub-line. One line.

---

### F-26 — Explorer default year + hardcoded reconcile claim

**Sites.** `assets/app.js:1739-1743` (the default), `:1776-1780` (the warning).

**Failure.** Once FY2028 slices ship, every reader who never touches the year dropdown is reading
last year's plan by default. And if a future rebuild flips General Fund FY2027 budget to
`verified: false`, selecting that slice renders a box saying, in one breath, "The account detail for
**FY2027 budget** differs from the total the town publishes for it" and, in the next, "the **FY2027
budget** figures reconcile exactly."

**Correction.** **Not reachable today** — `lineitem_validation.json` has General Fund 2027 budget
`verified: true`. Latent, not live.

---

### F-27 — Transfer schedule selected by literal 2027

**Sites.** `assets/app.js:1488-1490`, `:1499` (hardcoded caption).

**Failure.** `transfer_schedule.json` advances to FY2028. Section 02 renders normally **minus one
disclosure** — nine dollar cells and their sources gone, no error, no console warning, no test
failure. Nobody reviewing the site can tell whether the town stopped publishing transfers or the
page stopped reading them.

**Severity note.** Neither branch publishes a wrong figure. It earns its place as one more instance
of the year-literal class, not on reader harm.

---

### F-28 — "about a third" is a hardcoded prose ratio

**Sites.** `assets/app.js:1628-1631`. Data: `structure.json`
`already_shared.current_fee_pct_of_collections` = 0.5, `county_fee_study_peer_average_pct` = 1.5.

**Failure.** 0.5 / 1.5 is exactly a third today. Raise the town's fee to 0.75% and the page
publishes "at **0.75%** of collections the town currently pays **about a third** of the **1.5%**
average" — one half described as one third, in a paragraph whose whole point is the size of that
gap.

**Scope.** Swept for the pattern (`a third`, `a quarter`, `a fifth`, `about half`, `twice`,
`three times`); the only other hits are in comments. **A single site, not a class.**

---

### F-29 — Four live WCAG scrollable-region failures

**Defect.** `markScrollableRegions()` marks an overflowing table keyboard-reachable, but it only
ever runs against the DOM as it stands. Neither `disclosure()`'s toggle handler nor `card()`'s "Show
the numbers" button calls `scheduleScrollableScan()` after building its contents, so **every table a
reader actually opens is created after the last scan and never marked**.

**Sites.** `assets/app.js:427-429` (`disclosure`'s toggle handler), `:386-391` (`card`'s toggle
handler). The scan itself: `:3105-3127`. The comment at `:3088-3104` records that this code exists
precisely because "an audit found two SERIOUS instances at 390px and 320px" — M-03 of the
2026-08-01 audit.

**Failure — measured at 390 px**, after opening the disclosures the way a reader does:

```
scrollable candidates in DOM : 12
actually overflowing at 390px: 5
of those, keyboard-reachable : 1
WCAG scrollable-region-focusable FAILURES: 4
  - Transfers out of each fund, and where they went…
  - Audited General Fund, year ended 30 June 2025…
  - Every table requested, and whether it has been filled in.
  - The 118 files catalogued behind this project…
```

There are **34 `<details>` elements and 0 are open at load**, so the fix as written covers roughly
two tables out of thirty. `refreshDependents()` does call `scheduleScrollableScan()` (`:1337`), so
the regions are incidentally repaired if the reader later changes their home value — which means the
failure is intermittent, and a manual check that happens to touch the calculator first will not
reproduce it.

**Why the tests miss it.** No test opens a disclosure; no test runs at a phone viewport.

**Smallest remedy.** Call `scheduleScrollableScan()` at the end of both toggle handlers. Two lines.
Then gate it: render at 390 px, open every `<details>`, and assert zero overflowing regions lack
`tabindex`.

---

## Considered and rejected

Thirteen findings were killed by adversarial verification. They are recorded so they are not
re-raised. Three were the auditor's own, which is the point of the exercise.

| Claim | Why it was rejected |
|---|---|
| **The share link rewrites the reader's figure below $1,000.** `shareUrl()` clamps to [1000, 1e9]; the input clamps to [0, 1e9]. Typing 500 shows a bill at $500 and emits a link that opens at $1,000. | **Mechanism confirmed, impact refuted.** The slider's `min` is 50000, so the only route is typing a sub-$1,000 assessment — a value the page already renders as self-evidently absurd, and which the sender sees before copying. No figure *about Hillsborough or Orange County* is misstated on either screen. The auditor also misread the comment at `:129-134`: it governs the `shareUrl`↔`loadShared` round trip, and **those two do match exactly**. Downgraded to a consistency note; the constants are unified in `assets/domain.js` at zero cost, and the input's behaviour is left alone. |
| **Section 01's blurb tells an out-of-town reader the page "covers both bills a Hillsborough household pays".** | The sentence's subject is the page's coverage, and "a Hillsborough household" is third person. No dollar figure attaches, both quoted rates are correct and sourced, and it sits **above** the question "Is your home inside town limits?" as framing for a question not yet answered. Contrast F-25, where the caption sits directly on top of the reader's own figure and labels it. *Residual, not pursued: for a **returning** out-of-town reader the answer is already restored from localStorage, and the blurb still reads as though both apply.* |
| **The snapshot's "$0 to the town" renders a not-applicable as a measurement.** | Refuted. The caption is inside the `#snapshot` innerHTML that `draw()` rewrites, so it tracks the toggle live; it renders "$0 to the town, $3,379 to Orange County … Based on a home assessed at $500,000, **outside town limits**" — every figure correct, the location stated on the same line. The comparison to the explorer's guard does not transfer: there "$0 of yours" was repeated against **every** department row of a fund the reader **does** fund, with no adjacent explanation. |
| **The stormwater fee is charged to out-of-town households on a source with no inside/outside dimension.** | The mechanism is real (`:670-672` ignores `loc`; the dataset's stormwater block is flat) but the premise — that the fee does not reach parcels outside the limits — is **unproven**. The town demonstrably serves out-of-town water/sewer customers, the fee is billed per ERU on the same bill, and page 231 prints a single residential figure with no split, on the same page that *does* split water and sewer. Rendering one undifferentiated published fee is not provably publishing a wrong number. |
| index.html hardcodes OCR counts · the explorer's personalised branch drops the year (duplicate of F-21) · stormwater unit conversion assumed monthly · the FY29 cliff's penny assumption (duplicate of F-14) · the audited underspend zero-fallback (subsumed by F-15) · project operating impact renders null as zero · revenue shares attributed to the wrong year · derived ratios pinned in prose (subsumed by F-28) | Either already correct in current code, unreachable, or a duplicate of a finding above. |

---

## Remediation order

Mapped onto the stated sequence. **No framework rewrite.**

### Step 1 — Extract pure domain functions

| Extract | Replaces | Closes |
|---|---|---|
| `townPolicyDollarsOnThisHome(homeValue, location, cents)` | 5 inline `oneCent` constants; the dead `townLevyIfInTown()` | **F-01** |
| `headlineYear()` reading `index.headline_fiscal_year` | literals at `:1213`, `:1884`, `:2376`, `:1489`, `:1740` | **F-06**, **F-13**, **F-26**, **F-27** |
| `propertyTaxBill()` — sum-of-rounded-rows, `null` when an *applicable* component is missing | duplicated blocks at `:906-908`, `:1169-1171`; the `\|\| 0` collapse | **F-05**, **F-10** |
| `annualBillChange({… townDeltaCents …})`, location-gated | inline `addedAll` at `:985` | **F-12** |
| `fundShares(parts, statedTotal)` returning share **and** denominator used | `:1395`, `:1401` | **F-11** |
| `budgetVariance(finalBudget, actual)` → `{pct, direction}` | `:1971`, `:1983` | **F-15** |
| `centsEquivalent(dollars, pennyYield)` returning null on a missing yield | both `\|\| 240000` | **F-14** |
| `splitProjectCost(projects)` + a `plan_window` parse | `:2271-2275`, `:2279-2282` | **F-08** |
| `floorPct()` reading a new `fund_balance_floor_pct` fact | `:1218`, `:1890`, `:2200`, `:2385`, `:2682` | **F-16** (needs step 4's half) |
| `utilityBill()` returning a **named component list** | fallback at `:688-689` | **F-18** |
| `rateSentence(location)` | `:1066`, and the hero caption's branch | **F-19**, **F-25** |
| `loadHome()` returning what it adopted; `saveHome()` writing only touched fields | `:44-57`, `:68-74`, `:1086` | **F-20** |

### Step 2 — Add JavaScript unit tests

There are currently **zero**. Each of these only becomes writable once step 1 gives it something to
call. Every one must be proven to **fail** against the pre-fix behaviour before it is committed —
the suite already carries one vacuous test (F-05) and that is exactly how the out-of-town rule
looked guarded when it was not.

### Step 3 — Split renderers by section

Extracting the shared calculations is the bulk of the work; splitting is what stops them being
re-inlined.

- Pull `draw()`'s row-list construction, `takeawayHTML()`'s row list, and `copySnap`'s text builder
  onto **one row-model function** that each renderer formats differently. That single change closes
  F-01's takeaway sites, F-12's screen/paper divergence, and F-19 at once — and removes the
  mechanism by which the original bug survived in four surfaces.
- Give `renderHealth` and `whoProvidesWhat` a location parameter and register them in
  `refreshDependents()` — **F-09**, **F-24**. Neither currently repaints on the toggle.
- Guard the three unguarded optional-dataset dereferences and move `$('#loading').remove()` to after
  `render()` returns — **F-17**.
- Make the hero caption part of the redraw layer — **F-25**.
- Add `scheduleScrollableScan()` to both toggle handlers — **F-29**.

### Step 4 — Versioned dataset schema

Findings that **cannot** be closed in JavaScript, because the data does not carry what the page needs:

| Finding | Schema change |
|---|---|
| **F-02** | Year-neutral field names — or read the `years[]` / `amounts[]` `tradeoffs.json` already publishes. Also `mfas_conformance.json`, where `general_fund_fy2027_budget` is year-keyed while its sibling is not. |
| **F-08** | `amount_columns: ["current_budget", 2027, …]` in `projects.json`; assert `len(amounts) == 8` and parse `plan_window`. |
| **F-16** | Publish `fund_balance_floor_pct` as a numeric fact cited to the same page as the quotation. |
| **F-22** | Add `fiscal_year` to the stormwater block; the rate sets already carry it. |

### Step 5 — Browser smoke / calculator / a11y tests in CI

1. **`--force-prefers-reduced-motion`** on the chromium argv, plus per-element assertions — **F-03**.
   *Without this, every browser assertion below is written against a nondeterministic sample.*
2. Assert the **takeaway** and the **copied text** for both locations — **F-04**, and the
   takeaway/copy halves of F-01 and F-19.
3. Extend the out-of-town gate to assert no `on your home` / `for a home like yours` / `for you` /
   `on this home` dollar string — **F-01**.
4. Boot with each non-CORE dataset 404'd and assert all six section ids survive — **F-17**.
5. Boot with `county_property_tax_rate` removed; assert the hero reads `—`, not `$0` — **F-10**.
6. Two-visit localStorage test — **F-20**.
7. Render at 390 px, open every disclosure, assert zero unreachable scrollable regions — **F-29**.
8. **Replace the no-op loop** at `tests/test_data_integrity.py:1907-1909` with the assertion that
   would have caught F-01: *fail if `homeValue / 100 * 0.01` appears outside a single named helper.*
   Fix `js.count("townTax()") >= 4` to exclude the declaration line — **F-05**.

### Not closed by the stated sequence

Three findings need their own step, because they are **copy** decisions, not code structure.

- **F-01's doctrine.** The comment at `:723-725` explicitly sanctions the unconditional town levy
  for these rows as "town POLICY comparisons". That comment is what a future maintainer will read.
  Extracting a pure function without rewriting the comment **and** the row wording re-opens the
  finding: the arithmetic can stay, but *costs you / on your home / for you / a home like yours*
  cannot. **This needs an editorial decision — what is a town-policy figure called when it is shown
  to a non-resident? — before the extraction is written.**
- **F-09** and **F-24** are sentences that are false as written regardless of how the code is
  organised. Both fixes are word changes (`Your` → `The town's`; one location branch), and neither
  is produced by extraction, testing or schema work.

---

## What this audit did not establish

- **It did not re-verify a single published figure against a source document.** Every dollar amount
  quoted above was read out of the rendered page or the datasets, and is used only to demonstrate a
  code path. Whether `51.3` is the town's actual FY2027 rate is the Python suite's job, not this
  audit's.
- **It did not execute the roll-forward scenarios.** F-02, F-06, F-07, F-08, F-11, F-13, F-16 and
  F-22 are traced through the code with the data held constant. They are argued from the source and
  the current datasets, not observed. The next fiscal roll is the real test, and the JS unit tests
  proposed in step 2 are how to run it early.
- **It did not test any browser but headless snap chromium 150**, at desktop and 390 px, with no
  assistive technology attached. F-29's four failures are `scrollable-region-focusable` by
  measurement of `scrollWidth`/`tabindex`, not by an Axe run.
- **It did not review `assets/style.css`** (1,163 lines) except where a rule affected whether a
  region overflows.
- **It did not assess the ETL.** M-04 is a frontend finding; the 2026-07-31 and 2026-08-01 audits
  cover the pipeline.
- **Severity is the auditor's judgement.** "Wrong number" and "wrong label" are calls about how a
  reader would take a sentence, and reasonable people will move some of these one row up or down.
  The file:line citations and the failure scenarios are checkable; the ranking is an argument.
