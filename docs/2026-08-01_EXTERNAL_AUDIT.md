# MFAS Full Code, Data, Numerical, and Frontend Audit

**Repository:** `oc-accountability/MFAS`  
**Branch / commit reviewed:** `main` at `8b1e75d1bd68a813e605f21b0630e3a21990e423`  
**Commit date:** 2026-07-31 21:30:02 CDT  
**Audit date:** 2026-08-01  
**Reviewer:** OpenAI Codex  
**Scope:** Python ETL, generated JSON and Excel artifacts, data lineage, numerical controls, static browser application, accessibility, performance, release process, security, documentation, personalization, and multi-county readiness.

## Executive Decision

MFAS has advanced substantially since the 2026-07-31 audit. The four previous high-severity build and provenance defects were addressed, the integrity suite increased from 94 to 111 passing tests, CI is active, the Excel outputs are deterministic, source identity is stable across renames, and the new digital-audit readers add meaningful evidence. The current main commit and GitHub Pages deployment match after line-ending normalization, and both the repository verification workflow and Pages deployment are green.

The product should **not be presented as a production-ready public standard yet**. A limited beta with a prominent limitations notice is defensible, but the primary personalized calculator currently publishes a materially wrong answer for a user who selects "outside town limits." The warehouse also contradicts its own traceability and confidence promises, and it contains scan-derived rows for years in which a digital original exists.

The launch decision is therefore **NO-GO until the Critical and High findings are closed**.

The most important findings are:

1. **Critical:** the out-of-town toggle does not remove Town of Hillsborough property tax. A $500,000 out-of-town home is shown as owing $5,944 instead of approximately $3,379 in countywide property tax, an overstatement of $2,565.
2. **High:** the workbook says it publishes 23,569 traceable facts, but its fact tabs contain 24,251 rows. Exactly 682 rows cite source IDs absent from `Source_Register`.
3. **High:** 1,110 warehouse rows are labeled `High` despite the workbook's own rules assigning OCR to `Medium` and workbook imports to `Working` unless officially confirmed.
4. **High:** the "digital original always wins" rule is not enforced in the final financial fact table. Thirty-six OCR rows remain in years held digitally; at least 16 are direct semantic duplicates of digital rows.
5. **High:** the public clone still cannot reproduce or independently verify the source extraction. The archive contains 118 registered documents, but all 118 `official_url` values are null and the approximately 945 MiB source set is absent.

No exposed secret, malicious workbook formula, known Python dependency vulnerability, high/medium Bandit issue, broken image, JavaScript runtime exception, or critical remote security exploit was found. The main launch risk is **incorrect or overstated civic-financial information**, not conventional application compromise.

## Scope and Assurance Boundary

The reviewed repository has 106 tracked files, including approximately 12,778 nonblank Python lines, a roughly 3,000-line JavaScript application, 1,075 CSS lines, 40 generated JSON files, and two generated Excel exports. The committed JSON is approximately 39 MB because it includes detailed statement and warehouse data.

"Checking all numbers" has three distinct assurance levels:

1. **Internal arithmetic:** whether components, totals, derived percentages, rate calculations, and cross-file counts agree with each other.
2. **Artifact provenance:** whether every exported row resolves to a registered source, page, extraction method, and defensible confidence level.
3. **Primary-source verification:** whether the number actually appears in the official PDF/XLSX at the stated location and has the stated meaning.

This audit completed levels 1 and 2 across the committed artifacts and repeated all machine-verifiable relationships. Level 3 could only be evaluated through evidence already embedded in the generated datasets because `sources/` is deliberately excluded and every official URL is blank. Consequently, this report can state that many figures reconcile and cross-check; it cannot honestly certify that every one of 24,251 fact rows was re-read from an official source document.

## Severity Model

- **Critical:** confirmed publication of a materially false primary user result or immediate compromise.
- **High:** a realistic path to materially misleading data, provenance, confidence, or aggregation.
- **Medium:** material reliability, accessibility, performance, documentation, or scaling defect.
- **Low:** bounded hardening, maintainability, or developer-experience issue.

## Previous Audit Remediation

