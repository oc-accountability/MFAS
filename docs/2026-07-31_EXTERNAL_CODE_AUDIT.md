# MFAS Full Code Audit

**Repository:** `oc-accountability/MFAS`  
**Branch / commit reviewed:** `main` at `84a86a68be42f0e92efe68eb5128e4994b08f710`  
**Audit date:** 2026-07-31  
**Reviewer:** OpenAI Codex  
**Scope:** Python ETL, generated JSON and Excel artifacts, static browser application, tests, build/release process, security, accessibility, performance, provenance, and documentation.

## Executive Summary

MFAS has a notably strong current data-integrity baseline. All 94 repository tests pass, the checked-in site loads without browser errors at desktop and mobile widths, the calculator responds correctly, and the current generated JSON artifacts reconcile. The project also shows unusual care around the risk of extracting numbers from scanned PDF text layers.

The largest risks are not obvious UI failures. They are defects in the rebuild and export path that can undermine the project's central promise of traceable, reproducible figures:

1. The committed Excel warehouse currently mislabels initiative-authored material as Orange County government material and assigns `High` confidence to interpreted request-workbook figures.
2. Several extraction caches are not bound to source content hashes. Replacing a source under the same document ID can silently reuse old OCR or page text while the manifest records the new file's hash.
3. Important extraction and consistency failures are recorded as messages but do not fail `make etl`; the separate test suite is not run by that target and no CI workflow enforces it.
4. The Excel export runs before the merged facts it consumes are rebuilt, so it can lag the JSON data by one pipeline run.

No confirmed corruption was found in the current core JSON facts. No critical-severity remote exploit, exposed secret, malicious workbook formula, or browser runtime error was found. The overall risk is **moderate to high**, driven primarily by provenance and rebuild correctness rather than conventional application security.

## Scope and Limitations

The clone contains 88 tracked files, approximately 7,800 lines of Python ETL, 1,166 lines of tests, 2,834 lines of JavaScript, and 1,069 lines of CSS. The review included manual control-flow and data-lineage analysis, generated-artifact inspection, dependency auditing, static analysis, browser execution, automated accessibility checks, and Lighthouse.

The repository deliberately excludes `sources/`. The reviewed manifest describes 95 unique documents totaling 903,201,291 bytes (861.4 MiB), but all 95 `official_url` fields are null and the repo has no acquisition script. Therefore the raw PDF/XLSX extraction stages and the numeric claims against their original documents could not be independently rerun from this public clone. The checked-in datasets and the final merge stage were tested; this is a full code and artifact audit, not a forensic re-transcription of the unavailable source archive.

## Severity Model

- **Critical:** immediate compromise or confirmed publication of materially false core data.
- **High:** a realistic path to incorrect or materially misleading published data, provenance, or exports.
- **Medium:** a material reliability, reproducibility, accessibility, performance, or maintenance defect.
- **Low:** limited-scope hardening or developer-experience issue.

## High-Severity Findings

### H-01: The committed Excel export misstates source ownership and confidence

**Evidence**

- `etl/s101_workbook.py:163` maps every jurisdiction containing the word `Orange` to `ORG_OC`. The manifest's initiative jurisdiction is `Orange County Efficiency & Accountability Initiative`, so all 10 initiative-authored documents are exported as county-government sources.
- `etl/s101_workbook.py:168-169` labels every non-scan document `Machine-readable source` with `High` confidence. Readability is not authority.
- `etl/s101_workbook.py:247` labels every fact except `extraction == "derived"` as `High`, even though the workbook's own definition at lines 132-134 says `High` means an official published document and `Working` means an analysis workbook.
- In the committed `data/exports/MFAS_Data_Warehouse.xlsx`, all 10 initiative documents are `ORG_OC / High`. Of the 14 facts sourced from `hillsborough-data-request-june-2027`, nine `stated` rows are `High` and five calculated rows are `Medium`.
- `tests/test_data_integrity.py:1382-1403` already documents that those 14 facts come from the initiative's own request workbook, not a government publication, but the Excel export has no semantic test for that distinction.

**Impact**

