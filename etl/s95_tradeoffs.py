"""Stage 95 — what got funded, what did not, and what the town says that costs.

Amy's request:

    "Conceptually what I really want to show is what the tradeoffs are in the spending.
     When the town starts spending $350k new incremental for affordable housing, and
     higher pensions, and compensation increases, and new personnel, what is this cost,
     and what didn't get funded?"

This is the hardest thing on her list and the most valuable, because a budget document
is built to answer the opposite question. It shows what *was* funded. What was declined
usually leaves no trace, and a transparency site that only totals approved spending
quietly adopts the government's own framing.

**Hillsborough is unusually good here, and publishes both sides.** Two structures make
this answerable without a single inference:

  1. **Noteworthy Requests**, per fund, split into *Funded* and *Unfunded* lists with
     amounts for FY2027, FY2028 and FY2029. The unfunded list is the answer to "what
     didn't get funded", in the town's own words and arithmetic.

  2. **Budget Justification Forms** — one per request, carrying the fund, department,
     priority rank, a description, the strategic-plan objective it serves, and, on most
     of them, a section headed **"Alternatives & Operational Impact if Not Funded"**.
     That is the town stating the consequence of declining each request. It is the
     tradeoff, sourced rather than editorialised.

One form goes further and names the tradeoff outright. On affordable housing:

    "Community Home Trust has requested a funding increase of $2,500 in FY27. This
     request is currently unfunded. This request could be funded by reducing the
     allocation to affordable housing creation and preservation."

So the same $320,000 commitment Amy asked about is itself the thing that would have to
be cut to fund the smaller request beside it. That is a genuine tradeoff, published.

**The resident-facing translation.** A declined total in dollars means little on its own,
so it is also expressed in the two units a resident already understands: cents on the tax
rate, and dollars on their own home. That conversion uses the town's own published yield
per cent, not an estimate.

Every list is reconciled to its own printed AMOUNT row before publication. Nothing here
ranks or judges the decisions — it reports what was asked, what was granted, what was
declined, and what the town itself said the consequence would be.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, read_json, write_json  # noqa: E402
from s94_projects import UNNAMED, load_pages, parse_table  # noqa: E402

SOURCE_DOC = "FY27 Budget and Financial Plan Recommended.pdf"
DOC_ID = "fy27-budget-and-financial-plan-recommended"

FORM = re.compile(r"Budget Justification Form\s*\(FY(\d{2})\s*-\s*FY(\d{2})\)", re.I)
# Both spellings occur in the document ("and" on 22 forms, "&" on 19).
ALT = r"Alternatives\s*(?:and|&)\s*Operational Impact if Not Funded"
FORM_SECTION = re.compile(
    rf"^(Request Description|Describe Request|Link to Strategic Plan or Departmental Priorities|"
    rf"{ALT}|Additional Information|Budget Justification Expenditures|Application Items)\s*$",
    re.I)
# Each list is announced TWICE — a bare banner, then a qualified caption naming the
# fund ("General Fund: Unfunded Noteworthy Requests"). Matching both counted every
# request twice and doubled the declined total. Only the qualified caption is used,
# because it also carries the fund name, which the bare banner does not.
LIST_HDR = re.compile(r"^(?P<fund>.+?):\s*(?P<status>Funded|Unfunded) Noteworthy Requests\s*$",
                      re.I)
ANY_LIST_HDR = re.compile(r"(Funded|Unfunded) Noteworthy Requests\s*$", re.I)
TOTAL = re.compile(r"^\s*AMOUNT\s*\$", re.I)


def prose_after(lines: list[str], idx: int, limit: int = 14) -> str | None:
    body = []
    for l in lines[idx + 1:]:
        s = l.strip()
        if not s or re.fullmatch(r"\d{1,4}", s):
            continue
        if FORM_SECTION.match(s) or FORM.search(s):
            break
        body.append(s)
        if len(body) >= limit:
            break
    joined = " ".join(body) if body else None
    # Several forms fill a section with "N/A"; that is an absence, not a statement.
    if joined and re.fullmatch(r"(n/?a\.?|none\.?|tbd\.?)", joined.strip(), re.I):
        return None
    return joined


def read_noteworthy(pages: list[str], problems: list[str]) -> list[dict]:
    """The Funded / Unfunded request lists, per fund."""
    out = []
    for pno, text in enumerate(pages, 1):
        if "Noteworthy Requests" not in text or "Worksheet Name" not in text:
            continue
        lines = [l.rstrip() for l in text.split("\n")]
        for i, l in enumerate(lines):
            hm = LIST_HDR.match(l.strip())
            if not hm:
                continue
            fund = hm.group("fund").strip()
            status = hm.group("status").lower()
            # A list with no rows says so in prose ("No unfunded requests.").
            tail = "\n".join(lines[i + 1:i + 4])
            if re.search(r"No unfunded requests", tail, re.I):
                out.append({"fund": fund, "status": status, "source_page": pno,
                            "items": [], "printed_total": [0.0],
                            "stated_none": True, "reconciles": True})
                continue
            tb, _ = parse_table(lines, i + 1, stop=ANY_LIST_HDR)
            if not tb.get("rows") and not tb.get("totals"):
                continue
            items = [{"request": ("Not named in the town's document" if UNNAMED.match(a) else a),
                      "unnamed_in_source": bool(UNNAMED.match(a)),
                      "amounts": v, "fy2027": v[0] if v else None,
                      "total_three_year": round(sum(v), 2)}
                     for a, v in tb["rows"]]
            totals = tb.get("totals") or []
            ncol = min(len(totals), min((len(i2["amounts"]) for i2 in items), default=0)) \
                if items else 0
            ok = bool(totals)
            for c in range(ncol):
                if abs(sum(i2["amounts"][c] for i2 in items) - totals[c]) >= 1.0:
                    ok = False
            if not ok and items:
                problems.append(f"p{pno}: the {status} list for {fund} does not reconcile to its "
                                f"printed AMOUNT row — withheld")
            out.append({"fund": fund, "status": status, "source_page": pno, "items": items,
                        "printed_total": totals, "stated_none": False, "reconciles": ok})
    return out


def read_forms(pages: list[str], problems: list[str]) -> list[dict]:
    """One record per Budget Justification Form, including the not-funded consequence."""
    forms = []
    for pno, text in enumerate(pages, 1):
        if not FORM.search(text):
            continue
        lines = [l.rstrip() for l in text.split("\n")]
        hdr_i = next((i for i, l in enumerate(lines) if FORM.search(l)), None)
        if hdr_i is None or hdr_i == 0:
            continue
        title = " ".join(l.strip() for l in lines[:hdr_i]
                         if l.strip() and not re.fullmatch(r"\d{1,4}", l.strip()))
        if not title:
            continue

        fund = dept = rank = None
        for i, l in enumerate(lines[hdr_i:hdr_i + 5], hdr_i):
            if re.search(r"Fund\s+Department\s+Priority", l, re.I) and i + 1 < len(lines):
                v = lines[i + 1].strip()
                m = re.match(r"(.+?Fund)\s+(.+?)\s+(\d+|None)\s*$", v)
                if m:
                    fund, dept = m.group(1), m.group(2).strip()
                    rank = None if m.group(3) == "None" else int(m.group(3))
                else:
                    fund = v or None
                break

        def sect(pattern):
            i = next((j for j, l in enumerate(lines)
                      if re.fullmatch(pattern, l.strip(), re.I)), None)
            return prose_after(lines, i) if i is not None else None

        # The consequence of NOT funding — the tradeoff, in the town's own words.
        not_funded = sect(ALT)
        amounts, total, recon = [], None, None
        bi = next((j for j, l in enumerate(lines)
                   if re.fullmatch(r"Budget Justification Expenditures", l.strip(), re.I)), None)
        if bi is not None:
            tb, _ = parse_table(lines, bi + 1, stop=FORM_SECTION)
            if tb.get("rows"):
                amounts = [{"division": a, "amounts": v} for a, v in tb["rows"]]
                if tb.get("totals"):
                    total = round(sum(tb["totals"]), 2)
                    ncol = min(len(tb["totals"]), min(len(v) for _, v in tb["rows"]))
                    recon = all(abs(sum(v[c] for _, v in tb["rows"]) - tb["totals"][c]) < 1.0
                                for c in range(ncol))
                    if not recon:
                        problems.append(f"p{pno}: '{title}' expenditure table does not reconcile")

        forms.append({
            "request": title, "fund": fund, "department": dept, "priority_rank": rank,
            "source_doc": DOC_ID, "source_page": pno,
            "description": sect(r"Request Description|Describe Request"),
            "strategic_plan_link": sect(
                r"Link to Strategic Plan or Departmental Priorities"),
            "impact_if_not_funded": not_funded,
            "states_a_fundable_alternative": bool(re.search(
                r"could be funded by|reducing the allocation|in place of|instead of",
                " ".join(x for x in (not_funded, sect(r"Request Description|Describe Request"),
                                     sect(r"Additional Information")) if x), re.I)),
            "by_division": amounts, "total_requested": total,
            "reconciles": recon,
        })
    return forms


ABBREV = [(r"\bn\.?\b", "north"), (r"\bs\.?\b", "south"), (r"\be\.?\b", "east"),
          (r"\bw\.?\b", "west"), (r"\bats\b", "automatic transfer switch"),
          (r"\b&\b", "and"), (r"\bdept\.?\b", "department")]


def norm(s: str) -> str:
    """Loose key for matching a request list entry to its justification form."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def tokens(s: str) -> set:
    t = (s or "").lower()
    for pat, rep in ABBREV:
        t = re.sub(pat, rep, t)
    # Words that appear in half the titles carry no matching signal.
    stop = {"the", "of", "at", "for", "and", "a", "request", "increase", "replacement",
            "expansion", "street", "fund", "town"}
    return {w for w in re.findall(r"[a-z0-9]+", t) if w not in stop and len(w) > 1}


