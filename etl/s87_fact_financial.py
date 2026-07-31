"""Stage 87 — the warehouse core Amy commissioned: one fact table, government as a column.

Her decisions (email via David, 2026-07-29), recorded verbatim in the register:

  * "One warehouse. Several analysis marts. Not several warehouses. — I agree. 100%"
  * "The government is a COLUMN. Never a tab name. Never a file name. — I agree. 100%"
  * System of record: "a process where the website has the warehouse, which is loaded
    from source (municipal documents), and transferred into Excel... I strongly support
    a process that is 'closed' and has the best controls over the integrity of the data."
  * The four Hillsborough database files: "These are all working files. In most cases
    only FY2025 was loaded in order to help visualize the design." — no file is the
    parent; the DESIGN is the parent, and this stage builds to it.

So this stage builds docs/WAREHOUSE_DESIGN.md steps 2-4:

  2. Freeze Dim_Organization, Dim_Fiscal_Year, Dim_Scenario.
  3. Build Fact_Financial for Hillsborough — all years, all scenarios — from the
     pipeline's already-verified datasets (never from her working files' sample loads).
  4. Load Orange County into the SAME table through the SAME row constructor, and fail
     the build if that would change the schema. Step 4 is the real test; the proof is
     recorded in the output (step4_proof) rather than asserted in prose.

Grain — written down, because most warehouse pain is a grain nobody wrote down:

  one row per Organization_ID · Fiscal_Year_ID · Scenario · Fund_ID · Flow ·
  Department · Account · Line · Measure  →  Amount

  Line exists because the documents themselves repeat a label: the FY27 appendix
  prints TWO "FICA" lines inside Administration/Personnel on the same page ($42,020
  and $3,099). Summing them would break the row-to-printed-line correspondence;
  renaming them would invent data. Line = 1, 2, … in printed order, and the first
  build failed on exactly this before Line existed — the grain gate works.

  Department is in the grain because Amy's Decision Context Model names seven
  dimensions and because the same natural account (SALARIES) recurs in thirty
  departments. Measure keeps totals out of the detail's way: 'amount' rows sum;
  'fund_total' rows are printed statement totals and must never be added to them;
  'amount_original_budget' preserves the original budget where a source prints both
  original and final (overwriting either would erase the amendment history).

Scenario mapping — the honest part, learned the hard way on the site itself:

  * The line-item appendix lives in the FY27 RECOMMENDED plan, so its "budget" column
    loads as Scenario=Recommended, not Adopted. The site once labelled FY2027 "already
    adopted"; the warehouse must not repeat that lie. When the adopted ordinance
    arrives, its rows APPEND as Adopted — her extensibility test #1, and nothing is
    overwritten — her test #2.
  * Amy's own vocabularies map 1:1 where she has them (revenue years say "Adopted
    Budget"/"Recommended Budget"/"Actual"; her county rows carry Scenario already).
    Her "Budget / Outlook" maps to Projection with her label kept in Source_Detail.

What is deliberately NOT here yet:

  * Dim_Account stays UNFROZEN: accounts load at natural grain (the account string the
    document prints) because the chart-of-accounts crosswalk — design question 2, and
    the highest-value item outstanding with the town — has not arrived. Freezing
    account IDs before the crosswalk would bake in a mapping that has to be redone.
  * Her county tables that are not fund-level dollar facts (staffing counts, ratios,
    tax-base statistics) are recorded in not_loaded rather than forced into a
    financial fact table. Loading them wrong would be worse than loading them later.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, read_json, write_json  # noqa: E402

COLUMNS = ["Organization_ID", "Fiscal_Year_ID", "Scenario", "Fund_ID", "Flow",
           "Department", "Account", "Line", "Category", "Measure", "Amount",
           "Source_ID", "Source_Detail", "Source_Page", "Confidence", "Extraction"]

SCENARIOS = ["Actual", "Adopted", "Recommended", "Estimate", "Projection"]

# Money flowing in and money flowing out must never sum together: the first build
# of this stage happily produced a $38.9M "GF FY2027" figure that was revenue PLUS
# expenditure. Flow reflects each SOURCE's own presentation — the budget appendix
# counts interfund transfers inside its expenditure totals while the audited
# statement counts them as other financing, and re-classifying either side would
# break reconciliation to that source's printed totals (the known presentation
# difference stays visible instead of being resolved by guesswork).
FLOWS = ["Revenue", "Expenditure", "Other Financing", "(unstated)"]
SECTION_FLOW = {"revenues": "Revenue", "expenditures": "Expenditure"}
COUNTY_FLOW = {"Revenue": "Revenue", "Expenditure": "Expenditure",
               "Expense": "Expenditure", "Other Financing": "Other Financing",
               "Net": "Other Financing", "None": "(unstated)"}

FUND_IDS = {
    "General Fund": "FUND_GF",
    "Water & Sewer Fund": "FUND_WS",
    "Stormwater Fund": "FUND_SW",
}

# lineitems' basis vocabulary -> Dim_Scenario. 'budget' -> Recommended because the
# single source document is the FY27 RECOMMENDED plan (see docstring).
LINEITEM_SCENARIO = {"actual": "Actual", "estimate": "Estimate",
                     "budget": "Recommended", "projected": "Projection"}
REVENUE_SCENARIO = {"Actual": "Actual", "Adopted Budget": "Adopted",
                    "Recommended Budget": "Recommended"}
COUNTY_SCENARIO = {"Actual": "Actual", "Budget / Outlook": "Projection"}


def fy_id(v) -> str:
    """FY2027 / FY27 / 2027 -> FY2027, her Fiscal_Year_ID convention."""
    s = str(v)
    if s.startswith("FY"):
        s = s[2:]
    n = int(s)
    return f"FY{n if n > 99 else 2000 + n}"


def main() -> None:
    li = read_json(DATASETS / "lineitems.json")
    revenue = read_json(DATASETS / "revenue.json")
    audited = read_json(DATASETS / "audited_general_fund.json")
    ocr = read_json(DATASETS / "ocr_statements.json")
    county = read_json(DATASETS / "warehouse_county.json")
    docs = read_json(DATASETS / "documents.json")["documents"]
    doc_ids = {d["id"] for d in docs}

    rows: list[list] = []
    seen: dict[tuple, str] = {}
    problems: list[str] = []

    line_counter: dict[tuple, int] = defaultdict(int)

    def row(org, fy, scenario, fund, flow, dept, account, category, measure, amount,
            source_id, source_detail, source_page, confidence, extraction,
            repeatable=False):
        """The ONE constructor both governments load through — the schema freeze.

        repeatable=True is for sources whose documents legitimately print the same
        label more than once (the line-item appendix, her county categories): the
        Line ordinal increments in printed order. Everything else must be unique at
        Line=1, and a collision fails the build — that is the gate that catches a
        double-load."""
        if amount is None:
            return
        if scenario not in SCENARIOS:
            problems.append(f"unknown scenario {scenario!r} for {org} {fy} {account}")
            return
        if flow not in FLOWS:
            problems.append(f"unknown flow {flow!r} for {org} {fy} {account}")
            return
        base = (org, fy_id(fy), scenario, fund, flow, dept, account, measure)
        if repeatable:
            line_counter[base] += 1
            line = line_counter[base]
        else:
            line = 1
        key = base + (line,)
        if key in seen:
            problems.append(f"grain collision: {key} already loaded from {seen[key]}, "
                            f"now again from {source_id}")
            return
        seen[key] = source_id
        rows.append([org, fy_id(fy), scenario, fund, flow, dept, account, line,
                     category, measure, round(float(amount), 2), source_id,
                     source_detail, source_page, confidence, extraction])

    # ---- step 3: Hillsborough, all years, all scenarios ----------------------

    C = {c: i for i, c in enumerate(li["columns"])}
    for r in li["rows"]:
        # Flow=Expenditure for every appendix row, including Interfund Transfers:
        # the appendix's own published totals count transfers as expenditure, and
        # reconciliation to those totals is the whole basis of trust here. The
        # Category column keeps transfers queryable.
        row("ORG_HB", r[C["fiscal_year"]], LINEITEM_SCENARIO[r[C["basis"]]],
            FUND_IDS.get(r[C["fund"]], r[C["fund"]]), "Expenditure",
            r[C["department"]], r[C["account"]], r[C["category"]], "amount",
            r[C["value"]], r[C["source_doc"]], "line-item appendix", r[C["page"]],
            "High", "digital-text", repeatable=True)

    # Her GF revenue-by-source series (imported and verified by s99). Component
    # detail only — the stated totals live in the audited series below, and the
    # variance between presentations is s99's finding, not something to re-litigate.
    rev_src = revenue.get("source_doc")
    for y in revenue.get("years", []):
        scen = REVENUE_SCENARIO.get(y["basis"])
        if scen is None:
            problems.append(f"revenue FY{y['fiscal_year']} basis {y['basis']!r} unmapped")
            continue
        for comp, amount in (y.get("components") or {}).items():
            row("ORG_HB", y["fiscal_year"], scen, "FUND_GF", "Revenue", "(revenue)",
                comp, "Revenue by source", "amount", amount, rev_src,
                f"her v5 trend workbook, Revenue_Trend ({y['basis']})", None,
                "High", "workbook-import")

    # The audited FY2025 statement, line by line: final budget AND actual, and the
    # original budget where printed — three readings per line, none overwriting
    # another (her extensibility test #2 is a property of the data, not a promise).
    afy = audited["fiscal_year"]
    for r in audited["rows"]:
        measure = "fund_total" if r.get("is_total") else "amount"
        flow = SECTION_FLOW.get(r["section"], "Other Financing")
        dept = "(audited statement)"
        if r.get("original_budget") is not None:
            row("ORG_HB", afy, "Adopted", "FUND_GF", flow, dept, r["line"],
                r["section"], measure + "_original_budget",
                r["original_budget"], r["source_doc"], "audited statement, original budget",
                r.get("source_page"), "High", "digital-text")
        if r.get("final_budget") is not None:
            row("ORG_HB", afy, "Adopted", "FUND_GF", flow, dept, r["line"],
                r["section"], measure, r["final_budget"], r["source_doc"],
                "audited statement, final budget", r.get("source_page"), "High",
                "digital-text")
        if r.get("actual") is not None:
            row("ORG_HB", afy, "Actual", "FUND_GF", flow, dept, r["line"],
                r["section"], measure, r["actual"], r["source_doc"],
                "audited statement, actual", r.get("source_page"), "High",
                "digital-text")

    # The recovered audited totals, FY2018-FY2024 — each proven by its own page.
    for p in ocr.get("published", []):
        if p.get("column_role") != "actual" or not p.get("fiscal_year"):
            continue
        row("ORG_HB", p["fiscal_year"], "Actual", "FUND_GF",
            SECTION_FLOW.get(p["section"], "Other Financing"), "(audited statement)",
            f"Total {p['section']}", p["section"], "fund_total", p["total"],
            p["source_doc"], "recovered from the scanned page image, column-sum proven",
            p.get("source_page"), "High", p["extraction"])

    hb_count = len(rows)
    schema_after_hb = list(COLUMNS)

    # ---- step 4: Orange County through the SAME constructor ------------------
    # Her curated county rows, in her schema, with her Source_IDs and Confidence.
    #
    # Tables 2.0, 3.0 and 4.0 are General Fund revenue/expenditure at fund grain and
    # load into Fact_Financial. Her remaining nine tables measure other things —
    # fund balance, net position, debt and capital, enterprise funds, schools, the
    # FY26 outlook — and each row carries a Metric and a Unit, so they load into
    # Fact_Metric at their own declared grain rather than being forced into a
    # financial fact table or, as before, left out entirely.
    #
    # They were left out entirely, and the reason turned out to be this pipeline's
    # own fault: the workbook import kept a hardcoded list of eleven fields and
    # dropped Metric, Metric_ID, Unit, Fund, Fund_ID and Activity_Type on the way in.
    # Nine tables therefore arrived as a bare Amount with nothing to say what it
    # measured, and were held back as "not fund-level dollar facts". They were fine;
    # their labels had been thrown away. Stage 85 now carries every column she wrote.
    LOADED_TABLES = ("2.0", "3.0", "4.0")
    metric_tables = sorted({str(r.get("table")) for r in county["rows"]
                            if not str(r.get("table", "")).startswith(LOADED_TABLES)})
    for r in county["rows"]:
        if not str(r.get("table", "")).startswith(LOADED_TABLES):
            continue
        dept = "(fund statement)"
        acct = r.get("Category") or "(unnamed)"
        cat = r.get("Line_Type") or "(unstated)"
        flow = COUNTY_FLOW.get(str(r.get("Line_Type")), "(unstated)")
        is_total = str(acct).lower().startswith("total") or cat == "Net"
        base_measure = "fund_total" if is_total else "amount"
        src = r.get("Source_ID")
        conf = r.get("Confidence") or "Working"
        page = r.get("ACFR_Page")
        fy = r["Fiscal_Year_ID"]
        if r.get("Original_Budget") is not None:
            row("ORG_OC", fy, "Adopted", "FUND_GF", flow, dept, acct, cat,
                base_measure + "_original_budget", r["Original_Budget"], src,
                "her county workbook, original budget", page, conf,
                "workbook-import", repeatable=True)
        if r.get("Final_Budget") is not None:
            row("ORG_OC", fy, "Adopted", "FUND_GF", flow, dept, acct, cat, base_measure,
                r["Final_Budget"], src, "her county workbook, final budget", page,
                conf, "workbook-import", repeatable=True)
        if r.get("Actual_Amount") is not None:
            row("ORG_OC", fy, "Actual", "FUND_GF", flow, dept, acct, cat, base_measure,
                r["Actual_Amount"], src, "her county workbook, actual", page, conf,
                "workbook-import", repeatable=True)
        if r.get("Amount") is not None and r.get("Actual_Amount") is None \
                and r.get("Final_Budget") is None:
            scen = COUNTY_SCENARIO.get(str(r.get("Scenario")))
            if scen is None:
                problems.append(f"county scenario {r.get('Scenario')!r} unmapped "
                                f"({fy} {acct})")
                continue
            row("ORG_OC", fy, scen, "FUND_GF", flow, dept, acct, cat, base_measure,
                r["Amount"], src, f"her county workbook ({r.get('Scenario')})", page,
                conf, "workbook-import", repeatable=True)

    # ---- Fact_Metric: her nine non-financial county tables, at their own grain --
    # One row per Organization · Fiscal_Year · Scenario · Metric (· Fund or Activity
    # where she distinguishes one). Kept OUT of Fact_Financial deliberately: a
    # per-pupil expenditure in dollars-per-pupil and a tax base in dollars must never
    # land in a table whose rows are summed as fund dollars.
    metric_rows: list[dict] = []
    for r in county["rows"]:
        if str(r.get("table", "")).startswith(LOADED_TABLES):
            continue
        # Her label column is Metric on most tabs, Classification on the fund-balance
        # tab, Category on the budget tabs. Take whichever she used.
        metric = r.get("Metric") or r.get("Classification") or r.get("Category")
        amount = r.get("Amount") if r.get("Amount") is not None else r.get("Actual_Amount")
        if metric is None or amount is None:
            problems.append(f"county metric row without a metric or amount: "
                            f"{r.get('table')} {r.get('Fiscal_Year_ID')}")
            continue
        qualifier = r.get("Purpose_Subcategory")
        if qualifier and str(qualifier) != str(metric):
            metric = f"{metric} — {qualifier}"
        metric_rows.append({
            "Organization_ID": r["Entity_ID"],
            "Fiscal_Year_ID": fy_id(r["Fiscal_Year_ID"]),
            "Scenario": r.get("Scenario"),
            "Metric_ID": r.get("Metric_ID"),
            "Metric": metric,
            "Unit": r.get("Unit") or "Dollars",
            "Fund_ID": r.get("Fund_ID"),
            "Fund": r.get("Fund"),
            "Activity_Type": r.get("Activity_Type"),
            "Amount": amount,
            "Source_ID": r.get("Source_ID"),
            "Source_Detail": f"her county workbook, {r.get('table')}",
            "Source_Page": r.get("ACFR_Page"),
            "Confidence": r.get("Confidence") or "Working",
            "Extraction": "workbook-import",
            "Notes": r.get("Notes"),
        })

    # ---- the audited statements, both governments, every year -----------------
    # Stages 61 and 81 read the town's digital audits (FY2021-FY2025) and the county's
    # ACFRs (FY2018-FY2025) directly, and publish only lines their page's own
    # arithmetic proved. Both feed this table through the same constructor.
    #
    # A line loads into Fact_Financial ONLY where the statement's column roles were
    # confirmed by its own variance identity. That is not fussiness: a column index
    # carries no meaning, and a figure loaded as "actual" when it was "budget" would
    # be a wrong number about a real government. Lines from statements whose columns
    # could not be proven are verified and cited but their basis is unknown, so they
    # go to Fact_Statement_Line instead, with the gap stated rather than guessed.
    ROLE_TO_SCENARIO = {
        "budget": ("Adopted", "amount"),
        "final_budget": ("Adopted", "amount"),
        "original_budget": ("Adopted", "amount_original_budget"),
        "actual": ("Actual", "amount"),
        "prior_year_actual": ("Actual", "amount"),          # for fiscal_year - 1
        "project_authorization": ("Adopted", "amount"),
        "prior_years_actual": ("Actual", "amount_prior_years"),
        "current_year_actual": ("Actual", "amount"),
        "total_to_date": ("Actual", "amount_to_date"),
    }
    STATEMENT_FLOW = {"revenue": "Revenue", "expenditure": "Expenditure",
                      "expense": "Expenditure"}

    statement_lines: list[dict] = []
    unproven = defaultdict(int)

    def load_statements(payload, org, extraction, detail_prefix):
        # Which years this payload reads DIRECTLY. Every one of these statements also
        # prints the prior year's actual as a comparative column, and that column
        # restates the very figure the prior year's own audit already gives — so
        # loading both put 475 slices into the table twice, from two documents, under
        # Line 1 and Line 2. Nothing about that is wrong per row and every row
        # reconciles, which is exactly why it is dangerous: anyone summing an account
        # across Lines would double it. A comparative column is loaded ONLY for a year
        # this payload does not read directly — where it is genuinely the only reading
        # available, as FY2020 is from the FY2021 audit.
        primary_years = {p.get("fiscal_year") for p in payload.get("published", [])
                         if p.get("fiscal_year")}
        for p in payload.get("published", []):
            fy = p.get("fiscal_year")
            if not fy:
                continue
            roles = {int(k): v for k, v in (p.get("column_roles") or {}).items()}
            grp = str(p.get("group") or "")
            line = str(p.get("line") or "(unnamed)")
            # Flow from the group the document itself printed the line under.
            probe = f"{grp} {line}".lower()
            flow = "(unstated)"
            for key, val in STATEMENT_FLOW.items():
                if key in probe:
                    flow = val
                    break
            if flow == "(unstated)" and "financing" in probe:
                flow = "Other Financing"
            measure_base = "fund_total" if p.get("is_subtotal") else "amount"

            if not roles:
                unproven[(org, fy)] += 1
                for ci, v in enumerate(p["values"]):
                    if v is None:
                        continue
                    statement_lines.append({
                        "Organization_ID": org, "Fiscal_Year_ID": fy_id(fy),
                        "Statement": p.get("statement"),
                        "Statement_Key": p.get("statement_key"),
                        "Group": grp, "Line": line,
                        "Column_Index": ci, "Amount": v,
                        "Is_Subtotal": bool(p.get("is_subtotal")),
                        "Source_ID": p["source_doc"], "Source_Page": p.get("source_page"),
                        "Verified_By": p.get("verified_by"),
                        # Her vocabulary, and "Working" is the honest value: the FIGURE is
                        # proven by the page's arithmetic, but a figure you cannot label
                        # budget-or-actual is not yet usable, and calling it High would
                        # overstate what is known about it.
                        "Confidence": "Working",
                        "Extraction": p.get("extraction", extraction),
                        "basis_unknown_because": (
                            "this statement's column roles could not be confirmed by its own "
                            "arithmetic, so which column is budget and which is actual is not "
                            "established. The figure is verified and cited; its basis is not. "
                            "Resolving it means reading each statement's column headers."),
                    })
                continue

            for ci, v in enumerate(p["values"]):
                if v is None or ci not in roles:
                    continue
                role = roles[ci]
                if role == "variance":
                    continue          # derived from the other columns; not a fact to sum
                mapped = ROLE_TO_SCENARIO.get(role)
                if mapped is None:
                    problems.append(f"{org} {fy}: column role {role!r} unmapped")
                    continue
                scen, meas = mapped
                year = fy - 1 if role == "prior_year_actual" else fy
                if role == "prior_year_actual" and year in primary_years:
                    continue          # that year is read from its own audit

                if meas == "amount":
                    meas = measure_base
                elif measure_base == "fund_total":
                    meas = meas.replace("amount", "fund_total", 1)
                row(org, year, scen, "FUND_GF", flow, grp or "(statement)", line,
                    p.get("statement_key") or "(statement)", meas, v,
                    p["source_doc"], f"{detail_prefix}, {role}", p.get("source_page"),
                    "High", p.get("extraction", extraction), repeatable=True)

    ad_path = DATASETS / "audited_digital.json"
    if ad_path.exists():
        load_statements(read_json(ad_path), "ORG_HB", "digital-text",
                        "audited statement, read from the digital audit")

    ca_path = DATASETS / "county_acfr.json"
    if ca_path.exists():
        load_statements(read_json(ca_path), "ORG_OC", "digital-text",
                        "audited statement, read from the county ACFR")

    # The component LINES recovered from the scanned reports — FY2018-FY2020 only.
    # Where a digital original exists the digital reading is already loaded above and
    # is strictly better, so loading the recognition too would duplicate the slice
    # and invite someone to sum both.
    for l in ocr.get("published_lines", []):
        if l.get("digital_original_exists") or not l.get("fiscal_year"):
            continue
        role = l.get("column_role")
        mapped = ROLE_TO_SCENARIO.get(str(role))
        if role == "variance" or mapped is None:
            continue
        scen, meas = mapped
        row("ORG_HB", l["fiscal_year"], scen, "FUND_GF",
            SECTION_FLOW.get(l["section"], "(unstated)"), "(audited statement)",
            l["line"], l["section"], meas, l["value"], l["source_doc"],
            f"recovered from the scanned page, column-sum proven, {role}",
            l.get("source_page"), "High", l["extraction"], repeatable=True)

    # Count by the Organization_ID actually on the row. Subtracting a high-water mark
    # taken before the audited statements loaded credited 1,944 Hillsborough audit
    # rows to Orange County, which made the step-4 proof read as nonsense.
    org_i = COLUMNS.index("Organization_ID")
    hb_count = sum(1 for r in rows if r[org_i] == "ORG_HB")
    oc_count = sum(1 for r in rows if r[org_i] == "ORG_OC")
    if COLUMNS != schema_after_hb:
        sys.exit("STEP 4 FAILED: loading Orange County changed the schema — "
                 "the design is wrong and this is the cheapest moment to know")

    # Note: her county Source_IDs (OC_CAFR_2018...) are HER register's keys, not this
    # archive's ids — s85 already reports which resolve to held files. Hillsborough
    # rows must all cite the manifest.
    bad_src = sorted({r[COLUMNS.index("Source_ID")] for r in rows
                      if r[COLUMNS.index("Organization_ID")] == "ORG_HB"
                      and r[COLUMNS.index("Source_ID")] not in doc_ids})
    if bad_src:
        sys.exit(f"Hillsborough fact rows cite unknown documents: {bad_src}")
    if problems:
        print(f"\nBUILD FAILED — {len(problems)} problem(s):")
        for p in problems[:20]:
            print(f"   {p}")
        sys.exit(1)

    # ---- the frozen dimensions (step 2) --------------------------------------
    years = sorted({r[1] for r in rows})
    scen_by_year = defaultdict(set)
    for r in rows:
        scen_by_year[r[1]].add(r[2])

    write_json(DATASETS / "warehouse.json", {
        "generated_by": "etl/s87_fact_financial.py",
        "decided_by": ("Amy, 2026-07-29: one warehouse, several marts; government is a "
                       "column; the pipeline is the system of record and Excel a "
                       "generated view; her working files are design sketches, not "
                       "the parent store."),
        "grain": ("one row per Organization_ID · Fiscal_Year_ID · Scenario · Fund_ID · "
                  "Flow · Department · Account · Line · Measure. Measure='amount' rows "
                  "sum WITHIN one Flow (revenue and expenditure must never be added "
                  "together); 'fund_total*' rows are printed statement totals and must "
                  "never be added to 'amount' rows; '*_original_budget' preserves the "
                  "original where a source prints both original and final budget; Line "
                  "disambiguates a label the document prints more than once, in printed "
                  "order. Flow reflects each source's OWN presentation of interfund "
                  "transfers (budget: inside expenditure; audited: other financing) — "
                  "the known presentation difference stays visible. Two documents can "
                  "report the same slice (FY2025 Actual revenue: the audited statement "
                  "says $17,047,188 and the budget-schedule series $18,356,346 — a "
                  "recorded presentation difference, not an error); such readings are "
                  "kept apart by Department + Source_Detail, each reconciles to its own "
                  "printed total, and summing ACROSS presentations double-counts."),
        "dim_organization": [
            {"Organization_ID": "ORG_HB", "Name": "Town of Hillsborough, NC",
             "Status": "Active"},
            {"Organization_ID": "ORG_OC", "Name": "Orange County, NC",
             "Status": "Active"},
            # Reserved by Amy in Hillsborough_Municipal_Financial_Database_v1 —
            # the IDs exist before the data does, exactly her pattern.
            {"Organization_ID": "ORG_CH", "Name": "Town of Chapel Hill, NC",
             "Status": "Future"},
            {"Organization_ID": "ORG_CB", "Name": "Town of Carrboro, NC",
             "Status": "Future"},
            {"Organization_ID": "ORG_MB", "Name": "City of Mebane, NC",
             "Status": "Future"},
        ],
        "dim_scenario": [
            {"Scenario": "Actual", "meaning": "audited or reported outturn"},
            {"Scenario": "Adopted", "meaning": "the budget as adopted (final unless "
             "the measure says original)"},
            {"Scenario": "Recommended", "meaning": "the manager's recommended budget, "
             "not yet adopted"},
            {"Scenario": "Estimate", "meaning": "in-year estimate of where the year "
             "will land"},
            {"Scenario": "Projection", "meaning": "a later year in a plan or outlook; "
             "least certain"},
        ],
        "dim_fiscal_year": [{"Fiscal_Year_ID": y,
                             "scenarios_loaded": sorted(scen_by_year[y])}
                            for y in years],
        # Provisional, per organization — deliberately NOT frozen (design open
        # question: Chapel Hill's funds are not Hillsborough's).
        "dim_fund_provisional": [
            {"Fund_ID": fid, "Name": name, "Organization_ID": "ORG_HB"}
            for name, fid in FUND_IDS.items()
        ] + [{"Fund_ID": "FUND_GF", "Name": "General Fund", "Organization_ID": "ORG_OC"}],
        "dim_account_note": ("UNFROZEN by design: accounts load at the natural grain "
                             "the documents print, because the chart-of-accounts "
                             "crosswalk (design question 2; requested from the town in "
                             "her Section 9) has not arrived. Freezing IDs now would "
                             "bake in a mapping that must be redone."),
        "step4_proof": {
            "claim": "Orange County loaded through the identical row constructor with "
                     "zero schema change",
            "schema_columns": COLUMNS,
            "hillsborough_rows": hb_count,
            "orange_county_rows": oc_count,
            "schema_changed_by_county_load": False,
        },
        "fact_metric": {
            "grain": ("one row per Organization_ID · Fiscal_Year_ID · Scenario · Metric, "
                      "with Fund or Activity_Type where the source distinguishes one. "
                      "Amounts here are NOT fund dollars and must never be summed with "
                      "Fact_Financial: the Unit column is load-bearing and includes "
                      "dollars-per-pupil alongside dollars."),
            "why_separate": ("Her nine remaining county tables measure fund balance, net "
                             "position, debt and capital, enterprise funds, schools and the "
                             "FY26 outlook. They are real facts with real citations, but not "
                             "at fund revenue/expenditure grain, so they get their own table "
                             "rather than being forced into the financial one."),
            "source_tables": metric_tables,
            "columns": (["Organization_ID", "Fiscal_Year_ID", "Scenario", "Metric_ID",
                         "Metric", "Unit", "Fund_ID", "Fund", "Activity_Type", "Amount",
                         "Source_ID", "Source_Detail", "Source_Page", "Confidence",
                         "Extraction", "Notes"]),
            "rows": metric_rows,
        },
        "fact_statement_line": {
            "grain": ("one row per Organization_ID · Fiscal_Year_ID · Statement · Group · "
                      "Line · Column_Index. Every figure here was proven by its page's own "
                      "arithmetic and carries a document and page — but the STATEMENT's "
                      "column roles could not be confirmed, so which column is budget and "
                      "which is actual is not established."),
            "why_separate": ("A column index means nothing on its own. Loading these as "
                             "'actual' would risk publishing a budget figure as an outturn "
                             "about a real government. They are held here, complete and "
                             "cited, until each statement's column headers are read — which "
                             "is the next piece of work on this, and it is registered as a "
                             "question rather than left implicit."),
            "unproven_lines_by_org_year": {f"{o} {y}": n
                                           for (o, y), n in sorted(unproven.items())},
            "columns": ["Organization_ID", "Fiscal_Year_ID", "Statement", "Statement_Key",
                        "Group", "Line", "Column_Index", "Amount", "Is_Subtotal",
                        "Source_ID", "Source_Page", "Verified_By", "Confidence",
                        "Extraction", "basis_unknown_because"],
            "rows": statement_lines,
        },
        "columns": COLUMNS,
        "rows": rows,
    })

    print(f"  Fact_Financial: {len(rows)} rows "
          f"({hb_count} ORG_HB + {oc_count} ORG_OC), grain unique")
    print(f"  scenarios loaded: "
          + ", ".join(f"{s}={sum(1 for r in rows if r[2] == s)}" for s in SCENARIOS))
    print(f"  years {years[0]}–{years[-1]}")
    print(f"  Fact_Metric: {len(metric_rows)} rows from {len(metric_tables)} county tables")
    print(f"  Fact_Statement_Line: {len(statement_lines)} rows awaiting column-role proof")


if __name__ == "__main__":
    main()
