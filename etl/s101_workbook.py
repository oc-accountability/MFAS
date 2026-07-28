"""Stage 101 — export everything to one Excel workbook, in Amy's own schema.

Her request:

    "One thing I will be looking for... is to have a data repository with all the data
     organized in a similar format to my excel spreadsheet
     Hillsborough_Municipal_Finance_Database_V1... Add additional tabs for any new content."

The file she names does not exist under that name; the lineage is
`Orange_County_Municipal_Finance_Database_v1.0` → `v1.1` → `..._Data_Warehouse_v1.2` →
`v2.0` → `..._Financial_Information_System_v2.2_Foundation`. This export follows the
**v2.2 Foundation** conventions rather than v1.1, because v2.2 is her own later evolution
of exactly this idea: numbered fact tabs, historical series rather than one year, a source
catalog, and a review dashboard. Matching the older shape would hand her back a structure
she had already outgrown.

**Her conventions, followed literally:**
  * every Fact tab ends with `Source_ID` and `Confidence`
  * `Fiscal_Year_ID` is the leading key, formatted `FY2027`
  * `Confidence` uses her vocabulary — High / Medium / Working / Pending
  * `Entity_ID` distinguishes the governments, and this adds `ORG_HILLSBOROUGH` beside her
    `ORG_OC`, because her workbook is county-centric and most of this data is the town's
  * Source_Register, Permanent_IDs, Dim_Fiscal_Year, Dim_Fund, Data_Quality_Gaps,
    Change_Log and Index all keep her column headings

**This file is GENERATED, and that is the one thing she must know about it.** It is rebuilt
from the datasets on every run, so anything typed into it is destroyed by the next build.
Her own workbooks stay hers and are never written to — stage 96 reads them and this stage
does not touch them. The README tab says so in the first cell anyone will read, because a
generated file that looks editable is a trap.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, DATASETS, read_json  # noqa: E402

OUT = DATA / "exports" / "MFAS_Data_Warehouse.xlsx"
HDR_FILL = PatternFill("solid", fgColor="1F3864")
HDR_FONT = Font(bold=True, color="FFFFFF", size=10)
TITLE_FONT = Font(bold=True, size=13)


def ds(name):
    p = DATASETS / f"{name}.json"
    return read_json(p) if p.exists() else {}


def fy(v):
    """Her fiscal-year key format — TWO digits.

    Corrected 2026-07-28. This exported FY2027 because it was built to her Orange County
    v2.2 workbook. Her Hillsborough database — the one she actually named — uses FY27, and
    a key that does not match hers will not join to her data.
    """
    if isinstance(v, int):
        return f"FY{v % 100:02d}"
    return v or ""


def sheet(wb, title, headers, rows, note=None, widths=None):
    ws = wb.create_sheet(title[:31])
    r = 1
    if note:
        ws.cell(1, 1, note).font = Font(italic=True, size=9, color="555555")
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(len(headers), 2))
        r = 2
    for c, h in enumerate(headers, 1):
        cell = ws.cell(r, c, h)
        cell.fill, cell.font = HDR_FILL, HDR_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = ws.cell(r + 1, 1)
    for row in rows:
        r += 1
        for c, v in enumerate(row, 1):
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            ws.cell(r, c, v)
    for c, h in enumerate(headers, 1):
        w = widths[c - 1] if widths and c - 1 < len(widths) else min(
            42, max(12, len(str(h)) + 4,
                    *(len(str(row[c - 1])) + 2 for row in rows[:60]
                      if c - 1 < len(row) and row[c - 1] is not None) or [12]))
        ws.column_dimensions[get_column_letter(c)].width = w
    return ws


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    facts = ds("facts").get("facts", [])
    docs = ds("documents").get("documents", [])
    metrics = ds("metrics").get("metrics", {})
    wb = Workbook()
    wb.remove(wb.active)
    index_rows = []

    def add(title, headers, rows, purpose, note=None, widths=None):
        sheet(wb, title, headers, rows, note=note, widths=widths)
        index_rows.append([title[:31], purpose, len(rows)])

    # ---- README — the warning has to be the first thing read ------------------
    ws = wb.create_sheet("README")
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 112
    lines = [
        ("MFAS Data Warehouse", ""),
        ("", ""),
        ("⚠ GENERATED FILE",
         "Rebuilt from the published datasets on every run of `make etl`. ANYTHING YOU TYPE IN "
         "HERE WILL BE DESTROYED by the next build. Treat it as a export to read from and copy "
         "out of, not a workbook to author in."),
        ("Your workbooks are safe",
         "This project READS your workbooks and never writes to them — there is a test that "
         "fails the build if that ever changes. Your authored files stay yours."),
        ("Purpose",
         "Everything the project publishes, in one place, in the schema of your "
         "Hillsborough_Municipal_Financial_Database — Organization_ID, FY## keys, "
         "Source_ID + Source_Detail. CORRECTED 2026-07-28: the first version of this "
         "export followed your Orange County v2.2 workbook instead, which was the wrong "
         "one to copy for town data."),
        ("Schema",
         "Every Fact tab ends with Source_ID and Confidence. Fiscal_Year_ID is FY####. "
         "Organization_ID separates the two governments: ORG_HB and ORG_OC — your own IDs."),
        ("Confidence", "High = an official published document. Medium = derived by this project "
                       "from official figures. Working = imported from an analysis workbook. "
                       "Pending = awaiting a source."),
        ("Where the numbers come from",
         "Source_Register lists every document with its SHA-256. A figure that cannot be traced "
         "to one of them is not published at all."),
        ("Generated", date.today().isoformat()),
        ("Live site", "https://oc-accountability.github.io/MFAS/"),
        ("Repository", "https://github.com/oc-accountability/MFAS"),
    ]
    for i, (k, v) in enumerate(lines, 1):
        ws.cell(i, 1, k).font = TITLE_FONT if i == 1 else Font(bold=True, size=10)
        c = ws.cell(i, 2, v)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    index_rows.append(["README", "What this file is, and the warning that it is generated", len(lines)])

    # ---- Change_Log ----------------------------------------------------------
    add("Change_Log", ["Version", "Date", "Change", "Notes"], [
        ["v1.0 export", date.today().isoformat(),
         "First generated export of the MFAS pipeline into the v2.2 Foundation schema",
         "Built at Amy's request. Adds the tabs that did not exist in her workbook: tax-rate "
         "history, revenue by source, capital projects, funded/declined requests, utility "
         "block rates, the structural measures and the open-questions register."],
    ], "Version history of this export")

    # ---- Source_Register — her columns ---------------------------------------
    src_rows = []
    for d in sorted(docs, key=lambda x: (x.get("jurisdiction") or "", x["filename"])):
        scan = d.get("text_layer") == "scan"
        src_rows.append([
            d["id"],
            "ORG_OC" if "Orange" in (d.get("jurisdiction") or "") else "ORG_HB",
            d["filename"],
            fy(d.get("fiscal_year")) if d.get("fiscal_year") else "",
            (d.get("category") or d.get("format") or "").title(),
            f"{d.get('pages')} pages" if d.get("pages") else "",
            "Excluded from extraction — scanned" if scan else "Machine-readable source",
            "Pending" if scan else "High",
            (d.get("sha256") or "")[:16] + "…" if d.get("sha256") else "",
        ])
    add("Source_Register",
        ["Source_ID", "Organization_ID", "Document", "Fiscal_Year", "Document_Type",
         "ACFR Page / Section", "Use in Model", "Confidence", "SHA-256 (first 16)"],
        src_rows, "Every source document, fingerprinted",
        note="A figure is only published if it traces to a row here. Scans are excluded because "
             "their hidden text scrambles digits.")

    # ---- Data_Dictionary -----------------------------------------------------
    add("Data_Dictionary", ["Table", "Field", "Definition", "Example", "Notes"], [
        ["All Fact Tables", "Organization_ID", "Permanent ID for the government", "ORG_HB",
         "Matches your Hillsborough database. ORG_OC is Orange County."],
        ["All Fact Tables", "Fiscal_Year_ID", "Fiscal year of the fact", "FY27",
         "June 30 year-end"],
        ["All Fact Tables", "Scenario", "Actual, Budget, Estimate, Projected, Recommended",
         "Budget", "Finer than Actual/Budget alone — the town publishes four bases"],
        ["All Fact Tables", "Source_ID", "Source register ID", "fy27-budget-message",
         "Traceable to Source_Register"],
        ["All Fact Tables", "Source_Page", "Page within the source document", "1",
         "Blank where the source states no page"],
        ["All Fact Tables", "Confidence", "High, Medium, Working, Pending", "High",
         "High = official document; Medium = derived here; Working = from an analysis workbook"],
        ["Fact_Published_Figures", "Metric", "Machine key for the measure",
         "county_property_tax_rate", "Defined in Metric_Registry"],
        ["Fact_Published_Figures", "Unit", "Unit of the value", "cents_per_100_valuation",
         "Never assume dollars — tax rates are cents per $100"],
    ], "Field conventions, matching your v2.2 Data_Dictionary")

    # ---- Permanent_IDs -------------------------------------------------------
    perm = [["ORG_HB", "Organization", "Town of Hillsborough", "", "Primary organization"],
            ["ORG_OC", "Organization", "Orange County", "", "County government (your ID)"]]
    for f, name, parent in [("FUND_GF", "General Fund", "ORG_HB"),
                            ("FUND_WS", "Water & Sewer Fund", "ORG_HB"),
                            ("FUND_SW", "Stormwater Fund", "ORG_HB")]:
        perm.append([f, "Fund", name, parent,
                     "Enterprise fund — paid by users, not taxes"
                     if f != "FUND_GF" else "Chief operating fund"])
    add("Permanent_IDs", ["ID", "ID_Type", "Name", "Parent_ID", "Definition / Notes"], perm,
        "Stable IDs, extending your scheme to the town")

    # ---- Dim_Fiscal_Year -----------------------------------------------------
    tco = ds("total_cost_of_ownership")
    years = sorted({f["fiscal_year"] for f in facts if f.get("fiscal_year")}
                   | {r["fiscal_year"] for r in tco.get("series", []) if r.get("fiscal_year")})
    reval = {2018, 2025, 2026}
    dim = []
    for y in years:
        audited = any(f["fiscal_year"] == y and f.get("basis") in ("actual", "audited")
                      for f in facts)
        dim.append([fy(y), fy(y), f"{y-1}-07-01", f"{y}-06-30",
                    "Closed" if audited else "Open",
                    "Audited Actual" if audited else "Budget / Projection",
                    "Complete" if audited else "In progress",
                    "Revaluation year / revenue-neutral rate applies" if y in reval else "",
                    "", ""])
    add("Dim_Fiscal_Year",
        ["Fiscal_Year_ID", "Fiscal Year", "Start Date", "End Date", "Financial Status",
         "Data Scenario", "Budget Status", "Revaluation Context", "Primary Actual Source",
         "Notes"], dim, "Fiscal years present in the data",
        note="Revaluation years matter: the rate falls because assessed values rise, so a "
             "falling rate is not a falling bill.")

    # ---- Metric registry -----------------------------------------------------
    add("Metric_Registry", ["Metric", "Label", "Unit", "Category", "Description"],
        [[k, v.get("label"), v.get("unit"), v.get("category"), v.get("description")]
         for k, v in sorted(metrics.items())],
        "What every metric key means")

    # ---- 1.0 the published figures ------------------------------------------
    add("1.0 Fact_Published_Figures",
        ["Organization_ID", "Fiscal_Year_ID", "Metric", "Value", "Unit", "Scenario",
         "Source_ID", "Source_Page", "Extraction", "Confidence"],
        [["ORG_OC" if f["metric"].startswith("county_") else "ORG_HB",
          fy(f.get("fiscal_year")), f["metric"], f.get("value"), f.get("unit"),
          (f.get("basis") or "").title(), f.get("source_doc"), f.get("source_page"),
          f.get("extraction"),
          "Medium" if f.get("extraction") == "derived" else "High"]
         for f in facts],
        "Every published figure, long format",
        note="This is the spine. Every number on the website is one of these rows.")

    # ---- 2.0 tax rate history ------------------------------------------------
    add("2.0 Fact_Tax_Rates_Hist",
        ["Fiscal_Year_ID", "County_Rate", "Town_Rate", "Combined_Rate",
         "School_District_Rate", "Fire_District_Rate", "Tax_On_Fixed_400k",
         "Corroborating_Editions", "Source_ID", "Confidence"],
        [[fy(r["fiscal_year"]), r.get("county_rate"), r.get("town_rate"),
          r.get("combined_rate"), r.get("school_district_rate"),
          r.get("fire_district_rate"), r.get("rate_on_fixed_400k"),
          r.get("corroborating_editions"),
          r.get("source", ""), "High" if r.get("corroborating_editions") else "Medium"]
         for r in tco.get("series", [])],
        "Both governments' tax rates, FY2013–FY2027",
        note="Dollars per $100 of assessed value. County rates come from ACFR Table 5, NOT "
             "Table 6 — Table 6's county column has a misplaced decimal in every edition held. "
             "Tax_On_Fixed_400k compares years on rate alone; it is NOT a bill history.")

    # ---- 3.0 revenue ---------------------------------------------------------
    rev = ds("revenue")
    rev_rows = []
    for y in rev.get("years", []):
        for k, v in (y.get("components") or {}).items():
            rev_rows.append([fy(y["fiscal_year"]), k, v,
                             (y.get("share_of_total") or {}).get(k),
                             y.get("basis"), y.get("state"),
                             "Hillsborough_GF_Trend_Schedules_v5", "Working"])
    add("3.0 Fact_GF_Revenue_Hist",
        ["Fiscal_Year_ID", "Revenue_Source", "Amount", "Share_Of_Total_Pct", "Scenario",
         "Reconciliation_State", "Source_ID", "Confidence"], rev_rows,
        "General Fund revenue by source",
        note="Shares are only filled where the components sum to the published total. Budget "
             "years reconcile exactly; audited years differ by up to $2.9M on a presentation "
             "difference that is a question for the town.")

    # ---- 4.0 capital projects ------------------------------------------------
    proj = ds("projects")
    add("4.0 Fact_Capital_Projects",
        ["Project_ID", "Project", "Organization_ID", "Fund", "Department", "Priority_Rank",
         "Plan_Window", "Total_Planned_Cost", "Creates_Recurring_Cost",
         "Recurring_Portion", "Funding_Unnamed", "Source_ID", "Source_Page", "Confidence"],
        [[p["project_id"], p["project_name"], "ORG_HB", p.get("fund"),
          p.get("department"), p.get("priority_rank"), p.get("plan_window"),
          p.get("total_planned_cost"), p.get("creates_recurring_cost"),
          (p.get("operating_budget_impact_quantified") or {}).get("recurring_portion"),
          any(f.get("unnamed_in_source") for f in p.get("funding_by_source", [])),
          p.get("source_doc"), (p.get("source_pages") or [None])[0], "High"]
         for p in proj.get("projects", [])],
        "The 27-project capital register",
        note="Every project reconciled to its own printed totals, per year column. "
             "Funding_Unnamed flags projects whose funding source the document does not name.")

    # ---- 5.0 / 6.0 requests --------------------------------------------------
    tr = ds("tradeoffs")
    for n, key, label in (("5.0", "declined", "declined"), ("6.0", "funded", "funded")):
        add(f"{n} Fact_Requests_{label.title()}",
            ["Fiscal_Year_ID", "Request", "Fund", "Department", "FY2027", "Three_Year_Total",
             "Impact_If_Not_Funded", "Source_ID", "Source_Page", "Confidence"],
            [["FY2027", r["request"], r.get("fund"), r.get("department"), r.get("fy2027"),
              r.get("total_three_year"), r.get("impact_if_not_funded"),
              "fy27-budget-and-financial-plan-recommended", r.get("source_page"), "High"]
             for r in tr.get(key, [])],
            f"New spending requests the town {label}",
            note=("The town publishes both lists. Impact_If_Not_Funded is the town's own words."
                  if key == "declined" else "The funded side of the same decision."))

    # ---- 7.0 utility block rates --------------------------------------------
    ur = ds("utility_rates")
    urows = []
    for name, rs in (ur.get("rate_sets") or {}).items():
        for basis in ("current", "recommended"):
            b = rs[basis]
            urows.append([fy(b["fiscal_year"]), rs["service"].title(), rs["location"].title(),
                          b["threshold_gallons"], b["block1_charge"], b["block2_per_1000"],
                          basis.title(), "fy27-budget-and-financial-plan-recommended", "High"])
    add("7.0 Fact_Utility_Block_Rates",
        ["Fiscal_Year_ID", "Service", "Location", "Threshold_Gallons", "Block1_Charge",
         "Block2_Per_1000", "Scenario", "Source_ID", "Confidence"], urows,
        "Water and sewer block rates",
        note="Block 1 covers the first N gallons; Block 2 is per 1,000 above it. This structure "
             "reproduces all eight increase figures the town states in prose.")

    # ---- 8.0 the structural measures ----------------------------------------
    st = ds("structure")
    b = st.get("reading_burden", {})
    sep = st.get("run_separately", {})
    add("8.0 Fact_Structure_Measures",
        ["Measure", "Value", "Unit", "Notes", "Source_ID", "Confidence"], [
            ["Governments a resident must read", b.get("governments_a_resident_must_read"),
             "count", "To answer why a bill went up", "manifest", "High"],
            ["Documents, current budget cycle", b.get("current_cycle_documents"), "count", "",
             "manifest", "High"],
            ["Pages, current budget cycle", b.get("current_cycle_pages"), "pages",
             "A floor — only documents this pipeline could measure", "manifest", "High"],
            ["Town administration (broad)", (sep.get("administration_broad") or {}).get("total"),
             "USD", "Share of General Fund: "
             f"{(sep.get('administration_broad') or {}).get('share_of_general_fund_pct')}%",
             "lineitems", "Medium"],
            ["Town administration (narrow)", (sep.get("administration_narrow") or {}).get("total"),
             "USD", "Excludes Communications and Facility Management — the boundary is arguable",
             "lineitems", "Medium"],
            ["County administration", None, "USD",
             "NOT EXTRACTED — publishing the town's figure alone would invite a comparison "
             "against nothing", "", "Pending"],
        ], "What it costs a resident to answer one question",
        note="Poses the structural question. It does NOT answer whether two administrations cost "
             "more than one — no document in the archive compares them.")

    # ---- Amy's own imported analysis ----------------------------------------
    wbb = ds("workbook_b")
    add("9.0 Fact_Change_Drivers",
        ["Driver", "Amount", "Cents_Equivalent", "Period", "Budget_Category", "Commentary",
         "Follow_Up_Question", "Source_ID", "Confidence"],
        [[m["driver"], m.get("amount"), m.get("cents_equivalent"), m.get("period"),
          m.get("budget_category"), m.get("commentary"), m.get("follow_up_question"),
          m.get("source"), (m.get("confidence") or "Working")]
         for m in wbb.get("material_change_drivers", [])],
        "Your Material Change Drivers, imported",
        note="Imported from your v5 Audit Edition and never modified. Cents_Equivalent is "
             "recomputed here from the town's published $240,000 per cent.")

    # ---- Data_Quality_Gaps + the register, in her columns -------------------
    reg = ds("questions")
    gaps, qrows = [], []
    for r in reg.get("register", []):
        qrows.append([r["id"], r["owner"], r["topic"], r["question"], r["status"],
                      r.get("why_it_matters"), r.get("answer"), r.get("raised_by")])
        if r["status"] != "answered":
            gaps.append([r["id"],
                         "High" if r["owner"] in ("town", "county") else "Medium",
                         r["topic"], r["status"].title(), r.get("why_it_matters") or "",
                         {"town": "Records request to the Town",
                          "county": "Records request to the County",
                          "amy": "Your decision",
                          "david": "Repository owner action",
                          "pipeline": "Work this project owes"}.get(r["owner"], "")])
    add("Data_Quality_Gaps",
        ["Gap_ID", "Priority", "Topic", "Current Status", "Why It Matters",
         "Likely Resolution / Next Steps"], gaps, "Open gaps, in your schema")
    add("Open_Questions",
        ["ID", "Owner", "Topic", "Question", "Status", "Why It Matters", "Answer", "Raised By"],
        qrows, "The full register, including answered items",
        note="Answered items are kept — a question that quietly vanishes is indistinguishable "
             "from one that was forgotten.")

    # ---- Index (her convention: last, listing every tab) ---------------------
    sheet(wb, "Index", ["Tab", "Purpose", "Rows"], index_rows,
          note="Every tab in this workbook.")
    wb.move_sheet("Index", offset=-(len(wb.sheetnames) - 1))
    wb.move_sheet("README", offset=-(len(wb.sheetnames) - 1))

    wb.save(OUT)
    size = OUT.stat().st_size
    print(f"  wrote {OUT.relative_to(DATA.parent)}  ({size / 1024:.0f} KB, "
          f"{len(wb.sheetnames)} tabs)")
    for t, purpose, n in index_rows:
        print(f"      {t:34} {n:6} rows   {purpose[:44]}")


if __name__ == "__main__":
    main()