| Previous finding | Current status | Verification |
|---|---|---|
| H-01 source ownership/confidence inferred from names | **Resolved for the source register and core fact export** | `data/source_registry.json` now stores durable `organization_id` and `source_authority`; initiative sources map to `ORG_INIT`; semantic tests cover the distinction. A separate warehouse-wide confidence issue remains below. |
| H-02 caches not bound to source content | **Resolved** | Cache paths now use source hashes through shared helpers, and mutation tests cover source replacement. |
| H-03 release gates not fail-closed | **Resolved** | `make verify` performs ETL plus tests; `.github/workflows/verify.yml` runs tests, compilation, frontend syntax, palette validation, and export-presence checks. The reviewed commit's `verify` run succeeded. |
| H-04 workbook built before merged facts | **Resolved** | `s90_build.py` and `s104_coverage.py` now precede the workbook stages; tests compare export semantics and deterministic hashes. |

Additional improvements since the prior review include deterministic XLSX ZIP timestamps, URL-scheme validation, improved scan selection and deskewing, digital-vs-OCR ground truth, direct Orange County ACFR extraction, accessible navigation semantics, and a pinned non-vulnerable pytest release.

## Critical Finding

### C-01: The primary calculator charges town property tax to out-of-town homes

**Evidence**

- `assets/app.js:691-704` calculates town and county property tax without consulting `state.location`.
- `assets/app.js:870-900` always includes and displays the town amount.
- The location control changes utility rates only (`assets/app.js:901-919`).
- In a live browser test at a $500,000 assessment:
  - `Yes, in town` produced `$5,944`: `$2,565` town plus `$3,379` county.
  - `No, outside` produced the same `$5,944` and the same town line.
  - The county-only calculation is `$500,000 / 100 x 0.6758 = $3,379`.
- The wrong total propagates into the snapshot, copied figures, share link, and printable takeaway because all use the same state and total helpers.

**Impact**

The site asks the user where the home is, promises "what your property tax actually costs you," and then ignores the answer for the headline calculation. The out-of-town result is overstated by $2,565 per year, about 75.9% relative to the correct county-only figure. This is the application's primary conversion and trust surface and must block launch.

The same state also leaves town-specific rows such as "one cent on the tax rate costs you" and the FY2029 town scenario visible to an out-of-town household without explaining that those are hypothetical town policy comparisons rather than components of that household's property-tax bill.

**Required fix**

Make town tax conditional on verified in-town status. Keep county tax countywide. Separate "your bill" rows from optional "town policy scenario" rows. Add pure calculation tests and Playwright tests for at least zero, $400,000, $500,000, maximum input, inside, outside, shared links, saved state, print, and copy. The outside test must assert that no town tax appears in any exported surface.

For the production product, replace the ambiguous manual boundary question with an optional address/parcel or map-based district resolver, while preserving a manual and privacy-preserving fallback.

## High-Severity Findings

### H-01: The workbook's fact count and source register do not cover its fact tabs

**Evidence**

The warehouse contains:

| Fact table | Rows | Rows with source ID absent from archive |
|---|---:|---:|
| `Fact_Financial` | 12,371 | 573 |
| `Fact_Metric` | 109 | 109 |
| `Fact_Statement_Line` | 11,771 | 0 |
| **Total** | **24,251** | **682** |

The nine absent IDs are `OC_ACFR_2021` through `OC_ACFR_2025`, `OC_CAFR_2018` through `OC_CAFR_2020`, and `SRC_OC_ACFR_2025`. They are legacy identifiers imported from the county research workbook. They may refer to real documents, but they do not resolve to any of the 118 IDs exported in `Source_Register`.

`etl/s104_coverage.py:117-127` counts rows by source ID, but `etl/s104_coverage.py:163-185` attaches counts only to known archive documents. `facts_total` at lines 215-218 then sums only those known-document rows. The foreign IDs are disclosed separately at lines 187-191 and 226-231, but excluded from the headline total.

`etl/s101_workbook.py:207-219` uses that incomplete coverage total on the cover. The resulting workbook says:

- "Every figure this project publishes ... traceable to a named document."
- "A figure that cannot be traced to a source document is not published at all."
- "23,569 published figures."

Its three fact tabs nevertheless contain 24,251 rows. The current test at `tests/test_data_integrity.py:1815-1818` checks only that the cover matches `coverage.json`, so the test makes the two incomplete representations agree instead of comparing the cover with the fact tabs. The manifest-source test at `tests/test_data_integrity.py:1327-1332` deliberately covers Hillsborough only.

