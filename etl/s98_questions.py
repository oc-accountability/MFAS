"""Stage 98 — the open-questions register Amy asked for.

Her request, verbatim:

    "Please keep a log of all your questions and follow up's and the status of each.
     I need this to keep track of any open questions that I need to address."

Until now these lived scattered across a dozen dataset files — a `gaps` list here, a
`caveats` list there, a `problems` array in another — plus her own `Questions_for_Town`
sheet and the follow-up question she wrote against each material change driver. Nobody
could see the whole list, which is exactly the complaint.

So this stage collects every one of them into a single register, and gives each an
**owner**, because the useful question is not "what is unresolved" but "who is the only
person who can resolve it". Four owners:

  * **town** / **county** — needs a records request or an answer from a government. She
    is the only one who can ask.
  * **amy** — a modelling or editorial decision that is hers to make, not something to
    be extracted from a document.
  * **david** — an account-level action, e.g. renaming the repository.
  * **pipeline** — work this project can do without anyone else.

The register is built from the datasets themselves rather than maintained by hand, so it
cannot drift out of date: close a gap in a stage and it leaves this list on the next run.
Items that are answered are kept with `status: answered` and the answer recorded, because
a question that quietly vanishes is indistinguishable from one that was forgotten.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, read_json, write_json  # noqa: E402


def ds(name):
    p = DATASETS / name
    return read_json(p) if p.exists() else {}


def main() -> None:
    reg: list[dict] = []
    seq = [0]

    def add(owner, topic, question, *, status="open", why=None, source=None,
            answer=None, asked=None, blocks=None):
        seq[0] += 1
        reg.append({"id": f"Q{seq[0]:03d}", "owner": owner, "topic": topic,
                    "question": question, "status": status, "why_it_matters": why,
                    "raised_by": source, "answer": answer, "raised": asked,
                    "blocks": blocks})

    tco = ds("total_cost_of_ownership.json")
    wbb = ds("workbook_b.json")
    ctx = ds("context.json")
    mfas = ds("mfas_conformance.json")
    proj = ds("projects.json")
    trade = ds("tradeoffs.json")
    docs = ds("documents.json").get("documents", [])
    facts_all = ds("facts.json").get("facts", [])

    # Counted from the datasets on every run. The first version of the masthead item
    # hardcoded "40 of the 75 documents" — in the very commit that raised the manifest
    # to 84 — inside a register whose own header says it cannot drift out of date.
    n_docs = len(docs)
    n_county = sum(1 for d in docs if d.get("jurisdiction") == "Orange County, NC")
    by_id = {d["id"]: d for d in docs}
    n_initiative_facts = sum(1 for f in facts_all
                             if by_id.get(f.get("source_doc"), {}).get("category")
                             in ("records-request", "issues"))
    n_pageless_facts = sum(1 for f in facts_all
                           if f.get("source_doc") and not f.get("source_page"))
    burden = ds("structure.json").get("reading_burden", {})

    # ---- questions only a government can answer ------------------------------
    for q in wbb.get("her_open_questions_to_the_town", []):
        add("town", q.get("topic") or "Town", q.get("question"),
            source="Amy's v5 Audit Edition, Questions_for_Town",
            why="From your Questions_for_Town sheet; it needs a records request or a staff answer.")

    add("county", "Sales tax for schools",
        "What is the county's sales tax rate dedicated to schools, and what does it raise? "
        "Amy recalls roughly a half-cent. The town's local option sales tax REVENUE is now "
        "sourced FY18-FY29, but that is a different measure and a different government.",
        why="It is part of the total cost of ownership and currently has no source.",
        source="Amy's request; gap reported by etl/s92_total_cost.py",
        status="awaiting upload",
        answer="Partially landed 2026-07-29: 'White Paper-Basics of Local Sales Taxes.pdf' "
               "is now in the archive — it explains the NC local-option articles (Article 40 "
               "and 42 carry the school earmarks) but contains no Orange County figures. "
               "UPDATE, later 2026-07-29: Amy also uploaded RES-2022-041, the county Board "
               "of Commissioners' resolution on continued uses of the Article 46 "
               "one-quarter-cent sales and use tax — the county-specific document this item "
               "wanted. Caution: its embedded text layer interleaves characters (the known "
               "scan trap), so its figures need careful transcription from the page image "
               "before any number from it is published. Still needed after that: the "
               "current proceeds and the school share in dollars.")

    add("town", "Utility rate history",
        "Water and sewer rate schedules for years before FY2026.",
        why="The FY2026 and FY2027 structures are exact, so a bill can be computed at any "
            "consumption, but the series cannot be trended backwards without the older "
            "schedules. The rate studies held are slide decks without the underlying tables.",
        source="gap reported by etl/s93_utility_rates.py",
        status="awaiting upload",
        answer="A file landed 2026-07-29 ('water and sewer historical rates.docx') and is "
               "archived — but its own first line says 'Source: Gemini AI', so under the one "
               "rule its figures cannot be published: an AI answer is not a source document. "
               "Its reference links are real leads, though — the town's water-and-sewer-rates "
               "page and three town news posts are recorded in this item. Still needed: the "
               "town's PUBLISHED rate schedules for years before FY2026. UPDATE, later "
               "2026-07-29: Amy saved the town's own rates page as PDF ('Water and Sewer "
               "Rates _ Town of Hillsborough...') plus the Stormwater Fees page — both now "
               "archived. They carry the CURRENT schedule (corroborating this pipeline's "
               "extraction exactly: $13.32/1,000 gal water in-town, $26.64 minimum) and "
               "FY2026, but not the earlier history; she plans to ask the Finance Director "
               "to confirm the earlier years with supporting documentation. Exactly right.")

    if proj.get("data_quality_findings"):
        f = proj["data_quality_findings"][0]
        add("town", "Unnamed capital funding",
            "Which funding sources pay for the projects whose funding table prints "
            "\"Empty Values\" instead of a source name? The largest is the Passenger Rail "
            "and Multi-Modal Station.",
            why=f"${f.get('amount_unnamed', 0):,.0f} of planned capital funding is "
                f"unlabelled across {len(f.get('projects', []))} projects.",
            source="etl/s94_projects.py")

    err = tco.get("source_error") or {}
    if err.get("finding"):
        add("county", "Tax rate table error",
            "Table 6 of the county ACFR prints the Orange County tax rate with the decimal "
            "point one place left — $0.086290 for 2025 where Table 5 prints 0.8629 — in all "
            "five editions held, and its 'Total direct rate' row inherits the error. Is this "
            "a known error, and will it be corrected?",
            why="A resident reading Table 6 would conclude the county taxes them at a seventh "
                "of the town's rate, when the county rate is the larger of the two.",
            source="etl/s92_total_cost.py, proven by a ten-for-ten identity against Table 5")

    # ---- decisions that are Amy's to make ------------------------------------
    org = ctx.get("organization_vs_government") or {}
    if org.get("still_needed"):
        add("amy", "Organization vs Government",
            org["still_needed"],
            status="in progress",
            answer="Her direction, 2026-07-29: the county-funded bodies could be BOTH — "
                   "elements of an Organization, and elements of Funds where they receive "
                   "separately tracked funding — \"if this is the case, we should have both "
                   "views\". Confirmed: the dimensional design supports exactly that (an "
                   "organization view and a fund view over the same rows). Final modelling "
                   "waits until the county data is extracted at that grain.",
            why="Your project scope defines two Governments with nine domains each, so the "
                "structure is known. Which level the county-funded bodies belong to is a "
                "modelling choice rather than something a document can settle.",
            source="etl/s97_context.py; her direction 2026-07-29")

    for gap in mfas.get("what_would_close_the_gaps", []):
        if gap.lower().startswith("project:"):
            continue                       # closed by s94
        add("amy", "MFAS dimensions", gap,
            why="Needed before this data could load into MFAS cleanly.",
            source="etl/s88_mfas_dimensions.py")

    add("amy", "Community Values",
        "Should the Community Values come from the town's Comprehensive Sustainability Plan "
        "and Strategic Plan, or would you rather define the list first?",
        why="You define Values as adopted priorities evidenced by plans and ordinances, not "
            "opinions — so which document they come from matters more than the wording.",
        source="asked 2026-07-27; not yet answered")

    add("amy", "Activities list",
        "Shall this project propose an activities list from the budget documents for you to "
        "correct, or will you define it?",
        why="Activity is the one MFAS dimension still only partial — department is a proxy for "
            "it, but department is who spends, not what the money does.",
        source="asked 2026-07-27; not yet answered")

    add("amy", "Water usage baseline",
        "Confirm your household's typical monthly water usage. Your ~$2,100 annual bill "
        "implies about 5,100 gallons a month at FY2027 in-town rates, which supports your own "
        "reading that the 9,000-gallon month was a summer outlier.",
        why="The site now accepts any usage, so nothing depends on this — but it is worth "
            "confirming the model reproduces a real bill.",
        source="her reply 2026-07-27",
        status="answered",
        answer="Model check: 5,000 gal/month gives $2,044/year against her stated ~$2,100 — "
               "within 3%. Treated as corroboration of the rate structure, not as her data.")

    add("amy", "Wording — where figures come from",
        "The masthead used to read \"Every figure comes from the town's own published "
        "documents\". It now reads that every figure is shown with its document and page, and "
        "that the page says so on the spot wherever a figure comes from something other than a "
        "government's own publication. Is that the wording you want?",
        why=f"The original sentence was not quite true and a sceptical reader could catch it: "
            f"{n_county} of the {n_docs} documents concern Orange County rather than the town, "
            f"and {n_initiative_facts} of the {len(facts_all)} published figures come from the "
            f"initiative's own request workbook — the administrative-spend series a "
            f"commissioner supplied, and two capital-project cost changes. Each of those is "
            f"already labelled where it appears. (The masthead was not the only place: the "
            f"page's meta description carried the same claim and was corrected separately.) "
            f"Changed rather than left, because the strongest sentence on the page is the "
            f"worst one to have to walk back.",
        source="site audit 2026-07-28; enforced by "
               "tests/test_data_integrity.py::test_the_masthead_does_not_overclaim_where_figures_come_from",
        status="answered",
        answer="David settled it on 2026-07-29: the corrected wording stands and is live. Kept "
               "here because it is a change to the most prominent sentence on the site and to "
               "how the project describes its own sourcing — if you would put it differently, "
               "say so and it changes. Nothing about it is expensive to revisit.")

    add("amy", "Resident film",
        "The 62-second film is now on the site itself, as a still image in the masthead that "
        "loads nothing until it is pressed. Should it stay an offer a reader can ignore, or "
        "lead the page?",
        why="It only appeared in the README before, where no resident will ever look. Placed as "
            "an offer on the judgement that a reader who arrives annoyed about a tax bill wants "
            "their own number first — but it is your film and the call is yours.",
        source="site audit 2026-07-28",
        status="answered",
        answer="David settled it on 2026-07-29: it stays an offer. The reader reaches the "
               "calculator, or a button pointing at it, before the film in every layout, and "
               "nothing of the film downloads until somebody presses play.")

    add("amy", "Resident film",
        "At about 50 seconds the film shows a screenshot of the site carrying a sentence that "
        "has since been corrected — the old \"nothing on this page is taken from those\" line "
        "about scanned documents. Is that worth a re-cut?",
        why=f"The sentence was superseded because the site now publishes the audited record "
            f"recovered from those scans. Since this was first raised, a second audit widened "
            f"it: the narration itself says at ~49s that \"Every figure names the document and "
            f"the page it came from\", which overpromises the same way the old masthead did "
            f"({n_pageless_facts} figures come from spreadsheet cells that have no page); and "
            f"the film's \"2 governments / 6 documents / 1,031 pages\" hold shows counts that "
            f"changed when the archive's duplicate county budget stopped being counted twice "
            f"(now {burden.get('current_cycle_documents', '?')} documents, "
            f"{burden.get('current_cycle_pages', '?')} pages — the masthead card was switched "
            f"to the film's opening question so the stale figures no longer sit on the front "
            f"page, but they remain inside the film). Re-cutting means regenerating machine "
            f"narration and music, so it is a cost and an ownership question rather than a "
            f"fix this project should make unasked.",
        source="site audit 2026-07-28; widened by the second-pass audit 2026-07-28",
        status="answered",
        answer="David settled it on 2026-07-29, and the reasoning is worth keeping: a film is a "
               "snapshot of the day it was cut, not a view onto live data. The archive will keep "
               "moving — documents get deduplicated, figures get re-checked — and the film cannot "
               "be re-recorded every time it does, so the sensible thing is to let it be a film. "
               "It is left exactly as cut, and no correction is carried on the page beside it "
               "either: the site's own figures are the ones that must be right and are checked on "
               "every build, and annotating a 62-second introduction with the archive's revision "
               "history would tell a resident nothing they came for. Anyone reading a figure off "
               "the film and wanting to rely on it will find the current one, sourced, on the "
               "page it is advertising. Amy added on 2026-07-29 that she does want to do some "
               "work on the video and likes it overall, with marketing in mind (TikTok, X, "
               "NextDoor) — so any future cut is hers to drive, and the film-making pipeline "
               "is ready when she is.")

    # ---- work this project owes ----------------------------------------------
    add("pipeline", "Revenue by source",
        "Build the broader revenue view she asked for — grants, state-shared revenue, other "
        "funds — not just property tax and sales tax.",
        why="Her words: \"The broader view includes revenue from sources such as Grants, "
            "State, Other Funds, etc. So I want to make sure we have this broader view too.\"",
        source="her reply 2026-07-27", status="in progress")

    add("pipeline", "Stacked waterfall",
        "Show the key drivers as a stacked waterfall of increases and decreases.",
        why="Her stated preference for the visual, and her own Workbook B opens with a Budget "
            "Waterfall sheet.",
        source="her reply 2026-07-27", status="in progress")

    for gap in tco.get("gaps", []):
        if "sales tax" in gap.lower() or "water and sewer base" in gap.lower():
            continue                       # already registered above with an owner
        add("pipeline", "Total cost of ownership", gap,
            source="etl/s92_total_cost.py")

    add("amy", "README film links if the repo moves",
        "If this repository is transferred to another GitHub account, the two film links at the top "
        "of the README have to be updated — they are absolute Pages URLs.",
        why="They cannot be repo-relative: GitHub's blob viewer refuses the file outright (\"we "
            "can't show files that are this big right now\") and raw.githubusercontent serves it "
            "as application/octet-stream, which downloads instead of playing. Only Pages serves it "
            "as video/mp4 with Accept-Ranges. Measured, not assumed.",
        source="found 2026-07-28 when the blob link failed")

    add("david", "Repository name",
        "Rename the GitHub repository from `hoa-funds` to something that matches the project.",
        status="answered",
        answer="Done 2026-07-28 — renamed to `MFAS`. git URLs redirect permanently; GitHub Pages "
               "does NOT, and Pages paths are case-sensitive, so the live address is "
               "https://oc-accountability.github.io/MFAS/ while both /hoa-funds/ and /mfas/ 404. "
               "Every link sent before the rename is dead and needs re-sending.",
        why="The project is MFAS; \"hoa\" reads like a homeowners association and was the name "
            "of the empty repository this was first pushed into.",
        source="Amy 2026-07-27; renamed by David 2026-07-28")

    # ---- questions already answered, kept so they cannot silently vanish -----
    add("amy", "Project dimension",
        "Should Project be a real dimension?",
        status="answered", answer="Yes — built in etl/s94_projects.py: 27 projects, $72.6M, "
                                  "each reconciled to its own printed totals.",
        source="asked 2026-07-26")
    add("amy", "Recurring vs one-time",
        "Add a dimension separating ongoing operations from one-time items.",
        status="answered", answer="Built in etl/s88_mfas_dimensions.py. General Fund FY2027 is "
                                  "86.6% recurring.",
        source="her instruction 2026-07-26")
    add("amy", "Cross-fund transfers",
        "A schedule with the transfer columns going across.",
        status="answered", answer="Built in etl/s89_transfers.py, outgoing side only — the "
                                  "limitation is stated in the dataset.",
        source="her instruction 2026-07-26")

    # Her per-driver follow-up questions are hers to put to the town; they are carried
    # verbatim rather than rewritten, since she chose the wording.
    for m in wbb.get("material_change_drivers", []):
        if m.get("follow_up_question"):
            add("town", f"Driver: {m.get('driver')}", m["follow_up_question"],
                why=(f"Her own follow-up against a "
                     f"${m['amount']:,.0f} driver" if m.get("amount") else None),
                source="Amy's v5 Audit Edition, Material_Change_Drivers")

    # ---- raised by the second-pass audit, 2026-07-28 -------------------------
    # New items are appended AFTER every pre-existing one on purpose: ids are
    # sequence positions, and inserting mid-list renumbers every later item (which
    # b4321db did — see the id-stability question below).
    add("amy", "County workbook — Source_Register alignment",
        "Six of the eight county summary rows the site shows (Source_IDs OC_ACFR_2021 through "
        "OC_ACFR_2025, and OC_CAFR_2019) cite reports that are not in your workbook's own "
        "Source_Register, so this build cannot resolve them to a held file and re-check the "
        "figures. The FY2019 CAFR itself is not in the archive at all. Could the "
        "Source_Register gain rows for those years — and do you have the FY2019 CAFR to add?",
        why="The county table's figures are yours and are published as yours, but only FY2018's "
            "row can currently be re-verified against a held report. Aligning the register "
            "makes every year checkable the way FY2018 already is.",
        source="second-pass audit 2026-07-28; measured by etl/s85_warehouse.py")

    add("town", "Dam Repairs — funding vs expenditure totals",
        "In the FY27 capital plan, the Dam Repairs project's funding sources total $2,915,840 "
        "while its expenditures total $2,861,320 — funding exceeds spending by $54,520, and "
        "each table reconciles to its own printed total. Which figure is authoritative, and "
        "what does the $54,520 difference represent?",
        why="Both tables are printed in the same document and both add up internally, so this "
            "is a question about the document rather than an extraction error — exactly the "
            "kind of difference a resident checking the numbers would find.",
        source="second-pass audit 2026-07-28; measured from data/datasets/projects.json")

    add("david", "Question-register id stability",
        "Register ids are sequence positions, so inserting an item renumbers every later one — "
        "the 2026-07-28 insertions moved Q019 to Q022, and any Q-number cited in an earlier "
        "email now points at a different question. Should ids become stable slugs (breaking "
        "all existing references once), or stay positional with a rule that new items only "
        "ever append?",
        why="Amy asked for this register specifically to track her open questions; an id that "
            "silently changes meaning defeats that. Append-only is the interim rule as of this "
            "audit, but it relies on discipline rather than the generator.",
        source="second-pass audit 2026-07-28")

    add("amy", "Wording — who adopts the budget",
        "The speak-up section used to say the budget is adopted by \"the mayor and Board of "
        "Commissioners\". No document in the archive states the adoption mechanics — so it "
        "was flagged rather than silently rewritten.",
        status="answered",
        answer="Answered by her research, 2026-07-29: Hillsborough's Board of Commissioners "
               "is officially defined as the mayor plus five commissioners, and on budget "
               "adoption the mayor votes only to break a tie. The site now says \"adopted by "
               "the town's Board of Commissioners\" — precise, and correct on her reading "
               "since the mayor is part of that board. Note: this rests on her research, not "
               "on a document in the archive; the town charter would settle it permanently.",
        why="A claim about who exercises a power is the kind a resident can check against the "
            "town charter.",
        source="second-pass audit 2026-07-28; answered by Amy 2026-07-29")

    add("pipeline", "Stormwater Fund reconciliation checks",
        "The spending explorer's reconciliation gate covers the General Fund and Water & Sewer "
        "(30 checks each) but emits no checks at all for the Stormwater Fund, so its slices "
        "render with no verification statement either way. Emit Stormwater checks in stage 50 "
        "from the appendix's own category totals.",
        why="A fund with no checks is indistinguishable on screen from a fund that failed "
            "them. The explorer now says so explicitly, but the honest fix is to run the "
            "checks.",
        source="second-pass audit 2026-07-28; measured from data/datasets/lineitem_validation.json")

    # ---- the warehouse decisions, answered by Amy 2026-07-29 -----------------
    # Recorded here so the decisions live in the register, not only in an email
    # thread. Her words, verbatim where they are the answer.
    add("amy", "Warehouse — system of record",
        "Is Excel the system of record, or the window onto it?",
        status="answered",
        answer="Answered 2026-07-29. Her interpretation, confirmed: \"a process where the "
               "website has the warehouse, which is loaded from source (municipal "
               "documents), and transferred into Excel... I strongly support a process "
               "that is 'closed' and has the best controls over the integrity of the "
               "data.\" The pipeline is the store; the Excel export is a generated view, "
               "always current, never hand-edited. Her authored workbooks remain "
               "authored — read, never written.",
        source="Amy's email 2026-07-29; docs/WAREHOUSE_DESIGN.md question 1")

    add("amy", "Warehouse — which file is the parent",
        "Which of the four Hillsborough database files is the real parent?",
        status="answered",
        answer="Answered 2026-07-29: \"These are all working files. In most cases only "
               "FY2025 was loaded in order to help visualize the design.\" No file is "
               "the parent — the DESIGN is, and one warehouse structure serves "
               "Hillsborough and Orange County alike. The warehouse (etl/s87) builds "
               "from the pipeline's verified datasets, not from any working file's "
               "sample data; the working files' conventions live on through the "
               "Decisions_Inventory.",
        source="Amy's email 2026-07-29; docs/WAREHOUSE_DESIGN.md question 5")

    add("amy", "Chapel Hill financials",
        "When step 6 (Chapel Hill as the extensibility proof) approaches: gather their "
        "adopted budget and ACFR as DIGITAL PDFs — not scans. Two or three recent years "
        "is enough to prove the load.",
        why="She asked \"I suppose you will need me to upload the Chapel Hill "
            "financials?\" — yes, but not yet: steps 3-4 are built, step 5 (marts "
            "reading from the warehouse) comes first. Digital originals matter: the "
            "scanned Hillsborough reports cost this project the detail beneath a "
            "decade of audited statements.",
        source="her email 2026-07-29", status="open")

    # ---- from her 2026-07-29 replies and the files that arrived with them ----
    add("amy", "Warehouse — projection horizon",
        "How far forward do projections go — FY29 (the budget's) or FY35 (your v5's)?",
        status="answered",
        answer="Her rule, 2026-07-29: \"as far out as is meaningful\" — for a single capital "
               "project, analysis runs to the end of that project's debt; across projects, a "
               "long horizon means less because new needs always emerge. Adopted as the "
               "marts' rule: per-project views extend to debt maturity; portfolio views stay "
               "inside the town's own published window, and anything beyond it is labelled "
               "scenario rather than projection.",
        source="Amy's email 2026-07-29; docs/WAREHOUSE_DESIGN.md question 4")

    add("amy", "Workbook B waterfall — the plug is a formula artifact",
        "In '1 Budget Waterfall', cell C11 reads =C5+9229686-SUM(C6:C10), but C5 is an EMPTY "
        "cell and 9,229,686 is a hardcoded intermediate — so the famous −$8,628,296 plug is "
        "a formula slip, not a measured presentation gap. Against your own stated totals "
        "(B5 = $10,076,945 FY18, C12 = $19,476,631 FY27), the residual the bridge actually "
        "needs is +$1,618,649. Separately: your B5 differs by exactly $100,000 from the "
        "page-proven FY2018 audited figure — the ACFR's own p.46 column sums to $10,176,945. "
        "Worth correcting both in the workbook when convenient.",
        why="You asked for the source document and pages behind the −$8.6M difference; the "
            "honest answer is that no document carries it — the plug row is computed inside "
            "the workbook, and its formula points at an empty cell. The genuine "
            "presentation-gap residual (~$1.6M) is far smaller than the plug suggested, "
            "though the crosswalk is still needed: three of your six rows are marked 'Needs "
            "mapping' or 'Not comparable'. (An apology is owed here too: this project quoted "
            "the −$8.6M twice without checking its arithmetic.)",
        status="answered",
        answer="Fixed by Amy the same afternoon, in "
               "Hillsborough_Workbook_B_Fiscal_Sustainability_Risk_Model_v2.xlsx — verified "
               "2026-07-29: B5 now reads 10,176,945 (the page-proven figure), C11 reads "
               "=C12-SUM(C6:C10) giving +1,991,826, the residual lands at +1,518,649, and "
               "the FY27 column sums exactly to its stated total. The pipeline now reads the "
               "highest-versioned Workbook B automatically, so v2 supersedes.",
        source="measured 2026-07-29 from Hillsborough_Workbook_B_Fiscal_Sustainability_"
               "Risk_Model.xlsx, tab '1 Budget Waterfall', row 11; corroborating FY2018 "
               "figure from the FY2018 ACFR p.46 (ocr-arithmetic-verified); fix verified in "
               "her v2 the same day")

    add("amy", "Adopted FY2027 budget ordinance",
        "The archive holds the FY27 RECOMMENDED plan only, but the town's own news summary "
        "reports the board approved the FY2027 budget ordinance before July 1. Could you "
        "download the adopted ordinance (and any amended financial summary) from the town "
        "site and add it to the Drive folder?",
        status="awaiting upload",
        why="It upgrades every FY2027 figure from Scenario=Recommended to Adopted — your own "
            "extensibility test #1 — and closes the gap between what the site can honestly "
            "call 'this year's plan' and 'this year's budget'.",
        source="lead found 2026-07-29 in the town news links referenced by the rates note")

    add("pipeline", "Extract the audited detail from the digital originals",
        "Amy obtained DIGITAL editions of the town's audit reports for FY2021-FY2025 "
        "(FY2019-FY2020 pending download — the files exceed the transfer tool's size "
        "ceiling). This is the site's own best-practice ask fulfilled: the detail beneath a "
        "half-decade of audited statements, previously locked behind scans, is now readable "
        "character-for-character. Extend the stage-60 reading to every digital year: full "
        "General Fund statements, the Water & Sewer and Stormwater enterprise fund audited "
        "outturns, debt schedules, tax levy/collection tables, and fund balance components.",
        why="The footer currently tells residents this detail 'will not appear here until "
            "each page proves itself' — with digital originals the proof is direct reading. "
            "It also lets the scan-recovery method be validated wholesale: every "
            "OCR-recovered total can now be checked against a digital original.",
        source="files obtained by Amy 2026-07-29; survey in progress",
        status="answered",
        answer="DONE — etl/s61_audited_digital.py reads all five digital audits "
               "(FY2021-FY2025): 187 statement pages, 459 of 576 statement groups "
               "reconciled against their own printed totals, 2,271 verified lines. The "
               "wholesale validation this item hoped for came out clean: FY2021, FY2022 "
               "and FY2024 audited General Fund totals read from the digital originals "
               "match the figures stage 75 recovered from the SCANNED versions to the "
               "dollar, and FY2025 matches stage 60's read of the separate digital twin. "
               "Five of five cross-document checks agree, and the stage fails the build "
               "if any disagrees. FY2018-FY2020 digital audits are still not held — see "
               "the item below on the thin early years.")

    # ---- raised by the warehouse fill of 2026-07-29 ---------------------------
    # APPEND ONLY, below every add() above: register ids are positional, so inserting
    # anywhere earlier silently renumbers every later item.
    add("pipeline", "Statement column headers — 10,275 figures with no established basis",
        "Stages 61 and 81 verify a statement line by its page's own arithmetic, and prove "
        "which column is budget and which is actual from the variance identity. On "
        "statements that print no variance column — balance sheets, net position, cash "
        "flows, combining statements — the columns are FUNDS or ACTIVITY TYPES instead, so "
        "no identity confirms them. Those 10,275 lines are verified, cited to a document "
        "and page, and held in Fact_Statement_Line with the basis explicitly unknown. "
        "Resolving it means reading each statement's column HEADER band and matching header "
        "text to the figure columns by position.",
        why="It is the single highest-leverage piece of work left on the warehouse. The same "
            "header-reading unlocks two things at once: it gives these 10,275 figures a "
            "basis so they can join Fact_Financial, and it is exactly what the unread budget "
            "documents need, because their columns are fiscal years printed in a header row. "
            "Until then the figures are published and traceable but cannot be charted as "
            "'actual' or 'budget' without guessing.",
        source="measured 2026-07-29 while loading the audited statements",
        answer="Amy 2026-07-30: 'This is a fair assumption. I agree.' Still to build.")

    add("pipeline", "Budget documents for FY2025, FY2026 and the county's FY2026-27",
        "Twenty-three documents with figures are still unread, and the substantial ones are "
        "budget plans: the town's FY26 Adopted, FY26 Recommended, FY26 Ordinance and FY2025 "
        "Manager's Recommended, and the county's FY25-26 Approved, FY25-26 Manager "
        "Recommended, FY2026-27 Manager's Recommended, FY2025-26 Ordinance and FY26-27 CIP. "
        "The FY27 plan's line-item appendix — the one structure this pipeline reads deeply — "
        "does NOT exist in any of them (measured: nine occurrences of 'Line-Item Budget' in "
        "the FY27 document, zero in the other five). They present budgets as narrative plus "
        "a handful of multi-year summary tables keyed by fiscal-year column headers.",
        why="It is why Fact_Financial holds nothing for Orange County after FY2025 and why "
            "the town's FY2026 rows come only from the FY27 plan's comparative columns rather "
            "than from the FY26 budget itself. The adopted-vs-recommended distinction Amy's "
            "extensibility test #2 depends on cannot be shown for FY2026 without them.",
        source="coverage measured 2026-07-29 by etl/s104_coverage.py",
        status="answered",
        answer="DEPRIORITISED by Amy, 2026-07-30, in her own words: 'The town/county budget "
               "books - these are likely not needed, but available for reference. It is maybe "
               "just adding confusion but I grabbed them in case there is some data elements "
               "not found elsewhere… They are properly marked Not Read, with the understanding "
               "there is no Action required.' Same for the studies. So do NOT read these "
               "speculatively — go to them only when a specific figure is missing from "
               "elsewhere, and she named the likely one: the water and sewer rate history. "
               "This releases what looked like the bulk of the remaining backlog.")

    add("amy", "The town's DIGITAL audits for FY2018, FY2019 and FY2020",
        "Would you ask the town for digital editions of the annual financial reports for the "
        "years ended June 30 2018, 2019 and 2020? You obtained FY2021-FY2025 and they "
        "transformed those years — from a handful of recovered column totals to several "
        "hundred verified lines each. For FY2018-FY2020 the archive holds only scans, whose "
        "embedded text transposes digits, so figures are published solely where a page's own "
        "arithmetic proves them.",
        why="It is the clearest hole in the warehouse and it shows plainly in the coverage "
            "table: Hillsborough FY2018 holds 31 facts and FY2019 holds 28, against 983 for "
            "FY2025. This is not something more code can fix — the documents are the "
            "constraint. Three files would close a decade-long series.",
        source="coverage measured 2026-07-29; the FY2021-FY2025 digital audits proved the value")

    add("amy", "122 county figures your workbook records that the audits did not corroborate",
        "Stage 81 now reads all eight county ACFRs directly and checks every monetary figure "
        "in your county workbook against the audited statements for that same year. 672 of "
        "794 matched (85%). The remaining 122 could not be found — and this is a question, "
        "not a correction. The match is on VALUE within a fiscal year, because your category "
        "names are your own and inventing a label crosswalk would be guessing at the mapping "
        "the town has not supplied. An absence can sit on either side: the county prints the "
        "same slice in several statements, and this project withholds any statement group "
        "whose arithmetic it could not prove.",
        why="Where your figure is right and the reader missed it, that is a gap in this "
            "project's reading worth fixing. Where a figure came from a table outside the "
            "audited statements — a transmittal letter, an MD&A narrative — recording which "
            "would make it citable to a page. Either way the answer improves the warehouse.",
        source="measured 2026-07-29 by etl/s81_county_acfr.py",
        status="answered",
        answer="ANSWERED 2026-07-30, and the answer is that this was never a question for Amy. "
               "Every one of the 60 sampled unmatched figures was searched for in the raw text of "
               "that year's county ACFR: 60 of 60 are PRESENT. Her transcription is correct and "
               "this project's reader simply failed to extract those statements — almost certainly "
               "the groups whose arithmetic did not reconcile and were therefore withheld, so they "
               "never entered the comparison set at all. "
               "Two wrong explanations were offered before the measurement was taken, and both "
               "should be a warning. Mine: 'they probably came from a transmittal letter or the "
               "MD&A narrative rather than the audited statements' — plausible, and wrong. Hers: "
               "'those are my learning tabs, you can ignore them' — also wrong, because the "
               "unmatched figures come from her numbered Fact tabs (2.0/4.0/5.0/6.0), and this "
               "pipeline never imports her lesson tabs at all (FACT_SHEET only matches sheets "
               "beginning with a digit, and Reading_Order_v2.2 through Capital_Debt_FY25 do not). "
               "The real work item is therefore a READER gap on the county statements, tracked as "
               "part of the withheld-group backlog — not anything Amy needs to do.")




    # ---- resolve items the archive already answers ---------------------------
    # The first run of this register showed two of her standing questions to the town as
    # open when documents already in sources/ answer them. That is precisely what a
    # register is for, and leaving them open would send her to ask for what she has.
    # Each resolution names the document, so it can be checked rather than trusted.
    RESOLVED = [
        ("Sales Tax",
         "Answered by the town's records-request response 'Sales Tax Information.docx', "
         "which gives FY18-FY25 receipts with a PDF page cite for each, the FY26 original "
         "budget ($3,233,500) and year-end estimate ($3,408,000), and the forecast "
         "assumption in staff's own words: FY27-29 are held flat at $3,408,000 because "
         "growth has slowed over 3-4 years and the source is volatile. It also explains "
         "the collection lag — the state receives and redistributes, so May sales reach "
         "the town in July."),
        ("Debt",
         "Partly answered by the Finance Director's response 'Debt Schedules from "
         "Hillsborough FD.docx' plus 'Debt Service Projections.xlsx'. Schedules through "
         "maturity were provided. On affordability the answer was that no such analysis "
         "exists — 'No specific analysis has been done' — and that capacity to absorb new "
         "debt service is what gates a project, managed with a ramp-up strategy. Still "
         "open: a written affordability analysis does not exist to request."),
    ]
    for topic, answer in RESOLVED:
        for r in reg:
            if r["topic"] == topic and r["owner"] == "town" and r["status"] == "open":
                r["status"] = "answered"
                r["answer"] = answer
                r["resolved_by"] = "documents already in sources/"

    by_owner: dict[str, dict[str, int]] = {}
    for r in reg:
        s = by_owner.setdefault(r["owner"], {})
        s[r["status"]] = s.get(r["status"], 0) + 1

    open_items = [r for r in reg if r["status"] != "answered"]

    write_json(DATASETS / "questions.json", {
        "generated_by": "etl/s98_questions.py",
        "requested_by": ("Amy — \"Please keep a log of all your questions and follow up's and "
                         "the status of each. I need this to keep track of any open questions "
                         "that I need to address.\""),
        "how_this_works": ("Built from the datasets themselves on every run rather than "
                           "maintained by hand, so it cannot drift out of date: close a gap in "
                           "a stage and the item leaves this list. Answered items are kept with "
                           "their answer, because a question that quietly vanishes is "
                           "indistinguishable from one that was forgotten."),
        "owners": {
            "town": "Needs a records request or an answer from Town of Hillsborough staff.",
            "county": "Needs a records request or an answer from Orange County staff.",
            "amy": "A modelling or editorial decision that is hers, not extractable.",
            "david": "An account-level action only the repository owner can take.",
            "pipeline": "Work this project can do without anyone else.",
        },
        "summary": {
            "total": len(reg), "open": len(open_items),
            "answered": len(reg) - len(open_items),
            "by_owner": by_owner,
            "needs_a_government_answer": sum(1 for r in open_items
                                             if r["owner"] in ("town", "county")),
            "awaiting_upload": sum(1 for r in reg if r["status"] == "awaiting upload"),
        },
        "register": reg,
    })

    # ---- a version she can actually work from ---------------------------------
    # JSON is for the site; a register is only useful to her if she can read it, tick
    # things off and see at a glance which items are hers rather than the town's.
    OWNER_LABEL = {"town": "Ask the Town", "county": "Ask the County",
                   "amy": "Your decision", "david": "David", "pipeline": "This project"}
    md = ["# Open questions and follow-ups",
          "",
          "*Generated by `etl/s98_questions.py` on every build — do not edit by hand.*",
          "*Close a gap in a stage and the item leaves this list automatically.*",
          "",
          f"**{len(open_items)} open** · {len(reg) - len(open_items)} answered · "
          f"{len(reg)} total",
          ""]
    order = ["amy", "county", "town", "david", "pipeline"]
    for owner in order:
        items = [r for r in reg if r["owner"] == owner and r["status"] != "answered"]
        if not items:
            continue
        md += [f"## {OWNER_LABEL[owner]} ({len(items)})", ""]
        for r in items:
            flag = "" if r["status"] == "open" else f" — **{r['status']}**"
            md.append(f"- **[{r['id']}] {r['topic']}**{flag}  ")
            md.append(f"  {r['question']}")
            if r.get("why_it_matters"):
                md.append(f"  *Why it matters:* {r['why_it_matters']}")
            if r.get("answer"):
                md.append(f"  *Note:* {r['answer']}")
            if r.get("raised_by"):
                md.append(f"  <sub>Raised by: {r['raised_by']}</sub>")
            md.append("")
    answered = [r for r in reg if r["status"] == "answered"]
    if answered:
        md += ["## Answered — kept so nothing quietly disappears", ""]
        for r in answered:
            md.append(f"- **[{r['id']}] {r['topic']}** — {r['question']}  ")
            md.append(f"  **Answer:** {r.get('answer') or '(recorded as answered)'}")
            md.append("")
    out = Path(__file__).resolve().parent.parent / "docs" / "OPEN_QUESTIONS.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"  wrote {out.relative_to(out.parent.parent)}")

    print(f"  {len(reg)} items — {len(open_items)} open, {len(reg) - len(open_items)} answered")
    for owner, counts in sorted(by_owner.items(), key=lambda x: -sum(x[1].values())):
        detail = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
        print(f"      {owner:9} {sum(counts.values()):3}  ({detail})")
    print(f"\n  open items she has to action:")
    for r in open_items:
        if r["owner"] in ("town", "county", "amy"):
            print(f"      [{r['id']}] {r['owner']:7} {r['status']:16} {r['topic'][:34]:36} "
                  f"{(r['question'] or '')[:60]}")


if __name__ == "__main__":
    main()
