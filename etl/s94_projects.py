"""Stage 94 — Project as a real dimension, which Amy asked for by name.

Her decision:

    "I do want Project to be a real dimension."

Stage 88 reported Project as the one dimension of her seven that this data could not
fill. Capital projects existed as named facts, but nothing a spending row could point
at, so a decision's cost could not be gathered back together. Her own worked example
is the reason it matters: Fire Station #3's cost lands across several accounts and
several years, and without a Project dimension there is no way to show a resident
what one decision actually cost.

The town publishes the register needed to fix it. Every capital project gets its own
pages in the budget document, carrying:

  * the project name, its fund, its department and its priority rank
  * a description, a justification and highlights, in the town's own words
  * **expenditures by object code by year**, FY27 through FY33
  * **funding by source by year** — operating revenue, transfers, debt to be issued
  * **operating budget impact** — the recurring cost the project creates afterwards

That last one is the interesting one for her architecture. A capital project is a
one-time expenditure that manufactures a recurring obligation, which is precisely the
Change Event with a long tail that her model describes. Most projects state it in prose
("No FY27-29 operating impact"), but eleven quantify it in a table by year — so the
recurring cost is captured rather than inferred.

Care is needed with those tables: they mix obligations that genuinely recur — debt
service, and the maintenance and utilities a new asset needs — with further one-time
capital spending and transfers to capital funds. Those are reported separately rather
than summed, because either mistake misleads: counting follow-on capital as recurring
overstates the tail, and counting only debt service understates it.

**Every project is checked against its own printed totals before publication.** Each
table prints an AMOUNT row, and the object-code rows above it must sum to it for every
year column. A project whose columns do not reconcile is reported, not published —
same rule as the rest of this pipeline. The check is per year rather than per project
so a single bad column cannot hide inside a correct grand total.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, write_json  # noqa: E402

TEXTCACHE = Path(__file__).resolve().parent.parent / "build" / "textcache"
DOC_ID = "fy27-budget-and-financial-plan-recommended"
SOURCE_DOC = "FY27 Budget and Financial Plan Recommended.pdf"

HEADER = re.compile(r"Capital Improvement Project\s*\(FY(\d{2})\s*-\s*FY(\d{2})\)", re.I)
MONEY = re.compile(r"\$\s*\(?-?([\d,]+)\)?")
# The tables print a "Current Project Budget Amount" column, then one column per
# fiscal year. The continuation table repeats the object codes for the final year.
YEAR_HDR = re.compile(r"Current Project Budget\s+((?:FY\d{2}\s*)+)", re.I)
YEAR_ONLY = re.compile(r"Itemization Description\s+((?:FY\d{2}\s*)+)|"
                       r"Object Code Description\s+((?:FY\d{2}\s*)+)", re.I)
TOTAL_ROW = re.compile(r"^\s*AMOUNT\s*(\$|$)", re.I)
SECTION = re.compile(r"^(Project Expenditures|Project Funding|Operating Budget Impact|"
                     r"Project Description|Project\s?Justification|Project Highlights)\s*$", re.I)


def load_pages() -> list[str]:
    cache = TEXTCACHE / f"{DOC_ID}-7776223-1778845438.json"
    if not cache.exists():
        matches = sorted(TEXTCACHE.glob(f"{DOC_ID}*.json"))
        if not matches:
            sys.exit(f"no cached text for {DOC_ID}; run etl/s30_budget_messages.py first")
        cache = matches[0]
    raw = json.loads(cache.read_text(encoding="utf-8"))
    pages = raw["pages"] if isinstance(raw, dict) and "pages" in raw else raw
    return [p if isinstance(p, str) else (p.get("text") or "") for p in pages]


# A capital project's stated budget impact mixes obligations that recur for years with
# further one-time spending. Maintenance and utilities on a new building recur exactly
# as debt service does — treating only debt service as recurring understated the tail a
# project leaves behind.
RECURRING_KINDS = {"debt service", "maintenance and utilities"}


def impact_kind(account: str) -> str:
    a = account.upper()
    if "DEBT SERVICE" in a:
        return "debt service"
    if any(k in a for k in ("MAINTENANCE", "UTILITIES", "INSURANCE", "SALARIES", "OPERATING")):
        return "maintenance and utilities"
    if "TRANSFER" in a:
        return "transfer to a capital fund"
    return "further capital spending"


# The town's own documents print this where a pivot table had no label. The money is
# real — for its largest project it is $11.9M — but the source is not named, so it is
# reported as unnamed rather than shown to a resident as if "Empty Values" were a
# funding source.
UNNAMED = re.compile(r"^\s*empty\s+values?\s*$", re.I)


def money_row(line: str) -> tuple[str, list[float]] | None:
    """Split a table row into its label and its figures.

    Parenthesised figures are negative; the town uses them for reductions.
    """
    vals, neg = [], []
    for m in MONEY.finditer(line):
        v = float(m.group(1).replace(",", ""))
        if m.group(0).lstrip("$ ").startswith("("):
            v = -v
        vals.append(v)
        neg.append(m.start())
    if not vals:
        return None
    label = line[:neg[0]].strip() if neg else line.strip()
    return label, vals


def parse_table(lines: list[str], start: int, stop: re.Pattern | None = None) -> tuple[dict, int]:
    """Read one expenditure or funding table into one row per account.

    `stop` is the section-boundary pattern; it defaults to the capital-project sections
    but is overridable so the budget justification forms (stage 95) can reuse this
    parser with their own headings instead of duplicating it.

    These tables are printed in TWO segments: the first covers the current project
    budget and FY27-FY32, then a continuation repeats every account for FY33. Treating
    the continuation as extra rows makes each account appear twice with mismatched
    column counts, and column 0 then sums figures from both segments — which is what
    made nine projects look as though the town's own arithmetic was wrong.

    So values are accumulated per account name in segment order, giving one row whose
    columns line up with the concatenated AMOUNT row.
    """
    stop = stop or SECTION
    acc: dict[str, list[float]] = {}
    order: list[str] = []
    totals: list[float] = []
    prev_text: str | None = None       # a label that wrapped above its own figures
    i = start
    while i < len(lines):
        ln = lines[i]
        if stop.match(ln.strip()):
            break
        parsed = money_row(ln)
        if not parsed:
            s = ln.strip()
            # Must track the MOST RECENT text line, not the first. Keeping the first
            # left the column header sitting in prev_text, so the wrapped label right
            # below it resolved to "Itemization Description Current Project Budget…",
            # which the header guard then discarded — silently losing that row.
            # "Amount" is excluded because it is the header's second line, and adopting
            # it as a label would make a real row look like the AMOUNT total.
            if (s and not re.fullmatch(r"\d{1,4}", s)
                    and not re.fullmatch(r"Amount", s, re.I)
                    and not re.match(r"(Object Code|Itemization|Line Item) Description", s, re.I)):
                prev_text = s
            i += 1
            continue

        label, vals = parsed
        if not label and prev_text:
            # Long account names WRAP AROUND their figures, so the page reads
            #     TRANSFER FROM WATER AND SEWER
            #     $195,000 $0 ...
            #     FUND
            # A values-only line therefore belongs to the text above it, and the
            # remainder of the name follows below. Dropping such rows silently lost
            # a $195,000 funding source and made the column fail to reconcile.
            label = prev_text
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if (nxt and not money_row(nxt) and not stop.match(nxt)
                    and len(nxt) <= 40 and not re.fullmatch(r"\d{1,4}", nxt)):
                label = f"{label} {nxt}"
                i += 1
        prev_text = None

        if TOTAL_ROW.match(ln.strip()) or label.upper().startswith("AMOUNT"):
            totals += vals
        elif label and not label.lower().startswith(("object code", "itemization", "line item")):
            if label not in acc:
                acc[label] = []
                order.append(label)
            acc[label] += vals
        i += 1
    return {"rows": [(k, acc[k]) for k in order], "totals": totals or None}, i


def main() -> None:
    pages = load_pages()
    projects = []
    problems: list[str] = []

    for pno, text in enumerate(pages, 1):
        h = HEADER.search(text)
        if not h:
            continue
        lines = [l.rstrip() for l in text.split("\n")]
        # The project name is the line above the "Capital Improvement Project" banner.
        hdr_i = next((i for i, l in enumerate(lines) if HEADER.search(l)), None)
        if hdr_i is None or hdr_i == 0:
            problems.append(f"p{pno}: found the project banner but no name above it")
            continue
        # A project page opens with its title, then the banner. Long titles WRAP, so
        # taking only the line directly above the banner truncates them — "Elizabeth
        # Brady Pump Station and Force Main Upgrade" became just "Upgrade".
        title_lines = [l.strip() for l in lines[:hdr_i]
                       if l.strip() and not re.fullmatch(r"\d{1,4}", l.strip())]
        name = " ".join(title_lines)
        if not name or MONEY.search(name):
            problems.append(f"p{pno}: implausible project name {name!r}")
            continue
        if len(title_lines) > 3:
            problems.append(f"p{pno}: {len(title_lines)} lines above the banner — the title may "
                            f"have absorbed other text: {name!r}")

        # Fund / Department / Priority Rank sit on the line after their own header.
        fund = dept = rank = None
        for i, l in enumerate(lines[hdr_i:hdr_i + 6], hdr_i):
            if re.search(r"Fund\s+Department\s+Priority", l, re.I) and i + 1 < len(lines):
                v = lines[i + 1].strip()
                # Most rows read "<name> Fund   <Department>   <rank>", but one project
                # names its fund by number instead — "69 - Water and Sewer Capital
                # Improvements" — which has no "Fund" to anchor on, so department and
                # rank were lost and the fund label came out as the whole line.
                m = (re.match(r"(.+?Fund)\s+(.+?)\s+(\d+)\s*$", v)
                     or re.match(r"(\d{2,3}\s*-\s*.+?(?:Improvements?|Fund))\s+(.+?)\s+(\d+)\s*$", v))
                if m:
                    fund, dept, rank = m.group(1).strip(), m.group(2).strip(), int(m.group(3))
                else:
                    fund = v or None
                    problems.append(f"p{pno}: could not split fund/department/rank from {v!r}")
                break

        prose = {}
        for key, label in (("description", "Project Description"),
                           ("justification", r"Project\s?Justification"),
                           ("highlights", "Project Highlights")):
            m = re.search(rf"^{label}\s*$", text, re.M | re.I)
            if m:
                rest = text[m.end():].split("\n")
                body = []
                for l in rest:
                    if not l.strip():
                        continue
                    if SECTION.match(l.strip()):
                        break
                    body.append(l.strip())
                if body:
                    prose[key] = " ".join(body)

        # Expenditures and funding, each possibly continuing onto the next page.
        window = lines[:]
        extra_pages = []
        for nxt in range(pno + 1, min(pno + 3, len(pages) + 1)):
            nxt_text = pages[nxt - 1]
            if HEADER.search(nxt_text):
                break                      # the next project has started
            window += [l.rstrip() for l in nxt_text.split("\n")]
            extra_pages.append(nxt)
            if "Operating Budget Impact" in nxt_text:
                break

        tables = {}
        for key, label in (("expenditures", "Project Expenditures"),
                           ("funding", "Project Funding")):
            idx = next((i for i, l in enumerate(window)
                        if re.match(rf"^{label}\s*$", l.strip(), re.I)), None)
            if idx is not None:
                tables[key], _ = parse_table(window, idx + 1)

        # Operating Budget Impact is a short prose statement and the last section of a
        # project. Reading it with a lookahead regex ran straight past it and swallowed
        # the following tables, which also defeated the "no operating impact" test and
        # flagged projects as creating recurring cost when they say the opposite. So it
        # is read line by line with explicit stop conditions instead.
        impact = None
        impact_table = None
        oi = next((i for i, l in enumerate(window)
                   if re.fullmatch(r"Operating Budget Impact", l.strip(), re.I)), None)
        if oi is not None:
            # Two forms. Most projects state it in prose ("No FY27-29 operating impact.")
            # but eleven QUANTIFY it in a table of object codes by year — which is the
            # more useful form, since it puts a number on the recurring cost a one-time
            # decision creates. Treating every case as prose reduced those to the table
            # caption, which is just the project name repeated.
            hdr = next((j for j in range(oi + 1, min(oi + 8, len(window)))
                        if re.match(r"(Object Code|Itemization|Line Item) Description",
                                    window[j].strip(), re.I)), None)
            if hdr is not None:
                tb, _ = parse_table(window, hdr + 1)
                if tb.get("rows"):
                    # Not all of this is recurring, and calling it so would overstate.
                    # The town's Operating Budget Impact section mixes three things:
                    # debt service (which genuinely recurs for the life of the loan),
                    # follow-on capital, and transfers to capital funds (both further
                    # one-time spending inside the three-year window). Amy's
                    # recurring-vs-one-time dimension needs them separated, not summed.
                    kinds = {}
                    for a, v in tb["rows"]:
                        kinds[impact_kind(a)] = round(
                            kinds.get(impact_kind(a), 0.0) + sum(v), 2)
                    impact_table = {
                        "rows": [{"account": a, "amounts": v, "kind": impact_kind(a),
                                  "recurring": impact_kind(a) in RECURRING_KINDS}
                                 for a, v in tb["rows"]],
                        "printed_total": tb.get("totals"),
                        "total": round(sum(tb["totals"]), 2) if tb.get("totals") else None,
                        "by_kind": kinds,
                        "recurring_portion": round(
                            sum(v for k, v in kinds.items() if k in RECURRING_KINDS), 2),
                        "note": ("The town states this as the project's FY2027-29 budget impact. "
                                 "Debt service, maintenance and utilities are recurring "
                                 "obligations the project creates; further capital spending and "
                                 "transfers to capital funds are one-time items inside the "
                                 "window. They are reported separately rather than summed."),
                    }
            if impact_table is None:
                body = []
                for l in window[oi + 1:]:
                    s = l.strip()
                    if not s:
                        continue
                    if (re.fullmatch(r"\d{1,4}", s) or SECTION.match(s) or HEADER.search(s)
                            or re.match(r"(Object Code|Itemization|Line Item) Description", s, re.I)
                            or re.fullmatch(r"Amount", s, re.I)):
                        break
                    body.append(s)
                    if len(body) >= 6:
                        break
                if body:
                    impact = " ".join(body)[:600]

        # --- the reconciliation gate: object rows must sum to the printed AMOUNT --
        checks = []
        publishable = True
        for key, tb in tables.items():
            if not tb.get("totals") or not tb.get("rows"):
                checks.append({"table": key, "status": "no total row printed",
                               "reconciles": False})
                publishable = False
                continue
            ncol = min(len(tb["totals"]), min(len(v) for _, v in tb["rows"]))
            for c in range(ncol):
                summed = round(sum(v[c] for _, v in tb["rows"]), 2)
                printed = round(tb["totals"][c], 2)
                ok = abs(summed - printed) < 1.0
                checks.append({"table": key, "column": c, "summed": summed,
                               "printed_total": printed, "reconciles": ok})
                if not ok:
                    publishable = False

        total_cost = None
        if tables.get("expenditures", {}).get("totals"):
            total_cost = round(sum(tables["expenditures"]["totals"]), 2)

        rec = {
            "project_id": re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"),
            "project_name": name,
            "fund": fund, "department": dept, "priority_rank": rank,
            "plan_window": f"FY20{h.group(1)}-FY20{h.group(2)}",
            "source_doc": DOC_ID, "source_pages": [pno] + extra_pages,
            **prose,
            "operating_budget_impact": impact,
            "operating_budget_impact_quantified": impact_table,
            # Reserved for a genuine ongoing obligation — debt service — rather than any
            # non-zero budget impact, which would count follow-on capital as recurring.
            "creates_recurring_cost": bool(
                impact_table and (impact_table.get("recurring_portion") or 0) != 0),
            "has_stated_budget_impact": bool(
                (impact_table and (impact_table.get("total") or 0) != 0)
                or (impact and not re.search(r"no\s+(FY[\d-]+\s+)?operating impact",
                                             impact, re.I))),
            "expenditures_by_account": [
                {"account": a, "amounts": v} for a, v in
                tables.get("expenditures", {}).get("rows", [])],
            "funding_by_source": [
                {"source": ("Not named in the town's document" if UNNAMED.match(a) else a),
                 "amounts": v, "unnamed_in_source": bool(UNNAMED.match(a))}
                for a, v in tables.get("funding", {}).get("rows", [])],
            "total_planned_cost": total_cost,
            "reconciliation": checks,
            "published": publishable,
        }
        if not publishable:
            problems.append(f"{name}: columns do not reconcile to the printed AMOUNT row "
                            f"— withheld")
        projects.append(rec)

    published = [p for p in projects if p["published"]]
    withheld = [p for p in projects if not p["published"]]

    by_fund: dict[str, dict] = {}
    for p in published:
        f = p["fund"] or "Unstated"
        s = by_fund.setdefault(f, {"projects": 0, "total_planned_cost": 0.0,
                                   "create_recurring_cost": 0})
        s["projects"] += 1
        s["total_planned_cost"] += p["total_planned_cost"] or 0
        s["create_recurring_cost"] += 1 if p["creates_recurring_cost"] else 0
        s["with_stated_budget_impact"] = s.get("with_stated_budget_impact", 0) + (
            1 if p["has_stated_budget_impact"] else 0)
    for s in by_fund.values():
        s["total_planned_cost"] = round(s["total_planned_cost"], 2)

    accounts = sorted({e["account"] for p in published for e in p["expenditures_by_account"]})
    sources = sorted({f["source"] for p in published for f in p["funding_by_source"]})

    write_json(DATASETS / "projects.json", {
        "generated_by": "etl/s94_projects.py",
        "requested_by": ("Amy — \"I do want Project to be a real dimension.\" Stage 88 reported "
                         "Project as the one dimension of her seven that this data could not "
                         "fill."),
        "source_doc": SOURCE_DOC,
        "what_this_adds": ("A project identifier that a capital spending row can point at, so a "
                           "single decision's cost can be gathered across every account and year "
                           "it touches — which is what her Fire Station #3 example needs."),
        "verification": ("Every project is checked against its own printed AMOUNT row, per year "
                         "column rather than on the grand total, so one bad column cannot hide "
                         "inside a correct total. Projects that do not reconcile are withheld."),
        "change_event_link": ("A capital project is a one-time expenditure that creates a "
                             "recurring obligation, which is the Change Event with a long tail "
                             "her model describes. The town states the operating impact per "
                             "project in prose, so it is captured rather than inferred."),
        "summary": {
            "projects_published": len(published),
            "projects_withheld": len(withheld),
            "total_planned_cost": round(sum(p["total_planned_cost"] or 0 for p in published), 2),
            "projects_creating_recurring_cost": sum(
                1 for p in published if p["creates_recurring_cost"]),
            "projects_with_any_stated_budget_impact": sum(
                1 for p in published if p["has_stated_budget_impact"]),
            "recurring_cost_created": round(sum(
                (p["operating_budget_impact_quantified"] or {}).get("recurring_portion", 0) or 0
                for p in published), 2),
            "by_fund": by_fund,
            "distinct_accounts": len(accounts),
            "distinct_funding_sources": len(sources),
        },
        "data_quality_findings": [
            {"finding": ("The town's document prints \"Empty Values\" where a funding source "
                         "label should be, so the funding for some projects is unnamed. For the "
                         "Passenger Rail and Multi-Modal Station — the largest project in the "
                         "plan — the entire amount is unnamed."),
             "projects": [p["project_name"] for p in published
                          if any(f["unnamed_in_source"] for f in p["funding_by_source"])],
             "amount_unnamed": round(sum(
                 sum(f["amounts"]) for p in published for f in p["funding_by_source"]
                 if f["unnamed_in_source"]), 2),
             "handling": ("The amounts are published because they are real and reconcile; the "
                          "label is reported as unnamed rather than shown as \"Empty Values\", "
                          "which would read as a fault in this site rather than in the source."),
             "worth_raising": True},
        ],
        "accounts_used": accounts,
        "funding_sources": sources,
        "projects": published,
        "withheld": [{"project_name": p["project_name"], "source_pages": p["source_pages"],
                      "reconciliation": p["reconciliation"]} for p in withheld],
        "problems": problems,
    })

    print(f"  {len(published)} projects published, {len(withheld)} withheld")
    for f, s in sorted(by_fund.items(), key=lambda x: -x[1]["total_planned_cost"]):
        print(f"      {f[:38]:40} {s['projects']:3} projects  "
              f"${s['total_planned_cost']:>14,.0f}  "
              f"{s['create_recurring_cost']} creating debt service")
    print(f"\n  largest planned projects:")
    for p in sorted(published, key=lambda p: -(p["total_planned_cost"] or 0))[:8]:
        print(f"      ${p['total_planned_cost']:>13,.0f}  {p['project_name'][:44]:46} "
              f"{(p['department'] or '—')[:20]}")
    if withheld:
        print(f"\n  withheld:")
        for p in withheld[:6]:
            bad = [c for c in p["reconciliation"] if not c["reconciles"]]
            print(f"      {p['project_name'][:46]:48} {len(bad)} column(s) off")
    if problems:
        print(f"\n  {len(problems)} problem(s); first few:")
        for x in problems[:5]:
            print(f"      {x}")


if __name__ == "__main__":
    main()