The coverage matrix is also narrower than its name implies. `org_year` is populated only from `Fact_Financial` at `etl/s104_coverage.py:121-123`; `Fact_Metric` and `Fact_Statement_Line` are omitted from `facts_by_org_and_year`, `thin_org_years`, and `empty_org_years`.

**Impact**

The downloadable warehouse is the reusable product counties and analysts will consume. A downstream user cannot join 682 rows to the exported source dimension, cannot follow the cover's traceability promise, and is told a fact count that is 2.9% lower than the actual exported rows. Coverage and thin-year conclusions are correspondingly distorted.

**Required fix**

Normalize every imported source to the canonical SHA-backed source ID before publication. Preserve the research workbook's identifier in a separate `Original_Source_ID` or `Source_Alias` dimension. Fail the build if any published fact lacks a canonical source row. Compute the cover total directly from all exported fact tabs, and test the exact table counts. Label coverage matrices by table or include all fact tables consistently.

### H-02: Confidence labels contradict the workbook's own definitions

**Evidence**

`etl/s101_workbook.py:97-109` correctly defines core-fact confidence: derived and OCR values are `Medium`; initiative material is `Working`; direct government text is `High`. The workbook cover repeats that policy at `etl/s101_workbook.py:225-238`.

The final warehouse does not apply it consistently. `etl/s87_fact_financial.py:468-471` assigns `High` to every parsed financial statement row, including OCR. Lines 501-513 also explicitly load legacy OCR rows as `High`.

Current fact-table counts are:

| Extraction | Confidence | Rows |
|---|---|---:|
| digital text | High | 11,249 |
| OCR arithmetic verified | High | **488** |
| workbook import | High | **522** |
| workbook import | Medium | 34 |
| workbook import | Working | 78 |
| workbook-import metrics | High | **100** |
| workbook-import metrics | Medium | 9 |

That is **1,110 `High` rows** whose extraction categories are defined on the cover as `Medium` or `Working` unless stronger evidence is established.

The evidence does not support a blanket escalation. `warehouse_county.json` says 41 of 396 workbook rows were checked against a held cited page, while 355 were not page-verifiable through that path. The new county reader finds 672 of 794 monetary values in the same fiscal year's audited statements and does not find 122, but that check is value-only, skips values below $1,000, and explicitly does not prove the label or attribution.

**Impact**

Filtering the warehouse to `Confidence = High` does not produce what the cover promises. Analysts can unknowingly include OCR and unconfirmed research-workbook values as if each were directly read from an official document with established meaning.

**Required fix**

Centralize confidence assignment and apply it to every fact table. Suggested minimum policy:

- `High`: canonical official source, direct text, known column meaning, label/page attribution verified.
- `Medium`: OCR arithmetic verified, derived from High inputs, or value-only official corroboration.
- `Working`: analysis-workbook import without label-level official verification or a digital line with unresolved basis.
- `Pending`: excluded from published fact tables.

Record separate dimensions for `Source_Authority`, `Extraction_Assurance`, `Semantic_Assurance`, and `Confidence_Reason`. A single label should be a derived summary, not the only evidence.

### H-03: Duplicate presentations can be aggregated as separate facts

**Evidence**

The warehouse includes 488 `ocr-arithmetic-verified` financial rows. Thirty-six are in fiscal years for which `audited_digital.json` contains a reconciled digital original: 30 in FY2018 and six across FY2021-FY2024. Sixteen match a digital row on organization, year, scenario, flow, account, measure, and amount.

This violates the explicit comments at `etl/s87_fact_financial.py:483-500` that a digital original wins and recognition must not be loaded for the same slice. The legacy `ocr_statements.published_lines` flag used at lines 501-503 is stale relative to the newer digital-source inventory.

Across `Fact_Financial`, 53 semantic/value groups covering 113 rows have the same organization, year, scenario, flow, account, measure, and amount but cite more than one source. Some are legitimate corroborating presentations, but the table has no canonical fact or authoritative-presentation flag to stop a downstream sum from counting both. Confirmed examples include scan and digital FY2018 totals and four FY2025 values emitted from two digital copies of the same financial report.

The duplicate test at `tests/test_data_integrity.py:1483-1491` includes `Department` in its identity key. Parser-specific values such as `(page)` and `(audited statement)` therefore make the same civic fact look unique and allow the duplicate to pass.

