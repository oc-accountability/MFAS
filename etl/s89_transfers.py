"""Stage 89 — the cross-fund transfer schedule Amy asked for.

Her request, verbatim:

    "When I look at the Town Revenue and Expense, there are Transfers to get to
     the bottom line total. I think we need a schedule that has the Transfer
     columns going across. So the value transferred to General Fund, then to the
     Debt Service, or other Funds. And include any other cross fund transfers."

That is a matrix: source fund down the side, destination fund across the top. It
is buildable because the town names its transfer accounts after their destination
("TRANSFER TO FUND 69 - UTILITY", "TRANSFER TO FUND 61 - STORMWATER"), so each
row already carries both ends of the movement.

Why it matters beyond tidiness: a transfer is the one place where money leaves one
fund's bottom line and appears in another's. Read a single fund in isolation and
transfers look like unexplained leakage. Laid out as a matrix they show which
services subsidise which — which is exactly the kind of thing a resident cannot
otherwise see.

**A limitation stated up front.** This reads the *outgoing* side only, because that
is what the line-item appendix records inside each fund's expenditure section. The
matching incoming side sits in the receiving fund's revenues, which the appendix
does not itemise the same way. So the schedule shows money leaving each fund and
where it was sent; it is not a proof that both sides balance. Where a destination
cannot be identified from the account name it is reported as unidentified rather
than allocated to a guess.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, read_json, write_json  # noqa: E402

# The town's fund numbers, as they appear inside transfer account names.
#
# These names were verified against the source, not assumed, and the first attempt
# got them WRONG. The account labels wrap, with the row's values printed in
# between, so the page reads:
#
#     TRANSFER TO FUND 60 - GENERAL
#     $333,000 $333,000 $363,000 ...
#     CAPITAL IMPROVEMENTS
#
# Reading only the first line gives "FUND 60 - GENERAL", which produced the
# nonsense of the General Fund transferring to itself. Every one of these is a
# CAPITAL fund, and that changes what the schedule means: these transfers are
# operating funds financing their own capital programmes.
FUND_NUMBERS = {
    "60": "General Capital Improvements Fund",
    "61": "Stormwater Capital Improvements Fund",
    "69": "Utility Capital Improvements Fund",
    "78": "Committed Funds (reserves)",
}
# Named destinations that carry no fund number.
NAMED = [
    (re.compile(r"GENERAL\s+CRF", re.I), "General Capital Reserve Fund"),
    (re.compile(r"GENERAL\s+CAPITAL", re.I), "General Capital Projects Fund"),
    (re.compile(r"DEBT\s+SERVICE", re.I), "Debt Service Fund"),
]


def destination(account: str) -> tuple[str, str]:
    """Resolve a transfer account name to (destination fund, how it was resolved)."""
    m = re.search(r"FUND\s+(\d{2,3})", account, re.I)
    if m and m.group(1) in FUND_NUMBERS:
        return FUND_NUMBERS[m.group(1)], f"fund number {m.group(1)} in the account name"
    for rx, name in NAMED:
        if rx.search(account):
            return name, "named in the account"
    return "Unidentified", "the account name does not say where it went"


def main() -> None:
    li = read_json(DATASETS / "lineitems.json")
    C = {c: i for i, c in enumerate(li["columns"])}

    cells: dict[tuple, float] = defaultdict(float)
    detail = []
    unidentified = []
    for r in li["rows"]:
        acct = r[C["account"]]
        if r[C["category"]] != "Interfund Transfers" and "TRANSFER" not in acct.upper():
            continue
        dest, how = destination(acct)
        key = (r[C["fiscal_year"]], r[C["basis"]], r[C["fund"]], dest)
        cells[key] += r[C["value"]]
        rec = {"fiscal_year": r[C["fiscal_year"]], "basis": r[C["basis"]],
               "from_fund": r[C["fund"]], "to_fund": dest, "resolved_by": how,
               "account": acct, "department": r[C["department"]],
               "amount": r[C["value"]], "source_page": r[C["page"]],
               "source_doc": r[C["source_doc"]]}
        detail.append(rec)
        if dest == "Unidentified":
            unidentified.append(rec)

    funds = sorted({k[2] for k in cells})
    dests = sorted({k[3] for k in cells}, key=lambda d: (d == "Unidentified", d))

    # One matrix per (year, basis) — the schedule she described.
    schedules = []
    for fy, basis in sorted({(k[0], k[1]) for k in cells}):
        rows = []
        for f in funds:
            cols = {d: round(cells.get((fy, basis, f, d), 0.0), 2) for d in dests}
            out = sum(cols.values())
            if out:
                rows.append({"from_fund": f, "to": cols, "total_out": round(out, 2)})
        if not rows:
            continue
        received = {d: round(sum(r["to"][d] for r in rows), 2) for d in dests}
        schedules.append({
            "fiscal_year": fy, "basis": basis,
            "destinations": dests,
            "rows": rows,
            "total_received_by_destination": received,
            "total_transferred": round(sum(r["total_out"] for r in rows), 2),
        })

    write_json(DATASETS / "transfer_schedule.json", {
        "generated_by": "etl/s89_transfers.py",
        "requested_by": ("Amy — a schedule with the transfer columns going across, showing the "
                         "value transferred to the General Fund, to Debt Service, and to other "
                         "funds, including any other cross-fund transfers."),
        "reads": "the OUTGOING side only — see the limitation below",
        "limitation": ("The line-item appendix records transfers inside each fund's EXPENDITURE "
                       "section, so this shows money leaving a fund and where it was sent. The "
                       "matching incoming side sits in the receiving fund's revenues, which the "
                       "appendix does not itemise the same way, so this schedule is not a proof "
                       "that both sides balance. Destinations that the account name does not "
                       "identify are reported as Unidentified rather than allocated to a guess."),
        "fund_number_key": FUND_NUMBERS,
        "summary": {
            "transfer_rows": len(detail),
            "schedules": len(schedules),
            "unidentified_destinations": len(unidentified),
            "source_funds": funds,
            "destination_funds": dests,
        },
        "schedules": schedules,
        "unidentified": unidentified[:40],
        "detail": detail,
    })

    print(f"  {len(detail)} transfer rows -> {len(schedules)} schedules "
          f"({len(funds)} source funds, {len(dests)} destinations)")
    cur = next((s for s in schedules if s["fiscal_year"] == 2027 and s["basis"] == "budget"), None)
    if cur:
        print(f"\n  FY2027 budget — transfers out of each fund:")
        for r in cur["rows"]:
            sent = {d: v for d, v in r["to"].items() if v}
            print(f"      {r['from_fund'][:26]:28} total ${r['total_out']:>11,.0f}")
            for d, v in sorted(sent.items(), key=lambda x: -x[1]):
                print(f"          -> {d[:40]:42} ${v:>11,.0f}")
    if unidentified:
        print(f"\n  {len(unidentified)} row(s) whose destination the account name does not give:")
        for u in unidentified[:5]:
            print(f"      FY{u['fiscal_year']} {u['basis']:9} {u['account'][:44]:46} "
                  f"${u['amount']:,.0f}")


if __name__ == "__main__":
    main()