def best_form(request: str, forms: list[dict]) -> tuple[dict | None, str]:
    """Match a request-list entry to its justification form.

    The two lists do not use identical wording — the town writes "Fire Station at N.
    Churton Street Ramp-Up" on the form and "Fire Station at North Churton Street Ramp-Up
    Expansion" in the list. An exact-name join therefore missed real matches, and the
    site then said the town had stated no consequence when in fact no form had been
    found. Those are different claims, and only one of them is about the town.
    """
    key = norm(request)
    for f in forms:
        if norm(f["request"]) == key:
            return f, "exact name"
    rt = tokens(request)
    if rt:
        scored = []
        for f in forms:
            ft = tokens(f["request"])
            if not ft:
                continue
            overlap = len(rt & ft) / max(1, min(len(rt), len(ft)))
            scored.append((overlap, f))
        scored.sort(key=lambda x: -x[0])
        if scored and scored[0][0] >= 0.75:
            return scored[0][1], f"name variant ({scored[0][0]:.0%} of words shared)"
    # Last resort: a form whose text discusses this request by name. That is a genuine
    # cross-reference, not a name variant, and is labelled as one — the Community Home
    # Trust ask is described inside the Affordable Housing form, not on its own.
    short = re.sub(r"\s*-\s*.*$", "", request).strip()
    if len(short) > 8:
        for f in forms:
            blob = " ".join(x for x in (f.get("description"), f.get("impact_if_not_funded"),
                                        f.get("strategic_plan_link")) if x)
            if short.lower() in blob.lower():
                return f, f"discussed within the form for \"{f['request']}\""
    return None, "no form found"


