"""Stage 97 — two documents that explain things the numbers alone cannot.

Both arrived on 2026-07-27, and neither is a table.

**1. `MFAS/OC & Hillsborough Fiscal Analysis Project.docx`** sets out which government
provides which services. That matters to a resident more than it looks: this site can
already show that Orange County's tax rate (67.58 cents) is larger than the town's
(51.30), but not *why*. The answer is that the county carries schools, the sheriff,
social services, public health, libraries, EMS and economic development, while the town
carries police, fire, streets, water and sewer, planning, parks and the Riverwalk.

It is also the **Organization vs Government split** stage 88 reports as unresolved. The
document names two governments with the same nine domains each, which is exactly the two
levels MFAS distinguishes and this project currently conflates.

**2. `Debt Schedules from Hillsborough FD.docx`** is a records-request response from the
town's Finance Director, and it is a primary source explaining a mechanism that the
budget figures show without explaining: the **ramp-up strategy**. The town sets aside a
rising amount for several years before a debt payment begins, so the money is already in
the base budget when it starts. That is why the budget carries $300,000 a year for a fire
station whose eventual debt service is around $670,000 — and why the declined "ramp-up
expansion" request matters more than its size suggests.

The same response also states, in the Finance Director's own words, that **no debt
affordability or debt management analysis has been prepared**. For an accountability
project that is a finding in itself, and it is recorded as a direct quotation rather than
paraphrased.

Nothing here is a number, so nothing here is reconciled. What is checked instead is that
every quotation actually appears in the document it is attributed to — a claim about what
a public official said is at least as damaging to get wrong as a figure.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, SOURCES, write_json  # noqa: E402

PROJECT_DOC = "Orange County Efficiency & Accountability Initiative/MFAS/OC & Hillsborough Fiscal Analysis Project.docx"
FD_DOC = ("Orange County Efficiency & Accountability Initiative/"
          "06 Budget & Financial Analysis - Hillsborough/Debt Schedules from Hillsborough FD.docx")


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    txt = re.sub(r"<w:p[ >]", "\n<w:p ", xml)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = txt.replace("&amp;", "&").replace("&#8217;", "’").replace("&quot;", '"')
    return re.sub(r"\n{2,}", "\n", txt).strip()


def bullets_after(text: str, heading: str, stop_at: tuple[str, ...]) -> list[str]:
    """The service lists are plain paragraphs under a heading, not a table."""
    i = text.find(heading)
    if i < 0:
        return []
    out = []
    for line in text[i + len(heading):].split("\n"):
        s = line.strip()
        if not s:
            continue
        if any(s.startswith(x) for x in stop_at):
            break
        # Sentences are prose, not list items.
        if len(s) > 60 or s.endswith((".", ":", "?")):
            continue
        out.append(s)
    return out


def main() -> None:
    ppath, fpath = SOURCES / PROJECT_DOC, SOURCES / FD_DOC
    problems: list[str] = []
    for p in (ppath, fpath):
        if not p.exists():
            sys.exit(f"missing {p}")

    ptext = docx_text(ppath)
    ftext = docx_text(fpath)

    county = bullets_after(ptext, "including:", ("Town of Hillsborough",))
    town = bullets_after(ptext, "The Town provides:", ("Together,", "What makes"))

    questions = []
    qi = ptext.find("We're trying to answer questions like:")
    if qi >= 0:
        for line in ptext[qi:].split("\n")[1:]:
            s = line.strip()
            if not s or s.startswith("No single budget"):
                break
            if s.endswith("?"):
                questions.append(s)

    # Quotations from the Finance Director. Each is verified to appear verbatim in the
    # document below — a misquotation of a named public official is worse than a bad
    # number, because it cannot be corrected by re-reading a table.
    QUOTES = [
        ("ramp_up_strategy",
         "We often use a “ramp-up” strategy to build capacity over multiple years.",
         "Why the budget sets aside money years before a debt payment starts."),
        ("no_affordability_analysis",
         "No specific analysis has been done",
         "Asked for any debt affordability or debt management analyses prepared by staff."),
        ("capacity_is_the_gate",
         "the town’s ability to absorb any new debt service is a key factor in "
         "determining if and when a project may move forward",
         "What actually decides whether a capital project proceeds."),
    ]
    quotes = []
    for key, quote, why in QUOTES:
        present = quote in ftext
        if not present:
            problems.append(f"quotation not found verbatim in the source document: {quote[:60]}")
            continue
        quotes.append({"id": key, "quote": quote, "why_it_matters": why,
                       "speaker": "Town of Hillsborough Finance Director",
                       "context": "Written response to a public records request",
                       "source_doc": "debt-schedules-from-hillsborough-fd",
                       "verified_verbatim": True})

    # The worked example the Finance Director gives, in his own numbers.
    ramp = None
    m = re.search(r"if debt service is anticipated to be \$([\d,]+).*?yr-1 - \$([\d,]+),"
                  r"\s*yr-2 - \$([\d,]+),\s*yr-3 - \$([\d,]+)", ftext, re.S)
    if m:
        target = float(m.group(1).replace(",", ""))
        steps = [float(m.group(i).replace(",", "")) for i in (2, 3, 4)]
        ramp = {"target_annual_debt_service": target, "ramp_by_year": steps,
                "reaches_target_in_years": len(steps),
                "arithmetic_consistent": abs(steps[-1] - target) < 1.0,
                "note": ("The Finance Director's own illustration. The ramp-up money goes "
                         "into the project itself, reducing what must be borrowed, and "
                         "reserves budget capacity so it is not absorbed elsewhere.")}
        if not ramp["arithmetic_consistent"]:
            problems.append("the ramp-up example's final year does not equal its target")

    write_json(DATASETS / "context.json", {
        "generated_by": "etl/s97_context.py",
        "arrived": "2026-07-27",
        "why_this_exists": ("Neither document is a table. One explains which government "
                            "provides which services, which is why the county's tax rate is the "
                            "larger of the two. The other is the town Finance Director's written "
                            "answer to a records request, explaining a mechanism the budget "
                            "figures show without explaining."),
        "verification": ("Nothing here is a number, so nothing is reconciled. Instead every "
                         "quotation is checked to appear verbatim in the document it is "
                         "attributed to — a claim about what a named public official said is at "
                         "least as damaging to get wrong as a figure."),
        "who_provides_what": {
            "source_doc": "oc-hillsborough-fiscal-analysis-project",
            "note": ("From the initiative's own project scope. Together these are, in its "
                     "words, “the complete local tax burden for a Hillsborough "
                     "resident”."),
            "Orange County": county,
            "Town of Hillsborough": town,
        },
        "questions_the_project_exists_to_answer": questions,
        "why_two_governments_matter": ("Most residents only ever see one budget at a time, and "
                                      "no single budget document answers these questions because "
                                      "they span two governments."),
        "finance_director_on_debt": {
            "quotes": quotes,
            "ramp_up_example": ramp,
            "relevance": ("This is the mechanism behind the fire station: the budget carries "
                          "$300,000 a year against an eventual debt service near $670,000. It is "
                          "also why the declined 'ramp-up expansion' request matters more than "
                          "its size suggests — a ramp-up that starts late means either "
                          "borrowing more or finding the money elsewhere later."),
        },
        "organization_vs_government": {
            "relevance_to_mfas": ("Stage 88 reports Organization as conflated with Government. "
                                  "This document resolves what the two levels are: two "
                                  "Governments, each with the same nine domains — operating "
                                  "budget, capital budget, debt, staffing, utilities or schools, "
                                  "affordable housing, revenues, reserves, historical trends."),
            "still_needed": ("A decision on whether sub-entities the county funds — the school "
                             "district, the sheriff's office, EMS — are Organizations under the "
                             "county Government or Governments in their own right. That is a "
                             "modelling choice, not a fact to extract."),
        },
        "problems": problems,
    })

    print(f"  who provides what: {len(county)} county services, {len(town)} town services")
    print(f"      County: {', '.join(county[:5])}…")
    print(f"      Town:   {', '.join(town[:5])}…")
    print(f"  {len(questions)} questions the project exists to answer")
    print(f"  {len(quotes)} Finance Director quotations, all verified verbatim")
    for q in quotes:
        print(f"      [{q['id']}] {q['quote'][:78]}")
    if ramp:
        print(f"  ramp-up example: {ramp['ramp_by_year']} -> "
              f"${ramp['target_annual_debt_service']:,.0f} "
              f"(consistent: {ramp['arithmetic_consistent']})")
    if problems:
        print(f"\n  {len(problems)} problem(s):")
        for p in problems:
            print(f"      {p}")


if __name__ == "__main__":
    main()