The export is a user-facing data product. A downstream analyst can reasonably interpret `ORG_OC / High` as an Orange County government publication when it is initiative-authored or interpreted material. This is a current provenance defect, not merely a future risk.

**Recommendation**

Add explicit `source_owner` and `source_authority` fields to the manifest instead of inferring them from a substring. Derive export confidence from source authority plus extraction method. Use `Working` for initiative analysis/request workbooks unless independently verified against an official source. Add tests for all 10 initiative source rows and all 14 request-workbook facts.

### H-02: Extraction caches can attach stale text to a new source hash

**Evidence**

- `etl/s70_ocr.py:49-52` returns an existing OCR page solely because `build/ocr/<doc-id>/pNNNN.txt` exists. The cache key contains no source SHA-256, page count, DPI, Tesseract version, or OCR parameters.
- `etl/s75_ocr_statements.py:193-201` walks every directory left under `build/ocr`, not the current stage-70 target set, and does not confirm that the current manifest entry is still a scan with the same hash.
- `etl/s85_warehouse.py:117-131` keys page text only by a truncated filename stem and page number. A replaced source can reuse old text; long filenames can also collide after truncation.
- `etl/s85_warehouse.py:112-114` chooses the first year-matching county PDF even when several candidates exist, despite describing ambiguity as a data-quality condition.
- `etl/s94_projects.py:67-75` prefers one hard-coded size/mtime cache name, then falls back to the first sorted matching cache. `etl/s50_line_items.py:168-184` creates those caches from document ID, file size, and mtime rather than content hash.

**Impact**

If a PDF is corrected or replaced under the same filename/document ID, the manifest can point to the new SHA-256 while downstream OCR, warehouse verification, or project extraction silently uses text from the old file. That severs the fact-to-source chain the application presents as its primary trust guarantee. A routine resumable `make etl` is enough to trigger the condition; `make clean` is only an undocumented workaround.

**Recommendation**

Use the full source SHA-256 plus extractor name/version/options in every cache namespace. Store and verify cache metadata before reading a hit. Have stage 75 consume the exact current OCR manifest rather than enumerate directories. Treat multiple source candidates as a hard error. Delete or ignore orphaned cache entries automatically.

### H-03: The documented integrity gates are not fail-closed

**Evidence**

- `etl/s30_budget_messages.py:255-311`, `etl/s40_household_impact.py:165-223`, and `etl/s80_county.py:69-137` collect extraction misses and failed consistency checks, write them into JSON, print them, and exit successfully.
- `etl/s90_build.py:179-181` treats a fact/registry unit mismatch as a warning, although using the wrong unit can change meaning by orders of magnitude.
- `etl/s90_build.py:255-355` computes the number of figures read from a scan text layer but only writes the count to `data/index.json`; it does not fail when the count is nonzero.
- `Makefile:17` says stage 90 fails the build on bad data, but `Makefile:18-44` ends after stage 90. The 94 integrity tests are a separate `make test` target at lines 46-47.
- There is no tracked GitHub Actions workflow, so nothing in the repository automatically requires `make test` before a push to the published branch.
- The current stage artifacts are healthy: the only extraction message is an informational FY2025 template note, and all current consistency checks pass. The defect is in enforcement.

**Impact**

A parser pattern miss, a failed tax calculation cross-check, a unit mismatch, or a prohibited scan-text value can produce and publish partial or misleading outputs when a maintainer runs the documented rebuild command but forgets the separate tests.

**Recommendation**

Give stage diagnostics explicit `info`, `warning`, and `error` levels; exit nonzero on errors. Promote unit mismatch and nonzero scan-text publication to build errors. Add a `verify` target that runs the complete ETL and tests, make it the documented release command, and enforce it in CI with branch protection. Keep known informational conditions in an allowlist with exact expected text or codes.

### H-04: The Excel warehouse can lag the JSON facts by one build

**Evidence**

- `etl/s101_workbook.py:96-100` reads `facts.json`, `documents.json`, and `metrics.json`.
- `Makefile:42-44` runs `s101_workbook.py` and `s103_tab_map.py` before `s90_build.py`.
- `etl/s90_build.py:148-163` is the stage that merges current upstream fact files into the `facts.json` consumed by stage 101.
- Existing workbook tests check that the file is tracked and has expected tabs/columns, but do not compare the workbook's fact and metric rows to the just-generated JSON datasets.