**Impact**

Every row can reconcile against its own page while an aggregate is still wrong. This is a dangerous warehouse failure mode because the numbers look individually trustworthy and duplicates can be introduced by adding a better source.

**Required fix**

Use the current digital-year set, not a legacy row flag, to exclude all OCR publication where a digital source is authoritative. Add `Canonical_Fact_ID`, `Presentation_ID`, `Is_Authoritative`, and `Corroborates_Fact_ID`. Publish a safe aggregate view containing one authoritative fact per grain. Add a duplicate gate that ignores parser-only `Department`/`Line` variation and explicitly permits documented comparative presentations.

### H-04: The public repository cannot independently reproduce or verify the data

**Evidence**

The registered archive has 118 unique documents totaling 991,167,169 bytes (945.25 MiB), plus 43 duplicate copies. It includes 71 digital-text PDFs, 15 scanned PDFs, and 32 other files. One source exceeds GitHub's 100 MiB per-file limit.

The sources are intentionally not tracked. Every one of the 118 `official_url` fields is null. There is no source acquisition manifest with downloadable URLs, no immutable public source package, and no documented command that reconstructs the exact source set from public locations. A fresh clone therefore cannot run `make etl` or verify page citations.

The site and workbook state that the dataset is rebuilt from the documents and can be checked by readers. The repository can reproduce generated artifacts only for someone who already possesses the private source archive.

**Impact**

This is incompatible with setting a standard for other counties. Reviewers cannot verify the source-to-fact chain, new maintainers cannot reproduce releases, and a government changing a web document can make later verification impossible without an archived copy.

**Required fix**

Publish a machine-readable acquisition manifest containing canonical official URL, issuing authority, access date, SHA-256, byte size, media type, license/public-record status, and an immutable archival URL where allowed. Use a release script that downloads, hashes, and refuses mismatches. For files that cannot be redistributed, publish exact public-record request metadata and a verification procedure. Produce a signed release manifest tying source-set hash, code commit, toolchain, generated datasets, and exports together.

## Medium-Severity Findings

### M-01: The customer-facing Orange County verification copy ignores new evidence

`assets/app.js:2017-2069` renders 16 county revenue/expenditure totals from `warehouse_county.json`. It reports that only two have been rechecked and says the others cite years that do not resolve to held files.

That was true of the older `s85` verification path, but `county_acfr.json` now directly reads all eight FY2018-FY2025 county ACFR years. Thirteen of the 16 summary values appear in the new direct extraction; the older page check separately verifies FY2018 expenditure. Together, 14 of 16 have at least one current cross-check. FY2019 and FY2020 expenditures remain not found in the direct extraction.

The UI therefore understates current evidence and gives a false reason for the gap. Feed the site a single verification record per displayed value with method, source, page, result, and limits. Do not infer trust from a dataset that predates the direct reader.

### M-02: The arithmetic gate says "exact" but accepts a $1 discrepancy

The shared parser uses `abs(got - total) < 1.5` at `etl/statement_parser.py:421-424`. Independent recomputation of 3,409 accepted Orange County columns found one accepted column on FY2022 PDF page 212 where four component lines sum to $141,335 but the printed total is $141,334.

The amount is immaterial, but the product repeatedly says accepted columns add up "exactly." Exactness is a control claim, not a rounding style. Require equality for integer-dollar statements, or disclose a tolerance and store the variance. Add a test that recomputes each accepted column from members instead of trusting cached `sum_of_lines` and `reconciles` fields.

### M-03: Mobile rendering is heavy, and horizontal tables are not keyboard reachable

The live deployed commit produced these Lighthouse mobile results under standard throttling:

| Category / metric | Result |
|---|---:|
| Performance | 73 |
| Accessibility | 100 |
| Best Practices | 100 |
| SEO | 100 |
| First Contentful Paint | 1.2 s |
| Largest Contentful Paint | 2.6 s |
| Total Blocking Time | 1,080 ms |
| Main-thread work | 3.5 s |
| Transferred payload | 222 KiB compressed |

The decoded initial data is roughly 1.57 MB across 24 resources. The mobile document renders about 34,400 text characters, 34 disclosure widgets, and approximately 30,000 vertical pixels up front. Most blocking time is style/layout rather than script download.