def main() -> None:
    pages = load_pages()
    problems: list[str] = []
    lists = read_noteworthy(pages, problems)
    forms = read_forms(pages, problems)

    funded, unfunded = [], []
    for lst in lists:
        if not lst["reconciles"]:
            continue
        for it in lst["items"]:
            rec = {**it, "fund": lst["fund"], "source_page": lst["source_page"]}
            form, how = best_form(it["request"], forms)
            rec["justification_matched"] = bool(form)
            rec["justification_match_basis"] = how
            if form:
                rec["justification_form"] = form["request"]
                rec["justification_page"] = form["source_page"]
                rec["department"] = form["department"]
                rec["priority_rank"] = form["priority_rank"]
                rec["description"] = form["description"]
                rec["impact_if_not_funded"] = form["impact_if_not_funded"]
                rec["strategic_plan_link"] = form["strategic_plan_link"]
                rec["states_a_fundable_alternative"] = form["states_a_fundable_alternative"]
            (funded if lst["status"] == "funded" else unfunded).append(rec)

    # --- the resident-facing translation -------------------------------------
    facts = read_json(DATASETS / "facts.json")["facts"]
    def fv(metric):
        rows = [f for f in facts if f["metric"] == metric]
        return rows[-1]["value"] if rows else None

    per_cent = fv("one_cent_of_tax_yields") or fv("revenue_per_cent_of_tax_rate")
    HOME = 400000.0

    def in_resident_terms(amount: float) -> dict:
        out = {"dollars": round(amount, 2)}
        if per_cent:
            cents_ = amount / per_cent
            out["cents_on_the_tax_rate"] = round(cents_, 3)
            out["per_year_on_a_400k_home"] = round(HOME / 100 * cents_ / 100, 2)
            out["basis"] = (f"The town states one cent on its tax rate raises "
                            f"${per_cent:,.0f} across the whole town.")
        return out

    def year_total(rows, idx=0):
        return round(sum(r["amounts"][idx] for r in rows if len(r["amounts"]) > idx), 2)

    fy27_funded, fy27_unfunded = year_total(funded), year_total(unfunded)
    asked = fy27_funded + fy27_unfunded

    write_json(DATASETS / "tradeoffs.json", {
        "generated_by": "etl/s95_tradeoffs.py",
        "requested_by": ("Amy — \"what I really want to show is what the tradeoffs are in the "
                         "spending... what is this cost, and what didn't get funded?\""),
        "source_doc": SOURCE_DOC,
        "why_this_is_possible": ("A budget document is built to show what was funded; what was "
                                "declined usually leaves no trace. Hillsborough publishes both — "
                                "Funded and Unfunded Noteworthy Requests per fund, and a Budget "
                                "Justification Form per request carrying a section headed "
                                "'Alternatives & Operational Impact if Not Funded'. So the "
                                "tradeoff is the town's own statement, not this site's opinion."),
        "method": ("Every list is reconciled to its own printed AMOUNT row before publication. "
                   "Request-list entries are joined to their justification form by name. Nothing "
                   "here ranks or second-guesses the decisions."),
        "summary": {
            "requests_funded": len(funded),
            "requests_declined": len(unfunded),
            "fy2027_funded": fy27_funded,
            "fy2027_declined": fy27_unfunded,
            "fy2027_total_asked": round(asked, 2),
            "share_of_asks_funded_pct": round(fy27_funded / asked * 100, 1) if asked else None,
            "declined_in_resident_terms": in_resident_terms(fy27_unfunded),
            "three_year_declined": round(sum(sum(r["amounts"]) for r in unfunded), 2),
            "forms_read": len(forms),
            "forms_stating_impact_if_not_funded": sum(
                1 for f in forms if f["impact_if_not_funded"]),
            "forms_naming_a_fundable_alternative": sum(
                1 for f in forms if f["states_a_fundable_alternative"]),
        },
        "years": [2027, 2028, 2029],
        "declined": sorted(unfunded, key=lambda r: -(r["fy2027"] or 0)),
        "funded": sorted(funded, key=lambda r: -(r["fy2027"] or 0)),
        "request_lists": lists,
        "justification_forms": forms,
        "caveats": [
            "These are the requests the town chose to call noteworthy. A department may never "
            "have submitted a request it expected to be refused, and that never appears here.",
            "'Declined' means not funded in this recommended budget. The board may still add an "
            "item before adoption, so these are the manager's recommendations, not final.",
            "The funded and declined figures are new or incremental requests, not the whole "
            "budget. Most spending is continuing operations that no one re-requests each year.",
        ],
        "problems": problems,
    })

    s = read_json(DATASETS / "tradeoffs.json")["summary"]
    print(f"  {len(forms)} justification forms, {s['forms_stating_impact_if_not_funded']} state an "
          f"impact if not funded, {s['forms_naming_a_fundable_alternative']} name a fundable "
          f"alternative")
    print(f"  FY2027 asks: ${s['fy2027_total_asked']:,.0f} — "
          f"${s['fy2027_funded']:,.0f} funded, ${s['fy2027_declined']:,.0f} declined "
          f"({s['share_of_asks_funded_pct']}% of asks funded)")
    rt = s["declined_in_resident_terms"]
    if rt.get("cents_on_the_tax_rate"):
        print(f"  declined = {rt['cents_on_the_tax_rate']:.2f} cents on the tax rate, "
              f"${rt['per_year_on_a_400k_home']:.0f}/yr on a $400k home")
    print(f"\n  declined requests:")
    for r in sorted(unfunded, key=lambda r: -(r["fy2027"] or 0)):
        print(f"      FY27 ${r['fy2027'] or 0:>9,.0f}  (3yr ${r['total_three_year']:>9,.0f})  "
              f"{r['request'][:44]:46} {r['fund'] or ''}")
        if r.get("impact_if_not_funded"):
            print(f"                   -> {r['impact_if_not_funded'][:104]}")
    if problems:
        print(f"\n  {len(problems)} problem(s):")
        for p in problems[:6]:
            print(f"      {p}")


if __name__ == "__main__":
    main()