**Impact**

On a build where an upstream extraction changes, the website JSON gets the new facts at the end of the run while the downloadable Excel warehouse keeps the previous run's facts. A second build can make it converge, hiding the problem during manual review. The current committed workbook count matches the current 83 facts, so this is a deterministic pipeline-order defect rather than a confirmed current mismatch.

**Recommendation**

Run stage 90 before stages 101 and 103, or split merge/validation from index generation so exports consume finalized canonical datasets. Add row-for-row tests that compare the export's fact and metric sheets to the JSON source immediately after one clean build.

## Medium-Severity Findings

### M-01: The public clone cannot reproduce the published data, and URL enrichment is overwritten

The public clone has no `sources/`, no download script, and no populated official URLs. `etl/s00_manifest.py:139-141` therefore stops immediately. At lines 180-183, every manifest rebuild unconditionally writes `official_url: None`. This contradicts `docs/PROVENANCE.md:29-32`, which tells contributors to set the field and rebuild; the rebuild erases the contribution.

This also makes the site's byte-for-byte reproducibility claim in `index.html:118-121` unverifiable for a new contributor. Preserve URL metadata in a tracked override keyed by full SHA-256, merge it during stage 00, and document a lawful acquisition/mirroring process for every source that can be redistributed. Where redistribution is impossible, publish canonical URLs and exact retrieval instructions.

### M-02: The byte-identical rebuild promise is not achievable as implemented

`etl/s101_workbook.py:138,150` and `etl/s103_tab_map.py:285` write `date.today()` into generated workbooks, so identical inputs produce different cells on different days. XLSX ZIP member metadata is also regenerated by OpenPyXL. External OCR/render tools are not installed from the pinned Python requirements, and not all tool versions/options are part of artifact identity.

This conflicts with `docs/PROVENANCE.md:127-136`, which instructs users to expect a clean `git diff --stat data/` after a byte-identical rebuild. Either make outputs deterministic using a source-derived/release date, fixed ZIP timestamps, and pinned toolchain containers, or narrow the promise to semantic equivalence and provide a canonical JSON/workbook comparison command.

### M-03: The OCR accuracy probe measures distinct-value recall, not exact figure reproduction

`etl/ocr_accuracy_probe.py:109-115` converts both sources to sets, collapsing duplicate amounts and discarding position. Lines 124-126 count only the truncated `spurious_sample`, and lines 129-133 declare OCR safe based only on recall. A result can therefore pass despite invented values, lost duplicates, or values moved to the wrong row/column. The arithmetic language in `etl/s75_ocr_statements.py:243-255` also says a changed digit *would* break the sum, which is evidence but not a proof against offsetting or correlated errors.

The current six-page sample reports 141 distinct values reproduced and no observed spurious values, so this is a methodology/claim issue rather than evidence that current totals are wrong. Compare ordered tokens or table coordinates as a multiset, require both precision and recall with zero unexplained values, retain complete mismatch counts, and add a documented human visual sample for row/column attribution.

### M-04: Document IDs are not stable identifiers

`etl/s00_manifest.py:47-52` derives IDs from basenames. Lines 204-209 resolve collisions by assigning suffixes in archive traversal order. Adding another same-named document in an earlier-sorting path can transfer the unsuffixed ID to different bytes while facts continue citing the same string.

Use a persistent source registry keyed by full SHA-256, with an explicitly assigned immutable ID and aliases. Fail when a new source wants an existing ID rather than silently renumbering it. Test important source IDs against expected hashes.

### M-05: Automated accessibility checks find serious WCAG failures

Desktop and mobile axe/Lighthouse runs found:

- `assets/app.js:1340-1342` emits `dt`/`dd` elements outside a `dl`.
- `assets/style.css:184-185` removes link underlines until hover, leaving prose links distinguishable by color alone.
- On mobile, `index.html:26-31` plus `assets/style.css:219-221` hides the brand's only text while its icon is `aria-hidden`, leaving an unnamed link.
- `assets/app.js:403-406` gives section permalinks accessible names that do not contain their visible numeric label.
- Horizontal regions created by `assets/app.js:390-396` and styled at `assets/style.css:681` are not keyboard-focusable when they overflow on mobile.