Standalone Axe testing found two serious `scrollable-region-focusable` failures on 390 px and 320 px viewports. Six table wrappers can overflow horizontally; none has `tabindex`, a role, or a keyboard-accessible scroll affordance. The overall document itself does not overflow, so this is easy to miss in a page-width test.

Use progressive section rendering, route or lazy-load secondary datasets, apply `content-visibility` carefully, and avoid constructing every table until requested. Make each overflow region focusable and labeled, or transform priority tables into stacked mobile rows. Increase the 34-40 px navigation/action controls toward a 44 px ergonomic target even though most satisfy WCAG's smaller formal minimum.

### M-04: Frontend behavior is untested and too hard-coded for county expansion

The frontend is a single approximately 160 KB, 3,000-line `assets/app.js` file that mixes calculations, data selection, copy, rendering, persistence, share-state handling, and interactions. `index.html` and the JavaScript contain many hard-coded Hillsborough, Orange County, and FY2027 strings. The warehouse has organization dimensions, but the site does not render from a jurisdiction configuration.

CI runs `node --check` and a palette validator, not browser or calculation tests. Python tests validate source data and grep for selected JavaScript strings, but they do not execute the calculator. That is why all 111 tests passed while the out-of-town result remained wrong.

Do not perform a framework rewrite solely for fashion. First extract pure domain functions (`townTax`, `countyTax`, `utilityBill`, `residentTotal`, provenance selection), add JavaScript unit tests, split renderers by section, define a versioned JSON schema, and add Playwright smoke/calculator/accessibility tests in CI. Then evaluate TypeScript or a small component layer if it materially improves multi-jurisdiction maintainability.

### M-05: Documentation and trust copy have drifted behind the data

Examples include:

- `AGENTS.md:16` still says ten of thirty sources are scans; the archive now has 118 documents and 15 scans.
- `README.md:117-148`, `README.md:209-247`, `docs/AGENT_BRIEF.md`, and `docs/OPEN_QUESTIONS.md` contain several old claims that FY2018 is scan-only or that FY2018-FY2024 all rely on scans.
- `docs/COVERAGE.md:17` says FY2017-FY2020 are thin because they exist only as scans, although FY2018 is now digital.
- `etl/s87_fact_financial.py:487-491` documents 1,941 OCR matches while the current artifact reports 5,394.
- The site says "Nothing here is our opinion." The application does separate many facts carefully, but its health assessments, grouping choices, interpretations, and recommendations are analysis. A more defensible promise is that facts, calculations, and interpretation are visibly distinguished.
- When a required JSON request fails over HTTP, the error message says the user probably opened the file directly. That diagnosis is wrong for deployment or partial-release failures.

Generate volatile counts/status text from datasets where possible, add assertions for prose claims, and version methodology claims. Show a build ID, data-as-of date, and correction history in the UI.

## Low-Severity and Hardening Findings

1. Ruff reports 328 issues, dominated by formatting, redundant constructs, unused suppressions, import order, broad exception handling, and subprocess configuration. This is not evidence of 328 bugs, but the 12 broad `except` findings and silent exception patterns make failures harder to diagnose.
2. Bandit reports 36 low-severity findings and zero medium/high findings, mostly subprocess use and suppressed exceptions in local ETL scripts.
3. `pip-audit` reports no known vulnerabilities in the pinned Python dependencies.
4. The static application has no backend, authentication, or server-held personal profile. Home value, location, and water use stay in browser storage, which is a good privacy baseline. A strict Content Security Policy would still add defense in depth, but the inline pre-paint theme script must be moved or hashed first.
5. GitHub Actions use version tags rather than immutable action SHAs. Pin action SHAs and enable dependency update automation for supply-chain hardening.
6. The Makefile assumes Unix paths and commands. Add a documented Windows entry point or a cross-platform Python task runner if Windows maintainers are expected.
7. The touch controls work, reduced-motion behavior exists, focus outlines are present, internal anchors resolve, themes pass automated contrast testing, and responsive navigation closes on Escape. These are strengths to preserve.

## Numerical Deep Dive

### Artifact inventory

