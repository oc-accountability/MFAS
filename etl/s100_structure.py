"""Stage 100 — the structural question, posed with evidence and deliberately unanswered.

Amy's message, which is the clearest statement of the project's purpose so far:

    "I read everywhere people are stressed and upset about property tax increases. And
     the villages and towns answer they look under every rock. From my standpoint, as a
     taxpayer, I end up reading 2 budgets, and 2 tax calculations, to figure out why my
     taxes are going up and what the decisions have been to get there. what am I getting
     for this tax? I wonder why this government is structured this way. This results in a
     lot of extra work, confusion, duplication, etc. and added cost. Why we need OC County
     and Hillsborough administration?

     I want this to highlight this insight."

And the constraint she put on it in the same breath:

    "But I don't want my opinion or me to tell anybody what is right or wrong."

Those two together are a precise and demanding brief: **make the question visible and
measurable, and refuse to answer it.** So this stage assembles only what the documents
support, in three parts, and then states plainly what they cannot settle.

**What it measures**

  1. *The reading burden.* Not an impression — a count. How many documents and pages a
     resident must open, across how many governments, to answer "why is my bill going up".

  2. *What is already shared.* This is where an assumption would have gone wrong. Tax
     billing and collection are **not** duplicated: Orange County bills and collects for
     all three municipalities, and the town's own justification form states the fee is
     0.5% of collected taxes while the county's fee study puts the peer average at 1.5%.
     So on this service the town currently pays a third of what its peers do. Anyone
     building a duplication argument needs to know that, including Amy.

  3. *What each government runs separately.* The town's own administrative departments,
     from its line-item appendix, as a share of its General Fund.

**What it refuses to do.** No document in the archive compares the cost of two
administrations against any alternative. There is no published figure for what
consolidation would save or cost, no service-level comparison, and no measure of what
duplication is real versus apparent. So this stage publishes no such number, offers no
estimate, and draws no conclusion. It presents the question as a question — which is
exactly what she asked for and the opposite of what a persuasive site would do.

The county side of part 3 is missing: county administrative spending is not yet extracted
at the same grain, so the comparison a reader would most want cannot be drawn honestly
yet. That absence is stated rather than filled with the town's figure alone.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, read_json, write_json  # noqa: E402

# Departments that exist to run the organisation rather than deliver a service to a
# resident. Drawn from the town's own department names, and deliberately narrow: Streets,
# Police, Fire, Planning and the rest are services, not administration.
ADMIN_DEPARTMENTS = {
    "Accounting", "Administration", "Communications", "Governing Body",
    "Human Resources", "Information Technology", "Safety & Risk Management",
    "Facility Management",
}
# Facility Management and Communications are arguable either way, so the output reports
# the total both with and without them rather than picking one and calling it the answer.
ARGUABLE = {"Facility Management", "Communications"}


def main() -> None:
    docs = read_json(DATASETS / "documents.json")["documents"]
    li = read_json(DATASETS / "lineitems.json")
    facts = read_json(DATASETS / "facts.json")["facts"]
    ctx = read_json(DATASETS / "context.json")
    trade = read_json(DATASETS / "tradeoffs.json")

    def fv(metric, fy=None):
        r = [f for f in facts if f["metric"] == metric
             and (fy is None or f["fiscal_year"] == fy)]
        return r[-1]["value"] if r else None

    # ---- 1. the reading burden, counted rather than asserted ------------------
    cur = [d for d in docs
           if (d.get("fiscal_year") in (2027, "2027", "FY27") or "FY27" in d["filename"]
               or "2026-27" in d["filename"] or "FY2026-27" in d["filename"])
           and d.get("format") == "pdf"]
    by_gov: dict[str, dict] = {}
    for d in cur:
        j = d.get("jurisdiction") or "unstated"
        s = by_gov.setdefault(j, {"documents": 0, "pages": 0, "examples": []})
        s["documents"] += 1
        s["pages"] += d.get("pages") or 0
        if len(s["examples"]) < 3:
            s["examples"].append({"filename": d["filename"], "pages": d.get("pages")})
    all_pdf = [d for d in docs if d.get("format") == "pdf"]
    burden = {
        "governments_a_resident_must_read": len([k for k in by_gov if k != "unstated"]),
        "tax_calculations_to_combine": 2,
        "current_cycle_documents": len(cur),
        "current_cycle_pages": sum(d.get("pages") or 0 for d in cur),
        "by_government": by_gov,
        "whole_archive_documents": len(all_pdf),
        "whole_archive_pages": sum(d.get("pages") or 0 for d in all_pdf),
        "pages_counted_for": sum(1 for d in all_pdf if d.get("pages")),
        "note": ("Page counts are only available for documents this pipeline could open and "
                 "measure, so these are floors rather than totals."),
    }

    # ---- 2. what is already shared, which an assumption would have got wrong --
    fee_form = next((f for f in trade.get("justification_forms", [])
                     if "Tax Collection" in (f.get("request") or "")), None)
    declined = next((r for r in trade.get("declined", [])
                     if "Tax Collection" in (r.get("request") or "")), None)
    shared = None
    if fee_form:
        shared = {
            "service": "Property tax billing and collection",
            "arrangement": fee_form.get("description"),
            "provided_by": "Orange County",
            "provided_for": ["Chapel Hill", "Carrboro", "Hillsborough"],
            "current_fee_pct_of_collections": 0.5,
            "county_fee_study_peer_average_pct": 1.5,
            "source_page": fee_form.get("source_page"),
            "why_this_matters_to_the_question": (
                "This service is NOT duplicated — one government does it for all three "
                "municipalities, and at a third of what the county's own fee study says peers "
                "charge. Any argument about duplicated cost has to account for the services "
                "that are already consolidated, and for the fact that this one is currently "
                "cheap for the town."),
        }
        if declined:
            shared["proposed_increase_declined"] = {
                "fy2027": declined.get("fy2027"),
                "three_year": declined.get("total_three_year"),
                "status": "not funded in the recommended budget",
            }
    # The town also carries its own tax collection line, which is the fee it pays.
    C = {c: i for i, c in enumerate(li["columns"])}
    tax_coll = [{"fiscal_year": r[C["fiscal_year"]], "basis": r[C["basis"]],
                 "amount": r[C["value"]], "department": r[C["department"]],
                 "source_page": r[C["page"]]}
                for r in li["rows"] if r[C["account"]].strip().upper() == "TAX COLLECTION"]
    if shared and tax_coll:
        shared["what_the_town_records_paying"] = sorted(
            tax_coll, key=lambda x: (x["fiscal_year"], x["basis"]))

    # ---- 3. what each government runs separately -----------------------------
    dept: dict[str, float] = {}
    for r in li["rows"]:
        if (r[C["fiscal_year"]] == 2027 and r[C["basis"]] == "budget"
                and r[C["fund"]] == "General Fund"):
            dept[r[C["department"]]] = dept.get(r[C["department"]], 0.0) + r[C["value"]]
    gf = sum(dept.values())
    admin_all = {d: v for d, v in dept.items() if d in ADMIN_DEPARTMENTS}
    admin_core = {d: v for d, v in admin_all.items() if d not in ARGUABLE}
    separate = {
        "government": "Town of Hillsborough",
        "fiscal_year": 2027, "basis": "budget", "fund": "General Fund",
        "general_fund_total": round(gf, 2),
        "administration_broad": {
            "departments": {k: round(v, 2) for k, v in sorted(admin_all.items(),
                                                             key=lambda x: -x[1])},
            "total": round(sum(admin_all.values()), 2),
            "share_of_general_fund_pct": round(sum(admin_all.values()) / gf * 100, 1),
        },
        "administration_narrow": {
            "excludes": sorted(ARGUABLE),
            "total": round(sum(admin_core.values()), 2),
            "share_of_general_fund_pct": round(sum(admin_core.values()) / gf * 100, 1),
        },
        "why_two_figures": ("Facility Management and Communications can reasonably be counted "
                            "as administration or as services, so both totals are given rather "
                            "than one being presented as the answer."),
        "county_equivalent": None,
        "county_note": ("Orange County's administrative spending is not yet extracted at this "
                        "grain, so the comparison a reader would most want cannot be drawn "
                        "honestly. Publishing the town's figure alone would invite a comparison "
                        "against nothing."),
    }

    write_json(DATASETS / "structure.json", {
        "generated_by": "etl/s100_structure.py",
        "requested_by": ("Amy — \"I end up reading 2 budgets, and 2 tax calculations, to figure "
                         "out why my taxes are going up... I wonder why this government is "
                         "structured this way... I want this to highlight this insight.\""),
        "constraint": ("Her own, in the same message: \"But I don't want my opinion or me to "
                       "tell anybody what is right or wrong.\" So this poses the question with "
                       "measurements and refuses to answer it."),
        "the_question": ("Why does answering \"why is my property tax going up?\" require reading "
                         "two budgets and combining two tax calculations, and what does running "
                         "two administrations cost?"),
        "reading_burden": burden,
        "already_shared": shared,
        "run_separately": separate,
        "who_provides_what": (ctx.get("who_provides_what") or {}),
        "combined_rate_cents": {
            "town": fv("property_tax_rate"),
            "county": fv("county_property_tax_rate"),
            "note": "Two rates, two governing bodies, one bill to the resident.",
        },
        "what_the_documents_cannot_answer": [
            "Whether two administrations cost more in total than one would. No document in the "
            "archive compares the two structures, so no figure is published for it.",
            "What consolidation or shared services would save, or cost. There is no published "
            "estimate, and producing one here would be an opinion wearing a number's clothes.",
            "Which duplication is real and which is apparent. Two governments each having a "
            "finance function is not by itself duplication — they administer different taxes, "
            "funds and statutory duties.",
            "Whether the current structure delivers better or worse services than an "
            "alternative. Nothing in the archive measures service quality at all.",
        ],
        "how_to_answer_it": [
            "County administrative spending at the same department grain as the town's, which "
            "would make the only comparison the documents could support.",
            "A shared-services inventory: which functions each government already buys from the "
            "other, and at what price. Tax collection is one; there may be more.",
            "North Carolina statutory duties by level of government, which would separate "
            "duplication a locality could remove from duplication state law requires.",
        ],
        "editorial_stance": ("Nothing here argues a position. The reading burden is counted, the "
                            "shared service is described from the town's own form including the "
                            "fact that it is currently cheap for the town, the administrative "
                            "share is given two ways because the boundary is arguable, and the "
                            "question is left with the reader."),
    })

    print(f"  reading burden: {burden['current_cycle_documents']} current-cycle documents, "
          f"{burden['current_cycle_pages']:,} pages, "
          f"{burden['governments_a_resident_must_read']} governments")
    for g, s in sorted(by_gov.items(), key=lambda x: -x[1]["pages"]):
        print(f"      {g[:26]:28} {s['documents']:2} docs  {s['pages']:>5,} pages")
    print(f"  whole archive: {burden['whole_archive_documents']} PDFs, "
          f"{burden['whole_archive_pages']:,} pages measured across "
          f"{burden['pages_counted_for']}")
    if shared:
        print(f"\n  already shared: {shared['service']} — county charges "
              f"{shared['current_fee_pct_of_collections']}% vs a "
              f"{shared['county_fee_study_peer_average_pct']}% peer average")
        if shared.get("proposed_increase_declined"):
            p = shared["proposed_increase_declined"]
            print(f"      proposed increase declined: ${p['fy2027']:,.0f} FY27 "
                  f"(${p['three_year']:,.0f} over three years)")
    a, n = separate["administration_broad"], separate["administration_narrow"]
    print(f"\n  town administration FY2027: ${a['total']:,.0f} "
          f"({a['share_of_general_fund_pct']}% of the General Fund), or "
          f"${n['total']:,.0f} ({n['share_of_general_fund_pct']}%) excluding "
          f"{', '.join(n['excludes'])}")
    print(f"  county equivalent: not extracted — comparison withheld")


if __name__ == "__main__":
    main()
