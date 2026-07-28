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
        answer="Amy states she has uploaded OC Sales Tax information. Not yet present in "
               "sources/ — needs a fresh Drive export.")

    add("town", "Utility rate history",
        "Water and sewer rate schedules for years before FY2026.",
        why="The FY2026 and FY2027 structures are exact, so a bill can be computed at any "
            "consumption, but the series cannot be trended backwards without the older "
            "schedules. The rate studies held are slide decks without the underlying tables.",
        source="gap reported by etl/s93_utility_rates.py",
        status="awaiting upload",
        answer="Amy states she has uploaded Water and Sewer historical rates. Not yet "
               "present in sources/ — needs a fresh Drive export.")

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
            why="Your project scope defines two Governments with nine domains each, so the "
                "structure is known. Which level the county-funded bodies belong to is a "
                "modelling choice rather than something a document can settle.",
            source="etl/s97_context.py")

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

    add("david", "Repository name",
        "Rename the GitHub repository from `hoa-funds` to `mfas`. Only the account owner can "
        "do it: Settings -> General -> Repository name. GitHub redirects the old URLs.",
        why="The project is MFAS; \"hoa\" reads like a homeowners association and was the name "
            "of the empty repository this was first pushed into.",
        source="Amy 2026-07-27; instructions in README")

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