| Surface | Current count |
|---|---:|
| Registered unique documents | 118 |
| Government sources | 108 |
| Initiative sources | 10 |
| Documents contributing known-source warehouse facts | 24 |
| Not-yet-read source documents | 37 |
| Core website facts | 83 |
| Core fact extraction mix | 65 digital, 13 stated, 5 derived |
| Financial fact rows | 12,371 |
| Metric fact rows | 109 |
| Statement-line fact rows | 11,771 |
| Total fact-table rows | 24,251 |
| Workbook sheets | 28 |

### Independent checks completed

- **111/111 tests passed** in 6.77 seconds.
- **40 JSON files and 255,420 numeric leaves** were traversed; no `NaN`, positive infinity, or negative infinity was found.
- **Digital statements:** 2,617 published rows, 536 accepted groups, 1,777 accepted columns independently recomputed, zero arithmetic mismatches. Fifty-seven parse problems are withheld rather than silently published.
- **Scanned statements:** 610 publication rows plus 1,920 validation-only rows, 542 accepted groups, 1,655 accepted columns independently recomputed, zero arithmetic mismatches. The artifact records 638 extraction problems and retains a 200-item sample.
- **County ACFR statements:** 4,568 published rows, 956 accepted groups, 3,409 accepted columns independently recomputed, one $1 strict mismatch accepted under the parser tolerance.
- **Combined statement gate:** 6,841 accepted columns independently recomputed; 6,840 equal the printed total exactly and one differs by $1.
- **OCR ground truth:** per-year counts independently retotal to 5,394 identical figures out of 5,394 compared across FY2018 and FY2021-FY2024, with zero reported differences.
- **Core derived facts:** all four administrative year-over-year percentages and the FY2023-FY2027 total-change percentage recompute exactly at their published two-decimal precision.
- **Core cross-checks:** county rate change is 67.58 - 63.83 = 3.75 cents; the county's $500,000 worked increase is $187.50; FY2027 budget components sum exactly to $36,420,539.
- **Projection comparisons:** all minima and maxima are correct; three raw floating spreads differ only by binary floating-point tails and are correctly stored rounded to one decimal place.
- **Utility model:** all eight town-stated water/sewer increases are reproduced; four are exact and four differ by one cent due to printed schedule rounding, which is disclosed.
- **Line-item validation:** 55 of 60 checks reconcile, five are disclosed presentation differences, and zero unexplained failures remain. Seven of ten slices are marked verified.
- **Projects:** all 27 published projects reconcile to their printed project totals; none is withheld in the current build.
- **Tradeoffs:** $3,350,298 funded plus $282,500 declined equals $3,632,798 requested; the published funded share is 92.2%.
- **Workbook B:** all eight tax-equivalent calculations agree; the FY2029 $3,567,819 cliff parts reconcile; cross-checks against pipeline facts pass.
- **Tax history:** 15 years have both town and county rates with no cross-edition disputes. The known Table 6 county decimal defect is consistently tenfold and the unaffected Table 5 is used instead.
- **Excel safety/structure:** 28 sheets, no formulas, no external links, no formula-injection-like strings, frozen headers, filters on fact/source sheets, and semantic row counts consistent with JSON after accounting for title/header rows.

### Numbers that are not fully proven

These are disclosed gaps, not necessarily errors:

- 37 source documents with figures remain unread by ETL.
- 355 of 396 county workbook rows were not verified through the original cited-page path.
- The new county reader corroborates 672 of 794 eligible imported monetary values by same-year value and does not find 122; it does not prove labels.
- Two of the 16 county summary totals shown on the website, FY2019 and FY2020 expenditure, lack either of the current direct/page checks.
- Seven actual-year revenue component schedules have disclosed presentation differences ranging from -$9,617 to +$2,928,203; percentages are suppressed where the parts do not reconcile.
- Nine transfer destinations remain `Unidentified` because the source line does not name the receiving fund.
- Historical base water/sewer rates, a county school-specific sales-tax rate, and adopted FY2028/FY2029 rates are not available and are not invented.
- Primary-source page verification for the entire corpus remains impossible from the public clone until H-04 is fixed.

## Frontend and Product Analysis

### What is already strong

The customer-facing design is substantially better than a typical civic-data portal. It starts with the actual experience instead of a marketing landing page, gives the product and jurisdictions first-viewport prominence, uses a clear visual hierarchy, keeps the next section visible, and makes dark and light themes feel intentional. The calculator, source citations, printable summary, share provenance, issue-report links, plain-language caveats, and progressive disclosures show careful attention to resident workflows.

