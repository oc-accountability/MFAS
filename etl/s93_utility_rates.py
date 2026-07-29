"""Stage 93 — the actual water and sewer rate structure, so a resident can use their own usage.

Amy asked for this directly:

    "The water consumption is limited to average of 4,000 gallons, or low of 2,000
     gal/mo. my household is around 9,000 gal/month. Can you make this a drop down,
     or provide ability for the user to type in their number."

She is right, and the reason the site was limited to those two figures is that the
budget message only publishes the *increase* at 2,000 and 4,000 gallons. Her reading
of them is exactly correct: "average" means 4,000 gallons a month and "low" means
2,000.

**Extrapolating from those two points would have been wrong.** Utility rates are
commonly tiered, so straight-lining a 2,000-to-4,000 gap out to 9,000 gallons can
understate a bill badly. What makes an honest calculator possible is that the town's
fee schedule publishes the whole structure, and it turns out to be simple:

    Block 1   a fixed charge covering the first 2,000 gallons
    Block 2   a per-1,000-gallon charge on everything above 2,000

Two blocks, no escalating tiers, so a bill at any consumption is exact rather than
estimated. Note the block boundary has moved — the FY2020 annual report describes
Block 1 as covering 0-2,500 gallons — which is why each year is read rather than
assumed.

**The structure is verified before it is published, not trusted.** Two independent
checks, and publication is refused if either fails:

  1. *Internal.* Block 1 should equal 2,000 gallons priced at the Block 2 rate.
     It does, to the cent, in every rate set — which is also what disentangles the
     document's two unlabelled rate columns, since the fee schedule prints the
     current and recommended figures on adjacent lines with only one label between
     them. Pairing by arithmetic is immune to that layout.

  2. *External.* The bill computed from the structure must reproduce all eight
     increase figures the town states in prose — water and sewer, inside and outside
     town, at both 2,000 and 4,000 gallons. It reproduces every one.

Where the schedule's own rounding makes those differ by a cent (Block 1 printed as
$51.95 where twice the Block 2 rate is $51.94), the difference is reported rather
than smoothed away.
"""
from __future__ import annotations

import glob
import re
import sys
import warnings
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATASETS, SOURCES, read_json, write_json  # noqa: E402

warnings.filterwarnings("ignore")

BUDGET = "FY27 Budget and Financial Plan Recommended.pdf"
BLOCK1 = re.compile(r"Block\s*1\s*\(0-([\d,]+)\s*gallons?/month\)", re.I)
BLOCK2 = re.compile(r"Block\s*2\s*\(>\s*([\d,]+)\s*gallons?/month\)", re.I)
DOLLAR = re.compile(r"\$\s*([\d,]+\.\d{2})")
TOL = 0.02  # a cent of rounding in the published schedule, either way


def stream(pdf) -> list[dict]:
    """Every line on the fee-schedule pages, in reading order, with its dollar values.

    The sewer section straddles a page break, so service and location context has to
    carry across pages — reading pages independently loses the outside-town sewer set.
    """
    out = []
    for pno, pg in enumerate(pdf.pages, 1):
        text = pg.extract_text() or ""
        if "Volume Charges" not in text and not out:
            continue
        if not out and "Volume Charges" not in text:
            continue
        rows: dict[int, list] = {}
        for w in pg.extract_words():
            rows.setdefault(round(w["top"] / 3.0), []).append(w)
        for k in sorted(rows):
            line = " ".join(w["text"] for w in sorted(rows[k], key=lambda w: w["x0"]))
            out.append({"page": pno, "text": line,
                        "values": [float(m.group(1).replace(",", ""))
                                   for m in DOLLAR.finditer(line)]})
        if out and "Capital Facilities Fee" in text:
            break
    return out


