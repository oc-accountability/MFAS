"""Shared reader for nested financial statements printed as PDF tables.

Extracted from stage 61 once a SECOND family of documents needed exactly the same
machinery: the Orange County ACFRs are the same kind of artefact as the town's
audits — nested statements, right-aligned figure columns, printed subtotals — and
duplicating four hundred lines of parser would have guaranteed the two copies
drifted apart. Everything here is jurisdiction-agnostic; what differs per document
family (which pages to read, how to name a fund, where facts are routed) stays in
the stage that calls it.

The whole design rests on one property: **a figure is trustworthy only when the
page's own arithmetic proves it.** Components must add to the total printed beside
them, column by column; roll-forward lines must satisfy the statement's own
identities; column roles must be confirmed by the variance identity rather than
assumed from column order. Anything unproven is withheld and reported, never
published with a caveat.

The traps encoded here were each paid for on real documents, and they are recorded
at the function that defends against them:

  * a fixed label/figure boundary slices through the first figure column
  * clustering raw word edges lets parentheses and centred dashes invent columns
  * labels and figures need different tokenisation, and sharing one silently
    welded "Total revenues" into "Totalrevenues" and destroyed every schedule
  * "Total assets" closes ASSETS, not the innermost "Capital assets:" group
  * not every subtotal is called "Total", and some are not labelled at all
  * an account can legitimately be NAMED "Total OPEB liability"
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# --- geometry --------------------------------------------------------------
BAND = 3.0          # pt; rows are grouped into horizontal bands this tall
CHAR_GAP = 5.0      # pt; chars further apart than this start a new token.
                    # Internal stray spaces inside a figure ("1 0,474,657") are
                    # ~2-3pt; the gap between columns is ~30pt. 5 separates them.
COL_TOL = 9.0       # pt; how near a digit's right edge must be to claim a column
MIN_COL_HITS = 3    # a column must recur this often to be believed

JUR = "Town of Hillsborough, NC"

# Statements whose grain IS fund-level revenue/expenditure/other-financing. Only
# these route into the financial fact table; everything else stays a companion
# fact with its own declared grain.
FINANCIAL_TITLE = re.compile(
    r"Revenues,\s*Expenditures|Revenues,\s*Expenses|Balance\s+Sheet|"
    r"Statement\s+of\s+Activities|Revenues\s+and\s+Expenditures", re.I)

# Pages that are prose, notes, opinions or signatures carry no parseable grid.
SKIP_TITLE = re.compile(r"Notes\s+to\s+the\s+Financial|Table\s+of\s+Contents|"
                        r"Independent\s+Auditor|Schedule\s+of\s+Findings", re.I)

# Which pages hold a statement worth reading. This must NOT be "Exhibit or
# Schedule": that is the Town of Hillsborough's house style, and using it as the
# gate meant the Orange County ACFRs gave up 24 pages out of 230 while skipping the
# single most important one in the book. The county titles its statements in caps
# with no exhibit label at all —
#
#     ORANGE COUNTY, NORTH CAROLINA / GENERAL FUND / STATEMENT OF REVENUES,
#     EXPENDITURES, AND CHANGES IN FUND BALANCES - BUDGET TO ACTUAL (NON-GAAP)
#
# — which is exactly the statement Amy transcribed by hand and cited to PDF page 42.
# 296 of her figures looked "not found" purely because of this filter. Match on what
# a statement IS, not on how one government happens to label it. Hillsborough gains
# too: its continuation pages ("Balance Sheet Governmental Funds (continued)",
# "Reconciliation of the Statement of…") carry no Exhibit keyword either.
STATEMENT_TITLE = re.compile(
    r"Statement\s+of|Schedule\s+of|Balance\s+Sheet|Combining|Exhibit|Schedule\s+\d|"
    r"Budget\s+(?:to|and)\s+Actual|Reconciliation\s+of|Analysis\s+of\s+Current|"
    r"Schedules?\s+of|Statements?\s+of", re.I)

TOTAL = re.compile(r"^Total\b", re.I)
FY_IN_TEXT = re.compile(r"(?:Year|Years)\s+Ended\s+June\s+30,?\s*(20\d{2})", re.I)

# The documents this stage reads: every Hillsborough audit that is digital text.
# Deliberately a fixed list rather than a glob — a new scan appearing under a
# similar name must not silently start feeding the pipeline unverified figures.
WANTED_DOC_IDS = [
    "audit-2021",
    "hillsborough-2022-audit-stamped",
    "hillsborough-2023-audit-stamped",
    "hillsborough-2024-audit-stamped",
    "hillsborough-2025-audit-stamped",
]


def tokens_in_band(chars: list) -> list[dict]:
    """Group a band's characters into tokens, keeping each token's DIGIT right edge.

    The digit edge is the load-bearing part: it is immune to a trailing ')' and to
    a centred dash, both of which move a word's right edge and both of which
    corrupted the column grid when clustering raw word edges (trap 2).
    """
    out: list[dict] = []
    for ch in sorted(chars, key=lambda c: c["x0"]):
        t = ch["text"]
        if not t.strip():
            continue
        if out and ch["x0"] - out[-1]["x1"] <= CHAR_GAP:
            tok = out[-1]
            tok["text"] += t
            tok["x1"] = ch["x1"]
        else:
            out.append({"text": t, "x0": ch["x0"], "x1": ch["x1"], "digit_x1": None})
            tok = out[-1]
        if t.isdigit():
            tok["digit_x1"] = ch["x1"]
    return out


def bands_of(page) -> list[tuple[list[dict], list[dict]]]:
    """One entry per horizontal band: (words, character-tokens).

    Both are needed and they are not interchangeable (trap 3): the words carry
    correct spacing for the label, the character-tokens carry the digit edges and
    the fragment merging the figures need.
    """
    wb: dict[int, list] = defaultdict(list)
    cb: dict[int, list] = defaultdict(list)
    for w in page.extract_words():
        wb[round(w["top"] / BAND)].append(w)
    for ch in page.chars:
        cb[round(ch["top"] / BAND)].append(ch)
    return [(sorted(wb.get(k, []), key=lambda w: w["x0"]), tokens_in_band(cb.get(k, [])))
            for k in sorted(set(wb) | set(cb))]


MONEY = re.compile(r"^\(?\$?-?[\d,]*\d[\d,]*\)?$")


def detect_grid(rows) -> tuple[list[float], float | None]:
    """Find the figure columns, and from them the label/figure boundary (trap 1)."""
    pts = [(t["digit_x1"], t["x0"]) for _words, toks in rows for t in toks
           if t["digit_x1"] is not None and MONEY.match(t["text"])]
    if not pts:
        return [], None
    pts.sort()
    clusters: list[list[tuple[float, float]]] = []
    for x1, x0 in pts:
        if clusters and x1 - clusters[-1][-1][0] <= COL_TOL:
            clusters[-1].append((x1, x0))
        else:
            clusters.append([(x1, x0)])
    keep = [c for c in clusters if len(c) >= MIN_COL_HITS]
    if not keep:
        return [], None
    edges = [max(x1 for x1, _ in c) for c in keep]
    boundary = min(x0 for _, x0 in keep[0]) - 4.0
    return edges, boundary


def clean_number(tok: str) -> float | None:
    """'1 0,474,657' -> 10474657; '(878,434)' -> -878434; '-' -> None.

    Refuses anything that is not properly grouped thousands once stray spaces are
    removed. Guessing at a malformed figure is worse than skipping it.
    """
    t = tok.strip()
    if t in {"-", "–", "—", ""}:
        return None
    neg = t.startswith("(") or t.endswith(")")
    t = t.strip("()").replace("$", "").replace(" ", "").replace(",", "")
    if not t or not t.isdigit():
        return None
    return -float(t) if neg else float(t)


def split_row(words: list[dict], toks: list[dict],
              boundary: float) -> tuple[str, float | None, list[dict]]:
    """Label from the WORDS (correct spacing), figures from the CHARACTERS (trap 3)."""
    lab = [w for w in words if w["x1"] < boundary and w["text"] != "$"]
    figs = [t for t in toks if t["x1"] >= boundary and t["text"] != "$"]
    label = re.sub(r"\s*\$\s*$", "", " ".join(w["text"] for w in lab)).strip()
    return label, (lab[0]["x0"] if lab else None), figs


def to_columns(figs, edges) -> tuple[list[float | None], list[str]]:
    vals: list[float | None] = [None] * len(edges)
    bad: list[str] = []
    for t in figs:
        v = clean_number(t["text"])
        if v is None:
            continue
        ref = t["digit_x1"] if t["digit_x1"] is not None else t["x1"]
        near = min(range(len(edges)), key=lambda i: abs(edges[i] - ref))
        if abs(edges[near] - ref) > COL_TOL or vals[near] is not None:
            bad.append(t["text"])
            continue
        vals[near] = v
    return vals, bad


def statement_title(page) -> str:
    text = page.extract_text() or ""
    head = [ln.strip() for ln in text.splitlines()[:8] if ln.strip()]
    return " ".join(head)


def parse_page(page, page_no: int):
    """Return (rows, edges, problems) for one statement page."""
    rows_tok = bands_of(page)
    edges, boundary = detect_grid(rows_tok)
    problems: list[str] = []
    if len(edges) < 2 or boundary is None:
        return [], edges, problems

    parsed = []
    for words, toks in rows_tok:
        label, indent, figs = split_row(words, toks, boundary)
        vals, bad = to_columns(figs, edges)
        if not label and not any(v is not None for v in vals):
            continue                      # blank, or a rule
        # An UNLABELLED figure row is kept, because in the FY2021-FY2023 audits the
        # departmental subtotal has no label at all — just a rule and the figures.
        # Dropping them meant no department group ever closed and Schedule 1 yielded
        # nine groups a year instead of twenty-eight. Whether such a row really is a
        # subtotal is decided by arithmetic in group_rows, never by its position.
        if bad:
            problems.append(f"p{page_no}: {label[:40]!r} figure(s) {bad} match no column")
        parsed.append({"label": label, "indent": indent, "values": vals,
                       "has_figures": any(v is not None for v in vals)})
    return parsed, edges, problems


ALLCAPS = re.compile(r"^[A-Z][A-Z &'()/\-,.]{2,}$")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def group_rows(parsed, ncols: int):
    """Close the document's own nesting with a stack; return reconciliation groups.

    The document names what it totals, and that name is the only reliable way to
    know which level a total closes. "Total assets" in the Statement of Net
    Position closes ASSETS — not the innermost open group "Capital assets:", which
    prints no total of its own. Closing innermost unconditionally was the first
    version of this function and it mis-summed 203 of 460 groups.

    So: a total whose name matches an open group closes THAT group, popping the
    intermediate groups on the way. A group popped without a total of its own was
    a presentational heading rather than a subtotal level, so its members are
    PROMOTED to the group being closed — which is what makes "Total assets" equal
    the sum of the lines under Cash and investments, Receivables and Capital
    assets together. A generic "Total" (Schedule 1 prints one per department)
    matches nothing and closes the innermost group, which is correct there.

    Two further shapes the statements use:

      * Section headers are ALL CAPS with no colon (ASSETS, LIABILITIES, NET
        POSITION, PRIMARY GOVERNMENT), and wrap across lines ("DEFERRED OUTFLOWS
        OF" / "RESOURCES"). Consecutive caps headers at one indent are one header.
      * A long line label wraps too ("Accounts payable and accrued" / "liabilities",
        "Hillsborough Tourism" / "Development Authority"). A figureless row that is
        neither header shape is a label fragment for the row beneath it.

    Consumed members are cleared, because two totals at the same level must not
    both consume the whole accumulator — that made "Total component units" sum the
    primary government as well as the component units.
    """
    groups = []
    page = {"label": "(page)", "indent": -1.0, "members": []}
    stack: list[dict] = [page]
    pending: list[str] = []      # wrapped label fragments
    last_header: dict | None = None
    started = False              # have we passed the page heading yet?

    def pop_to(target_i: int) -> dict:
        """Pop down to stack[target_i], promoting the members of totalless levels."""
        while len(stack) - 1 > target_i:
            dead = stack.pop()
            stack[-1]["members"].extend(dead["members"])
        return stack[target_i]

    for r in parsed:
        label = r["label"].strip()
        indent = r["indent"] if r["indent"] is not None else 0.0

        if not r["has_figures"]:
            is_header = label.rstrip().endswith(":") or bool(ALLCAPS.match(label))
            if not is_header:
                # Before the first header or figure, these are the page heading —
                # the town name, the statement title, the date. Accumulating them
                # renamed the ASSETS group to "Town of Hillsborough, … ASSETS", so
                # "Total assets" no longer matched it and thirteen balance sheets
                # summed only their last sub-block.
                if started:
                    pending.append(label)
                continue
            started = True
            full = " ".join(pending + [label]).strip()
            pending = []
            # A caps header continuing the previous caps header at the same indent
            # is the same header wrapped, not a new level.
            if (last_header is not None and ALLCAPS.match(label)
                    and last_header.get("caps") and abs(last_header["indent"] - indent) < 1.0
                    and not last_header["members"]):
                last_header["label"] = f"{last_header['label']} {full}".strip()
                continue
            while len(stack) > 1 and stack[-1]["indent"] >= indent:
                dead = stack.pop()
                stack[-1]["members"].extend(dead["members"])
            grp = {"label": full.rstrip(":").strip(), "indent": indent, "members": [],
                   "caps": bool(ALLCAPS.match(label))}
            stack.append(grp)
            last_header = grp
            continue

        # An unlabelled figure row closes the innermost open group as its implicit
        # subtotal — but only when a real group is open and has something to total,
        # which is what keeps the "2021 2020" year header (also unlabelled, also
        # numeric) from consuming the page level and poisoning every later total.
        if not label:
            if len(stack) > 1 and len(stack[-1]["members"]) >= 2:
                grp = stack.pop()
                groups.append({"group": grp["label"],
                               "total_label": "(unlabelled subtotal)",
                               "total": r["values"], "members": list(grp["members"])})
                stack[-1]["members"].append({
                    "label": f"{grp['label']} / (subtotal)",
                    "values": r["values"], "is_subtotal": True})
                last_header = None
            continue

        label = " ".join(pending + [label]).strip() if pending else label
        pending = []
        started = True

        if TOTAL.match(label):
            name = _norm(re.sub(r"^Total\b", "", label, flags=re.I))
            target_i = 0
            if name:
                for i in range(len(stack) - 1, 0, -1):
                    if _norm(stack[i]["label"]) == name:
                        target_i = i
                        break
                else:
                    target_i = max(0, len(stack) - 1)
            else:
                target_i = max(0, len(stack) - 1)

            grp = pop_to(target_i)
            groups.append({"group": grp["label"], "total_label": label,
                           "total": r["values"], "members": list(grp["members"])})
            grp["members"].clear()
            if grp is not page:
                stack.pop()
            parent = stack[-1] if stack else page
            parent["members"].append({"label": f"{grp['label']} / {label}".lstrip(" /"),
                                      "values": r["values"], "is_subtotal": True})
            last_header = None
            continue

        stack[-1]["members"].append({"label": label, "values": r["values"],
                                     "is_subtotal": False})
    return groups


def collapse_inner_subtotals(members, ncols: int):
    """Fold a member that is itself the sum of the members just above it.

    Not every subtotal is called "Total". The proprietary funds statement prints
    "Capital assets, net" directly beneath "Land and construction-in-progress" and
    "Depreciable assets, net", and it is their sum — so counting all three put
    $63,049,803 into "Total assets" twice. Detected by the document's own
    arithmetic across every column the two share, never by the label, and only
    when at least two columns agree, which makes a coincidence implausible.
    """
    out = list(members)
    i = 0
    while i < len(out):
        cand = out[i]
        for start in range(max(0, i - 8), i - 1):
            run = out[start:i]
            agree = 0
            for c in range(ncols):
                tot = cand["values"][c] if c < len(cand["values"]) else None
                parts = [m["values"][c] for m in run
                         if c < len(m["values"]) and m["values"][c] is not None]
                if tot is None or len(parts) < 2:
                    continue
                if abs(sum(parts) - tot) < 1.5:
                    agree += 1
                else:
                    agree = -99
                    break
            if agree >= 2:
                cand = dict(cand)
                cand["is_subtotal"] = True
                cand["collapsed_lines"] = [m["label"] for m in run]
                out[start:i + 1] = [cand]
                i = start
                break
        i += 1
    return out


def reconcile(groups, ncols: int):
    """Per column: do the members add to the printed total? Only then publish."""
    checked = []
    for g in groups:
        members = collapse_inner_subtotals(list(g["members"]), ncols)
        if not members:
            continue
        cols = []
        for c in range(ncols):
            tot = g["total"][c] if c < len(g["total"]) else None
            parts = [m["values"][c] for m in members
                     if c < len(m["values"]) and m["values"][c] is not None]
            if tot is None or not parts:
                cols.append({"column_index": c, "printed_total": tot,
                             "sum_of_lines": None, "reconciles": None})
                continue
            got = sum(parts)
            cols.append({"column_index": c, "printed_total": tot,
                         "sum_of_lines": round(got, 2), "lines": len(parts),
                         "reconciles": abs(got - tot) < 1.5})
        any_checked = [c for c in cols if c["reconciles"] is not None]
        g2 = dict(g)
        g2["members"] = members
        # Collapsing keeps a subtotal from being counted twice; the lines inside it
        # are still verified by it, so they are still published.
        collapsed = {lbl for m in members for lbl in m.get("collapsed_lines", [])}
        g2["publish_members"] = members + [m for m in g["members"] if m["label"] in collapsed]
        g2["columns"] = cols
        g2["reconciles"] = bool(any_checked) and all(c["reconciles"] for c in any_checked)
        g2["columns_checked"] = len(any_checked)

        # The reconciliation statements print sub-amounts in one column and their
        # total in the NEXT one — three pension/OPEB deferral lines at 1,173,125 +
        # 486,377 + 126,354 with 1,785,856 printed one column right. Column-by-column
        # checking cannot see that, and it is the statement's own arithmetic, so it
        # is checked explicitly rather than left as an unexplained failure.
        if not g2["reconciles"]:
            for c in range(ncols - 1):
                tot_next = g["total"][c + 1] if c + 1 < len(g["total"]) else None
                tot_here = g["total"][c] if c < len(g["total"]) else None
                parts = [m["values"][c] for m in members
                         if c < len(m["values"]) and m["values"][c] is not None]
                if tot_next is None or tot_here is not None or len(parts) < 2:
                    continue
                if abs(sum(parts) - tot_next) < 1.5:
                    g2["reconciles"] = True
                    g2["offset_total_column"] = {"members_column": c,
                                                 "total_column": c + 1,
                                                 "sum_of_lines": round(sum(parts), 2),
                                                 "printed_total": tot_next}
                    break

        if not g2["reconciles"]:
            # Say WHY, so a withheld group is a recorded decision rather than a
            # silent gap. The balance-sheet case is structural, not an error: a
            # balance sheet prints two page-level grand totals over disjoint sides,
            # and every line inside both is published by its own subtotal group.
            subs = sum(1 for m in members if m["is_subtotal"])
            if subs >= 2 and re.search(r"liabilit|fund balance", g["total_label"], re.I):
                g2["withheld_reason"] = (
                    "balance-sheet grand total: the assets side and the "
                    "liabilities-plus-fund-balances side are both printed as page-level "
                    "totals, so this total's members include the other side's total. "
                    "Every line inside it is published via its own subtotal group.")
            else:
                g2["withheld_reason"] = ("components do not add to the printed total as "
                                         "parsed — withheld rather than published with a caveat")
        checked.append(g2)
    return checked


def column_roles(groups, ncols: int) -> tuple[dict[int, str], str]:
    """Prove the column layout from the statement's own arithmetic (trap 5).

    Three provable layouts occur in these documents, and they are NOT the same —
    assuming one cost a full round of wrong cross-checks:

      * Schedule 1 and the fund schedules print Budget, Actual, Variance
        (positive = favourable), then a comparative prior-year Actual.
      * Exhibit 5 prints Original Budget, Final Budget, Actual, Variance — so the
        variance identity sits at columns 1-2-3, not 0-1-2. Testing only the first
        shape left every Exhibit 5 in the archive with unknown column roles, which
        means nothing downstream could tell which column held the actuals.
      * Capital project schedules print Authorisation, Prior Years, Current Year,
        Total to Date, Variance — where prior + current = total to date.

    Confirmed on at least three rows or the roles stay unknown. A column index
    means nothing on its own and charting the wrong one would be a silent,
    serious error.
    """
    def rows_with(*idx):
        for g in groups:
            v = g["total"]
            if max(idx) < len(v) and all(v[i] is not None for i in idx):
                yield [v[i] for i in idx]

    def variance_hits(b, a, var):
        rows = list(rows_with(b, a, var))
        hits = sum(1 for x, y, z in rows
                   if abs((y - x) - z) < 1.5 or abs((x - y) - z) < 1.5)
        # Three matches is the comfortable bar. Two is accepted only when EVERY
        # testable row matches — Exhibit 5 prints just two totals, and demanding
        # three left every Exhibit 5 in the archive with unknown column roles.
        # Two exact four-column agreements coinciding by chance is implausible.
        return hits if (hits >= 3 or (hits >= 2 and hits == len(rows))) else 0

    # Four columns with the identity at 1-2-3 is the original/final/actual/variance
    # shape. Tested FIRST because that layout also satisfies nothing at 0-1-2, while
    # a budget/actual/variance page has no column 3 to test.
    if ncols >= 4 and variance_hits(1, 2, 3) >= 3:
        return ({0: "original_budget", 1: "final_budget", 2: "actual", 3: "variance"},
                "the variance column equals actual minus final budget (revenues) or final "
                "budget minus actual (expenditures), on at least three totals")

    if ncols >= 3 and variance_hits(0, 1, 2) >= 3:
        roles = {0: "budget", 1: "actual", 2: "variance"}
        if ncols >= 4:
            roles[3] = "prior_year_actual"
        return roles, ("the variance column equals actual minus budget (revenues) or "
                       "budget minus actual (expenditures), on at least three totals")

    if ncols >= 4:
        hits = sum(1 for prior, cur, todate in rows_with(1, 2, 3)
                   if abs((prior + cur) - todate) < 1.5)
        if hits >= 3:
            roles = {0: "project_authorization", 1: "prior_years_actual",
                     2: "current_year_actual", 3: "total_to_date"}
            if ncols >= 5:
                roles[4] = "variance"
            return roles, ("prior years plus current year equals total to date, on at "
                           "least three totals — a capital project schedule layout")

    return {}, "NOT confirmed — roles left unknown rather than assumed"


# The statement's own roll-forward, which proves the lines that sit outside every
# subtotal (trap 4). Each entry: the line, and the lines it must equal.
ROLLFORWARD = re.compile(
    r"^(Revenues\s+over|Excess\s+of\s+revenues|Net\s+change\s+in\s+fund\s+balance|"
    r"Fund\s+balance[,\s]|Change\s+in\s+fund\s+balance)", re.I)
TOTAL_REV = re.compile(r"^Total\s+revenues?$", re.I)
TOTAL_EXP = re.compile(r"^Total\s+expenditures?$", re.I)
NET_CHANGE = re.compile(r"^(Net\s+change\s+in\s+fund\s+balance|Change\s+in\s+fund\s+balance)", re.I)
REV_OVER = re.compile(r"^(Revenues\s+over|Excess\s+of\s+revenues)", re.I)
FB_BEGIN = re.compile(r"^Fund\s+balance,?\s+beginning", re.I)
FB_END = re.compile(r"^Fund\s+balance,?\s+end", re.I)


def rollforward_checks(parsed, ncols: int):
    """Prove the out-of-group roll-forward lines by the statement's own identities.

    Returns (verified_rows, checks). A line is returned only where the identity
    holds in at least one column, and only the columns where it holds are kept —
    a column that does not prove is left as None rather than published unproven.
    """
    def find(pat):
        return next((r for r in parsed if pat.match(r["label"]) and r["has_figures"]), None)

    t_rev, t_exp = find(TOTAL_REV), find(TOTAL_EXP)
    rev_over, net_chg = find(REV_OVER), find(NET_CHANGE)
    fb_b, fb_e = find(FB_BEGIN), find(FB_END)

    out, checks = [], []

    def prove(row, expected_fn, name, inputs):
        if row is None or any(i is None for i in inputs):
            return
        kept = [None] * ncols
        proved = 0
        for c in range(ncols):
            got = row["values"][c] if c < len(row["values"]) else None
            want = expected_fn(c)
            if got is None or want is None:
                continue
            if abs(got - want) < 1.5:
                kept[c] = got
                proved += 1
        checks.append({"line": row["label"], "identity": name,
                       "columns_proved": proved})
        if proved:
            out.append({"label": row["label"], "values": kept, "identity": name})

    def col(row, c):
        if row is None or c >= len(row["values"]):
            return None
        return row["values"][c]

    prove(rev_over, lambda c: (None if col(t_rev, c) is None or col(t_exp, c) is None
                               else col(t_rev, c) - col(t_exp, c)),
          "total revenues minus total expenditures", [t_rev, t_exp])

    prove(fb_e, lambda c: (None if col(fb_b, c) is None or col(net_chg, c) is None
                           else col(fb_b, c) + col(net_chg, c)),
          "fund balance beginning plus net change", [fb_b, net_chg])

    # The beginning balance is proven in reverse by the same identity — useful
    # because a schedule sometimes prints ending and change but not beginning in
    # every column.
    prove(fb_b, lambda c: (None if col(fb_e, c) is None or col(net_chg, c) is None
                           else col(fb_e, c) - col(net_chg, c)),
          "fund balance ending minus net change", [fb_e, net_chg])

    return out, checks