Desktop, tablet, 390 px mobile, and 320 px mobile tests found no page-wide horizontal overflow, missing anchor target, duplicate DOM ID, broken image, console error, or failed request. Navigation and theme interactions worked, the mobile menu synchronized `aria-expanded` and closed on Escape, all 34 disclosures could be opened, and extreme numeric input did not break page width.

The visual direction is modern enough. "Bleeding edge" should come from unusually clear personalization, evidence, and responsiveness, not decorative effects that make public finance harder to trust.

### Launch UX priorities

1. Fix the out-of-town result and display the exact tax districts included and excluded.
2. Put a compact persistent "My household" summary near the top: assessment, jurisdiction, tax districts, water basis, fiscal year, and confidence/as-of status.
3. Add an always-available "Why this number?" provenance drawer for every headline: formula, inputs, official source, page, source authority, extraction method, confidence reason, hash, and last verification date.
4. Replace the 30,000-pixel single journey with task-oriented views or tabs: `My bill`, `Where it goes`, `Financial health`, `Changes`, and `Sources`. Preserve deep links and a concise narrative mode.
5. Make tables usable on phones through responsive rows or labeled, keyboard-focusable scrollers.
6. Show data state explicitly: `Official`, `Calculated`, `OCR verified`, `Research workbook`, `Unverified`, or `Conflicting presentation`. Do not hide this behind a single green "sourced" count.
7. Improve partial-failure states so one optional dataset can fail without replacing the entire product, and report the actual failed data family plus build ID.

### High-value personalization

The product already remembers assessment, inside/outside status, and water usage. The next personalization layer should be:

1. **Optional address or parcel lookup:** resolve municipality, county, fire district, school district, and service area from public GIS. Explain that an address lookup contacts the lookup service; retain manual mode and do not store addresses by default.
2. **Complete local bill stack:** county, municipality, fire district, special districts, water/sewer/stormwater, and any solid-waste or service fees. Show exclusions next to the total.
3. **Household type:** owner, renter, business, nonprofit, senior, disabled veteran, agricultural/deferred property, or tax-exempt. Explain which calculations change and which cannot be estimated.
4. **Assessment and exemption details:** assessed value, taxable value, exemptions/deferments, revaluation year, and an option to compare a real prior bill rather than applying one fixed home value across revaluation.
5. **Year and scenario selector:** adopted, recommended, amended, actual, and projected. Default to the currently applicable bill and never label a recommendation as adopted.
6. **Change explainer:** a waterfall from last year to this year separating rate, assessed value, county, town, district, and utility changes. This is more useful than a generic trend chart.
7. **Service preferences:** let residents choose priorities and show the documented budget/service tradeoff, without presenting preference matching as a financial fact.
8. **Local-only saved profiles:** allow several named scenarios such as home, rental, or proposed purchase, stored locally. Sharing should expose exactly which fields enter the URL.
9. **Alerts and watchlists:** optional notifications for adopted budgets, rate changes, capital projects, source corrections, and public hearings. Treat contact data as a separate consented service, not part of the static calculator.

### Features that would establish a standard

- A per-figure evidence panel with source thumbnail/page, text excerpt within copyright limits, formula, version history, and correction trail.
- A "where one dollar goes" view tied to authoritative fund/scenario grain, with an explicit no-double-count aggregate view.
- Peer comparisons normalized per resident, household, assessed-value dollar, and service population, with comparability warnings.
- Outcome measures beside spending where official measures exist; avoid implying that expenditure alone measures service quality.
- A public data-health dashboard: sources present, URLs archived, rows canonical, conflicts open, checks passed, backlog, and last successful release.
- Download/API options for the exact filtered view a resident is seeing, with the source-set and schema version embedded.
- Multilingual plain-language content and a WCAG 2.2 AA regression suite.
- A correction workflow with public issue, owner, status, affected releases, resolution evidence, and response target.

## Multi-County Architecture

The warehouse has the beginnings of a reusable dimensional model, but the site is still a Hillsborough-specific publication. Expansion should be configuration-driven rather than a copy of the current app per county.

Recommended structure:

1. Define a versioned jurisdiction package containing identity, geography, fiscal calendar, organization hierarchy, fund/account crosswalk, tax/fee formulas, scenarios, source authorities, and content labels.
2. Separate source ingestion adapters from canonical facts. Each adapter should emit the same validated contract and never render UI directly.
3. Preserve local vocabulary while mapping to canonical concepts. Do not force every county's funds or departments into Hillsborough labels.
4. Make canonical source ID, source alias, organization ID, scenario, fiscal year, presentation, and authoritative status required dimensions.
5. Publish JSON Schema or equivalent contracts and validate every artifact at build time.
6. Add a jurisdiction readiness score: source URLs complete, required years present, current rates present, formulas tested, crosswalk reviewed, accessibility content complete, and independent signoff recorded.
7. Create a contributor/admin source-registry interface for URL, authority, organization, document version, supersession, and review status. Changes should produce reviewable diffs, not edit generated files silently.
8. Keep a common civic design system and interaction model while allowing local branding, language, service structure, and required disclosures.

The standard should define evidence and interfaces, not demand identical accounting structures. Counties vary; the platform must expose those differences rather than normalize them away invisibly.

## Recommended Release Gates

### P0: Required before public production launch

- Close C-01 and add browser tests for every personalized output surface.
- Canonicalize all 682 foreign source IDs or exclude those rows from published fact tabs.
- Correct confidence for the 1,110 OCR/workbook rows and make the rule centralized.
- Remove OCR publication for digital years and establish a canonical authoritative fact view.
- Publish the source acquisition/archival manifest and populate official URLs.
- Correct the county verification copy and explicitly mark the two unresolved summary values.
- Make accepted arithmetic match the advertised exactness, or disclose tolerances precisely.
- Add CI gates for fact-tab/source-register coverage, cover/tab counts, semantic duplicates, confidence semantics, and Playwright calculator scenarios.

### P1: Required for a credible "leading civic platform" release

- Reduce main-thread rendering and target a stable mobile Lighthouse performance score of at least 90 on the deployed site.
- Resolve keyboard access for all table scrollers and add automated Axe/Playwright checks.
- Split the frontend into tested domain and presentation modules.
- Add per-figure provenance drawers, build/data-as-of identity, and correction history.
- Reconcile documentation and generate volatile status claims from data.
- Add partial-data failure handling and observability for failed dataset loads.

### P2: Expansion and differentiation

- Implement jurisdiction configuration and a second-county proof without forking the application.
- Add optional parcel/district resolution and the complete local tax stack.
- Add year/scenario comparison, change waterfall, saved profiles, and filtered downloads.
- Establish schema governance, data quality SLAs, independent review, and a public release/correction process.

## Verification Record

Commands and checks run against the reviewed commit included:

```text
git fetch / fast-forward to origin/main
python -m pytest tests -q                         111 passed
python -m compileall -q etl tests                 passed
node --check assets/app.js                        passed
node scripts/validate_palette.js                  passed
pip check                                         passed
pip-audit -r etl/requirements.txt                 no known vulnerabilities
ruff check etl tests                              328 findings
bandit -r etl                                     36 low, 0 medium, 0 high
Playwright desktop/tablet/mobile/narrow smoke     passed except findings above
Axe WCAG 2.x                                      2 serious mobile scroller nodes
Lighthouse live mobile                            73 / 100 / 100 / 100
Excel formula/link/injection inspection           clean
Independent JSON and statement arithmetic audit   completed
```

The reviewed `verify` workflow and GitHub Pages deployment both completed successfully for commit `8b1e75d1`. The green workflow proves the repository's current gates pass; the findings above identify important assertions those gates do not yet make.

## Final Assessment

MFAS is a serious civic-data product with a stronger integrity culture than most early public-finance applications. Its deterministic build work, source registry, explicit extraction caveats, scan-vs-digital comparison, issue links, and resident-centered UI are valuable foundations.

It is not yet safe to claim the standard. The clearest reason is not abstract architecture: the primary calculator currently ignores a user's jurisdiction answer and publishes the wrong personal total. The warehouse then has a second trust problem: its cover, source dimension, confidence labels, and duplicate policy do not describe all of the rows it actually ships.

Fix those controls first. Then make the evidence visible in the interface and turn jurisdiction-specific assumptions into configuration. That combination - correct personal results, explicit assurance levels, reproducible sources, and reusable jurisdiction contracts - is what can make MFAS a standard other counties can adopt rather than only a polished local site.