Lighthouse accessibility scored 91, but these are real navigation and semantics defects. Use a proper `dl`, retain non-color link affordance, add an `aria-label` to the brand, make visible/accessibility labels agree, and give overflow containers `tabindex="0"` plus an accessible label where needed. Add axe checks at desktop and mobile breakpoints to CI.

### M-06: The initial page eagerly loads nearly all data and has a slow mobile LCP

`assets/app.js:2900-2906` fetches 20 datasets in one `Promise.all` before the first render. Those JSON files total 966,153 bytes (943.5 KiB) uncompressed, including county warehouse, projects, and tradeoff data for sections far below the fold.

The local Lighthouse mobile run scored 70 for performance: FCP 1.1 s, LCP 7.8 s, total blocking time 290 ms, CLS 0, and 1,178 KiB transferred. The local Python server does not model production compression/caching, so absolute transfer results are conservative, but the all-or-nothing boot and long main-thread render are visible in the code.

Render the calculator and above-the-fold summary from a small critical bundle, then fetch/render later sections on intersection or disclosure. Split large datasets by feature and cache parsed data. Establish a mobile performance budget in CI.

### M-07: Documentation has materially drifted from the generated manifest

The current manifest contains 95 unique documents, 42 duplicate paths, 54 digital PDFs, 11 scans, and 83 core facts. Examples of stale claims include:

- `README.md:96,160,219`: 879 MB, 84 documents, and 19 of 84 cited.
- `AGENTS.md:102` and `docs/PROVENANCE.md:9`: 726 MB / 30 documents.
- `docs/PROVENANCE.md:17`: nine duplicate copies.
- `docs/EXTRACTION_NOTES.md:46,54`: 10 scans, 16 digital documents, and 62 figures.
- `docs/AGENT_BRIEF.md:60-62`: 10 scanned documents.

Stale trust documentation is especially costly in a civic accountability project. Generate counts in documentation from the manifest, or replace volatile values with links to the generated summary. Add a test that searches designated trust documents for obsolete pinned counts.

## Low-Severity Findings

### L-01: The pinned pytest version has a known local tmpdir vulnerability