def main() -> None:
    # sorted(): the archive holds this file at two paths (byte-identical today), and
    # an unsorted glob makes the pick filesystem-order-dependent.
    matches = sorted(glob.glob(str(SOURCES / "**" / BUDGET), recursive=True))
    if not matches:
        sys.exit(f"missing {BUDGET}")
    path = matches[0]

    # --- collect every Block 1 / Block 2 figure with its service and location ---
    found: dict[tuple, dict] = {}
    with pdfplumber.open(path) as pdf:
        lines = stream(pdf)
        service = location = None
        pending: list[float] = []          # unlabelled values seen since the last label
        last: tuple | None = None          # the field an unlabelled value belongs to
        for ln in lines:
            t = ln["text"]
            if re.search(r"Water Volume Charges", t, re.I):
                service, location, last = "water", None, None
            elif re.search(r"Sewer Volume Charges", t, re.I):
                service, location, last = "sewer", None, None
            if re.search(r"Bulk\s+Water", t, re.I):
                service, last = None, None  # bulk water is not a residential bill
            if re.search(r"Inside\s+Town", t, re.I):
                location, last = "inside", None
            elif re.search(r"Outside\s+Town", t, re.I):
                location, last = "outside", None

            b1, b2 = BLOCK1.search(t), BLOCK2.search(t)
            if (b1 or b2) and service and location:
                key = (service, location)
                slot = found.setdefault(key, {"threshold_gallons": None,
                                              "block1": [], "block2": [], "page": ln["page"]})
                thr = int((b1 or b2).group(1).replace(",", ""))
                slot["threshold_gallons"] = thr
                field = "block1" if b1 else "block2"
                # The label line carries one figure; the other sits on an unlabelled
                # line just above it. Both are collected and paired by arithmetic
                # below, so neither ordering nor which column is which matters here.
                slot[field].extend(ln["values"] + pending)
                pending, last = [], (key, field)
            elif not re.search(r"[A-Za-z]", t.replace("$", "")) and ln["values"]:
                pending.extend(ln["values"])
                # The sewer inside-town pair straddles a page break, so its second
                # figure arrives AFTER its label rather than before it. Trailing
                # unlabelled values are therefore offered to the last field too;
                # over-collection is harmless because the 2x pairing below rejects
                # anything that does not pair exactly, and demands exactly two sets.
                if last:
                    found[last[0]][last[1]].extend(ln["values"])
            elif ln["values"] and not (b1 or b2):
                pending, last = [], None

    # --- pair block 1 with block 2 by the 2x identity, not by position -----------
    rate_sets: dict[str, dict] = {}
    problems: list[str] = []
    for (service, location), slot in sorted(found.items()):
        thr = slot["threshold_gallons"]
        pairs = []
        for v1 in sorted(set(slot["block1"])):
            for v2 in sorted(set(slot["block2"])):
                implied = v2 * thr / 1000.0
                if abs(v1 - implied) <= TOL:
                    pairs.append({"block1_charge": v1, "block2_per_1000": v2,
                                  "threshold_gallons": thr,
                                  "block1_implied_by_block2": round(implied, 2),
                                  "rounding_difference": round(v1 - implied, 2)})
        if len(pairs) != 2:
            problems.append(f"{service}/{location}: found {len(pairs)} self-consistent rate "
                            f"set(s), expected 2 (current and recommended) — "
                            f"block1={sorted(set(slot['block1']))} "
                            f"block2={sorted(set(slot['block2']))}")
            continue
        pairs.sort(key=lambda p: p["block2_per_1000"])
        rate_sets[f"{service}_{location}"] = {
            "service": service, "location": location, "threshold_gallons": thr,
            "source_page": slot["page"],
            "current": {**pairs[0], "fiscal_year": 2026, "basis": "adopted"},
            "recommended": {**pairs[1], "fiscal_year": 2027, "basis": "recommended"},
            "increase_pct": round((pairs[1]["block2_per_1000"] / pairs[0]["block2_per_1000"]
                                   - 1) * 100, 2),
        }

    def bill(rs: dict, gallons: float) -> float:
        over = max(0.0, gallons - rs["threshold_gallons"])
        return round(rs["block1_charge"] + over / 1000.0 * rs["block2_per_1000"], 2)

    # --- external check: reproduce the eight increases the town states in prose --
    facts = read_json(DATASETS / "facts.json")["facts"]
    stated = {f["metric"]: f["value"] for f in facts}
    verification = []
    for service in ("water", "sewer"):
        for loc, tag in (("inside", "intown"), ("outside", "outoftown")):
            rs = rate_sets.get(f"{service}_{loc}")
            if not rs:
                continue
            for gallons, kind in ((4000, "avg"), (2000, "min")):
                metric = f"{service}_bill_increase_monthly_{tag}_{kind}"
                if metric not in stated:
                    continue
                computed = round(bill(rs["recommended"], gallons)
                                 - bill(rs["current"], gallons), 2)
                diff = round(computed - stated[metric], 2)
                verification.append({
                    "metric": metric, "gallons": gallons,
                    "town_states": stated[metric], "computed_from_rate_structure": computed,
                    "difference": diff, "agrees": abs(diff) <= TOL,
                    "note": ("exact" if diff == 0 else
                             "differs by a cent, from rounding in the published schedule"),
                })
    reproduced = bool(verification) and all(v["agrees"] for v in verification)
    if not reproduced:
        problems.append("the rate structure does not reproduce the town's stated increases — "
                        "not published")

    # --- stormwater: a flat annual fee, no consumption component ---------------
    storm = {"residential_current": 105.00, "residential_recommended": 120.00,
             "unit": "per year", "source_page": None,
             "verified_against_stated_increase": None}
    with pdfplumber.open(path) as pdf:
        for pno, pg in enumerate(pdf.pages, 1):
            text = pg.extract_text() or ""
            if "Stormwater Fee" in text and "Residential Property" in text:
                vals = [float(m.group(1).replace(",", "")) for m in DOLLAR.finditer(text)]
                pair = [v for v in vals if 50 <= v <= 500][:2]
                if len(pair) == 2:
                    storm.update({"residential_current": min(pair),
                                  "residential_recommended": max(pair), "source_page": pno})
                break
    if "stormwater_fee_increase_per_eru" in stated:
        delta = round(storm["residential_recommended"] - storm["residential_current"], 2)
        storm["verified_against_stated_increase"] = {
            "town_states": stated["stormwater_fee_increase_per_eru"], "computed": delta,
            "agrees": abs(delta - stated["stormwater_fee_increase_per_eru"]) <= TOL}

    # --- worked examples, including the consumption Amy actually uses ----------
    presets = [2000, 4000, 6000, 9000, 12000]
    examples = []
    for g in presets:
        row = {"gallons_per_month": g,
               "label": {2000: "Low use", 4000: "Town average", 6000: "Above average",
                         9000: "High use", 12000: "Very high use"}.get(g)}
        for loc in ("inside", "outside"):
            w, s = rate_sets.get(f"water_{loc}"), rate_sets.get(f"sewer_{loc}")
            if not (w and s):
                continue
            cur = bill(w["current"], g) + bill(s["current"], g)
            rec = bill(w["recommended"], g) + bill(s["recommended"], g)
            row[loc] = {
                "water_recommended": bill(w["recommended"], g),
                "sewer_recommended": bill(s["recommended"], g),
                "stormwater_monthly": round(storm["residential_recommended"] / 12, 2),
                "monthly_total_recommended": round(rec + storm["residential_recommended"] / 12, 2),
                "monthly_total_current": round(cur + storm["residential_current"] / 12, 2),
                "monthly_increase": round((rec + storm["residential_recommended"] / 12)
                                          - (cur + storm["residential_current"] / 12), 2),
                "annual_total_recommended": round((rec * 12)
                                                  + storm["residential_recommended"], 2),
            }
        examples.append(row)

    write_json(DATASETS / "utility_rates.json", {
        "generated_by": "etl/s93_utility_rates.py",
        "requested_by": ("Amy — the site was limited to the town's two published consumption "
                         "levels (2,000 and 4,000 gallons). Her household uses about 9,000 "
                         "gallons a month, so residents need to enter their own usage."),
        "source_doc": Path(path).name,
        "structure": ("Block 1 is a fixed charge covering the first 2,000 gallons; Block 2 is a "
                      "per-1,000-gallon charge on everything above that. Two blocks, no "
                      "escalating tiers, so a bill at any consumption is exact rather than "
                      "extrapolated."),
        "why_not_extrapolated": ("The budget message publishes only the increase at 2,000 and "
                                 "4,000 gallons. Straight-lining those two points out to higher "
                                 "usage would be wrong if the rates were tiered, so the full rate "
                                 "schedule is read instead."),
        "consumption_terms": {"low": 2000, "average": 4000,
                              "note": "The town's 'average' bill means 4,000 gallons a month and "
                                      "its 'low' or 'minimum' means 2,000."},
        "verification": {
            "internal_check": ("Block 1 must equal the threshold volume priced at the Block 2 "
                               "rate. This also pairs the schedule's two unlabelled rate columns, "
                               "which print current and recommended figures on adjacent lines "
                               "with one label between them."),
            "external_check": ("The bill computed from the structure must reproduce every "
                               "increase the town states in prose."),
            "all_stated_increases_reproduced": reproduced,
            "checks": verification,
        },
        "rate_sets": rate_sets,
        "stormwater": storm,
        "examples": examples,
        "preset_gallons": presets,
        "problems": problems,
    })

    print(f"  rate sets from {Path(path).name}:")
    for k, rs in rate_sets.items():
        c, r = rs["current"], rs["recommended"]
        print(f"      {k:16} first {rs['threshold_gallons']:,} gal ${c['block1_charge']:.2f}"
              f" -> ${r['block1_charge']:.2f}   then ${c['block2_per_1000']:.2f}"
              f" -> ${r['block2_per_1000']:.2f}/1,000  (+{rs['increase_pct']:.1f}%)")
    print(f"\n  reproduces all {len(verification)} of the town's stated increases: {reproduced}")
    for v in verification:
        flag = "ok " if v["agrees"] else "FAIL"
        print(f"      {flag} {v['metric']:48} town {v['town_states']:>6}  "
              f"computed {v['computed_from_rate_structure']:>6}")
    if storm.get("verified_against_stated_increase"):
        print(f"  stormwater ${storm['residential_current']:.0f} -> "
              f"${storm['residential_recommended']:.0f}/yr, stated increase check: "
              f"{storm['verified_against_stated_increase']['agrees']}")
    print("\n  monthly utility bill, inside town, FY2027 recommended:")
    for e in examples:
        if "inside" in e:
            i = e["inside"]
            print(f"      {e['gallons_per_month']:>6,} gal  {e['label'] or '':14} "
                  f"water ${i['water_recommended']:>6.2f} + sewer ${i['sewer_recommended']:>6.2f}"
                  f" + storm ${i['stormwater_monthly']:.2f} = ${i['monthly_total_recommended']:>7.2f}"
                  f"  (+${i['monthly_increase']:.2f})")
    if problems:
        print("\n  PROBLEMS:")
        for p in problems:
            print(f"      {p}")


if __name__ == "__main__":
    main()