`etl/requirements.txt:3` pins `pytest==8.3.4`. `pip-audit` reports `PYSEC-2026-1845` / `CVE-2025-71176` / `GHSA-6w46-j5rx-g56g`, fixed in 9.0.3. On Unix, predictable `/tmp/pytest-of-{user}` handling can allow a local denial of service or possible privilege gain. Exposure is limited because pytest is a development dependency and the static site has no server-side Python runtime. Upgrade to pytest 9.0.3 or later and rerun the suite. See the [GitHub advisory](https://github.com/advisories/GHSA-6w46-j5rx-g56g).

### L-02: Fetch failures are collapsed into a generic page failure

`assets/app.js:2900-2905` and `assets/app.js:1635-1637` call `response.json()` without checking `response.ok`. One missing or non-JSON dataset rejects the all-or-nothing initial `Promise.all` and produces the generic message at lines 2943-2945. Add a small checked JSON loader that reports dataset name and HTTP status, and allow independent below-the-fold sections to fail without removing the primary calculator.

### L-03: Future official URLs need scheme validation and browser hardening

`assets/app.js:219` escapes an `official_url` for HTML syntax but does not restrict its URL scheme. The fields are currently null and repository-controlled, so this is not an exploitable current issue; once contributors populate them, a `javascript:` URL could become an executable link. Accept only `https:` (or an explicit scheme allowlist) during the build. A restrictive Content Security Policy would add defense in depth for the static application.

### L-04: The documented Make workflow is Unix-specific

`Makefile:1,13,55` assumes `.venv/bin/python`, `python3`, and `rm -rf`. On Windows, the audit had to invoke `.venv\Scripts\python.exe` directly. If Windows contributors are in scope, use a small cross-platform Python task runner or document WSL as a prerequisite. This does not affect the deployed static site.

## Verification Results

| Check | Result |
|---|---|
| `python -m pytest tests -q` | **94 passed** in 1.28 s |
| `python -m compileall etl tests` | Passed |
| `python etl/s90_build.py` against committed stage outputs | Passed; 83 facts, 42 metrics, 12 comparisons |
| `node --check assets/app.js` | Passed |
| `node scripts/validate_palette.js` | Passed |
| `pip check` | No broken requirements |
| `pip-audit -r etl/requirements.txt` | One known vulnerability: pytest 8.3.4 |
| Bandit | 0 high, 0 medium, 21 low findings; primarily subprocess path/exception-handling warnings |
| Ruff | 260 findings, mostly unused imports/style; no result independently established a current data error |
| Secret-pattern scan of tracked files | No common private-key/token patterns found |
| Generated workbook inspection | No formulas, suspicious formula prefixes, or external workbook links |
| Desktop browser, 1440x1000 | HTTP 200; no console/page/network errors; no horizontal overflow |
| Mobile browser, 390x844 | HTTP 200; no console/page/network errors; no page overflow |
| Calculator interaction | Default displayed $4,755; changing home value to $500,000 produced $5,944 |
| Lazy spending explorer | Loaded successfully |
| Lighthouse mobile | Performance 70, Accessibility 91, Best Practices 100, SEO 100 |
| Git working tree before this report | Clean; rebuilding stage 90 did not change tracked data |

## Positive Controls and Design Strengths

- The test suite asserts many domain-specific invariants rather than only schema validity: arithmetic reconciliation, source existence, scan handling, fiscal-year consistency, and copy claims.
- Core facts carry document and page/cell provenance, and the manifest retains full SHA-256 values.
- The checked-in artifacts report zero figures read from a scan's embedded text layer and 42 separately arithmetic-verified OCR totals.
- The static frontend has no third-party runtime JavaScript dependency, no cookies, and no backend attack surface.
- User-controlled calculator/share parameters are parsed into bounded numeric/enumerated state instead of being inserted as arbitrary markup.
- Generated workbooks contain no formulas or external links, reducing spreadsheet injection and link-update risk.
- No secrets, tracked source archive, symlinks, or tracked blobs over 5 MiB were found. The repository includes an MIT license.
- Browser behavior was stable at both audited viewport sizes, with no layout overlap, console errors, failed requests, or unnamed buttons.

## Test-Coverage Gaps

The 94 tests primarily validate checked-in artifacts and selected source-code strings. They do not execute the ETL stages against controlled fixture PDFs/XLSX files, do not test cache invalidation, do not test a clean one-pass build, and do not run the browser. This explains why H-02 through H-04 can coexist with a green suite.

Add small synthetic fixtures for digital PDFs, scanned PDFs, and workbooks; unit-test parsing and failure modes; run a clean pipeline twice and assert semantic idempotence; mutate a source while preserving its filename and assert cache invalidation; compare Excel facts to JSON; and add Playwright/axe smoke tests.

## Prioritized Remediation Plan

1. **Correct the export now:** fix source ownership/confidence mapping, regenerate both Excel files, and add semantic export tests.
2. **Make caches content-addressed:** bind every cache hit to source SHA-256 and extractor configuration; reject ambiguity and orphaned OCR.
3. **Create one release gate:** reorder stage 90 before exports, fail on integrity errors, run tests in the release target, and add CI/branch protection.
4. **Repair reproducibility:** persist official URLs outside generated output, publish source acquisition instructions, and define deterministic or semantic rebuild verification.
5. **Tighten OCR validation:** measure ordered/multiset precision and recall, keep full mismatch counts, and moderate claims that arithmetic alone proves digit accuracy.
6. **Fix accessibility and initial rendering:** address the five semantic/keyboard findings and lazy-load noncritical datasets.
7. **Refresh trust documentation and dependencies:** generate volatile counts and upgrade pytest.

## Release Recommendation

The current website can remain available because no confirmed core JSON numeric corruption or browser failure was found. The downloadable Excel warehouse should be treated as needing correction before it is promoted as authoritative, due to H-01. Any next data refresh should be held until H-02 through H-04 are fixed or the maintainer performs a clean build, clears all caches, runs the stages in corrected order, runs all tests, and manually verifies the regenerated export provenance.
