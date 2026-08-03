/* Unit tests for assets/domain.js — the calculations, without a browser.
 *
 * These exist because the 2026-08-01 audit found the calculator charging TOWN property
 * tax to homes OUTSIDE the town limits, and every one of the 111 tests passed while it
 * was live. The tests validated DATA and never executed the PAGE, so nothing in the
 * suite could see it. These are the missing half.
 *
 * `node --test` only, no dependencies, no install: this repo has no package.json and a
 * civic site that anyone can rebuild should not need a toolchain to check its arithmetic.
 *
 * DISCIPLINE: every assertion here was proven to FAIL against the pre-fix behaviour
 * before it was committed. A test that passes vacuously is worse than no test — the
 * suite already carries one (`for call in re.findall(...): pass`) and it is why the
 * out-of-town rule looked guarded when it was not.
 *
 * The published rates these fixtures use, and the arithmetic checked by hand:
 *   town   51.30 cents per $100  ->  $500,000 / 100 * 0.5130 = $2,565
 *   county 67.58 cents per $100  ->  $500,000 / 100 * 0.6758 = $3,379
 *   both                                                       $5,944
 * If a rate ever changes these numbers move, which is the point — the fixture is the
 * published figure, so the test fails loudly rather than tracking the code.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const D = require('../../assets/domain.js');

const TOWN = 51.3;
const COUNTY = 67.58;
const HOME = 500000;

/* ===================================================== rates and levies ==== */

test('taxOnValue reproduces the published figures exactly', () => {
  assert.equal(Math.round(D.taxOnValue(HOME, TOWN)), 2565);
  assert.equal(Math.round(D.taxOnValue(HOME, COUNTY)), 3379);
  // The town's own worked example, $400,000.
  assert.equal(Math.round(D.taxOnValue(400000, TOWN)), 2052);
});

test('a rate we do not hold yields null, never zero', () => {
  // The whole point. A styled, sourced "$0" is a claim; null is an absence.
  assert.equal(D.taxOnValue(HOME, null), null);
  assert.equal(D.taxOnValue(HOME, undefined), null);
  assert.equal(D.taxOnValue(null, TOWN), null);
  assert.equal(D.taxOnValue(HOME, NaN), null);
});

test('a rate is cents per $100, not a percentage', () => {
  // 51.3 cents is 0.513% of value. Reading it as 51.3% would overstate ~19.5x.
  assert.equal(D.taxOnValue(100000, 51.3), 513);
  assert.notEqual(D.taxOnValue(100000, 51.3), 51300);
});

/* ============================================== the out-of-town rule (C-01) */

test('IN town: both governments are charged, and the total is their sum', () => {
  const b = D.propertyTaxBill({ assessedValue: HOME, location: 'intown',
    townRateCents: TOWN, countyRateCents: COUNTY });
  assert.equal(b.town.applies, true);
  assert.equal(b.county.applies, true);
  assert.equal(b.town.rounded, 2565);
  assert.equal(b.county.rounded, 3379);
  assert.equal(b.total, 5944);
  assert.deepEqual(b.applicable.map(a => a.key), ['town', 'county']);
});

test('OUT of town: the town levy is not charged, and the county levy still is', () => {
  /* The audited defect, in one assertion. A $500,000 home outside the limits was
     shown $5,944 instead of $3,379 — an overstatement of $2,565, about 76%. */
  const b = D.propertyTaxBill({ assessedValue: HOME, location: 'outoftown',
    townRateCents: TOWN, countyRateCents: COUNTY });
  assert.equal(b.town.applies, false);
  assert.equal(b.county.applies, true);
  assert.equal(b.total, 3379);
  assert.notEqual(b.total, 5944);
});

test('OUT of town: no surface can be handed a town row to render', () => {
  /* The bug survived in four places because each surface decided for itself which
     rows to print. `applicable` is the one list; a renderer that walks it cannot
     reintroduce the town row without this failing. */
  const b = D.propertyTaxBill({ assessedValue: HOME, location: 'outoftown',
    townRateCents: TOWN, countyRateCents: COUNTY });
  assert.deepEqual(b.applicable.map(a => a.key), ['county']);
  assert.equal(b.applicable.some(a => a.key === 'town'), false);
});

test('OUT of town, the town share is not-applicable rather than a measured zero', () => {
  /* "$0 to the town" reads as a measurement of something. The spending explorer
     already guards this ("without the guard every department row rendered '$0 of
     yours', which reads as a measurement rather than as not-applicable"); the flag
     is what lets every other surface guard it the same way. */
  const b = D.propertyTaxBill({ assessedValue: HOME, location: 'outoftown',
    townRateCents: TOWN, countyRateCents: COUNTY });
  assert.equal(b.town.applies, false);
  assert.equal(b.town.rateCents, null, 'a rate that does not reach this home is not "their" rate');
});

test('the location answer is honoured for every assessed value, not just the fixture', () => {
  for (const v of [0, 1000, 250000, 400000, 500000, 1e6, 1e9]) {
    const inT = D.propertyTaxBill({ assessedValue: v, location: 'intown',
      townRateCents: TOWN, countyRateCents: COUNTY });
    const out = D.propertyTaxBill({ assessedValue: v, location: 'outoftown',
      townRateCents: TOWN, countyRateCents: COUNTY });
    assert.equal(out.total, Math.round(D.taxOnValue(v, COUNTY)),
      `out of town at $${v} must be the county levy alone`);
    assert.equal(inT.total, out.total + Math.round(D.taxOnValue(v, TOWN)),
      `in town at $${v} must be exactly the county levy plus the town's`);
  }
});

test('an unrecognised location is treated as outside the limits, never inside', () => {
  // Fail safe: a corrupt localStorage value or a hand-edited link must not silently
  // charge someone the town's levy.
  for (const loc of [undefined, null, '', 'INTOWN', 'in-town', 'yes', 'outoftown']) {
    const b = D.propertyTaxBill({ assessedValue: HOME, location: loc,
      townRateCents: TOWN, countyRateCents: COUNTY });
    assert.equal(b.town.applies, false, `location ${JSON.stringify(loc)} must not charge town tax`);
  }
});

/* ================================================ withhold, do not print $0 */

test('a missing county rate withholds the total rather than publishing a false zero', () => {
  /* Out of town with no county rate held, the page computed 0 + 0 and rendered
     "$0 in property tax this year" — fully styled, with sources under it — to a
     household that certainly does pay county tax. The doctrine is withhold, not
     caveat; `complete: false` is how a caller is told to. */
  const b = D.propertyTaxBill({ assessedValue: HOME, location: 'outoftown',
    townRateCents: TOWN, countyRateCents: null });
  assert.equal(b.complete, false);
  assert.equal(b.total, null);
  assert.notEqual(b.total, 0);
  assert.equal(b.monthly, null);
});

test('a missing town rate withholds only when the household is inside the limits', () => {
  const inT = D.propertyTaxBill({ assessedValue: HOME, location: 'intown',
    townRateCents: null, countyRateCents: COUNTY });
  assert.equal(inT.complete, false, 'in town, an unknown town rate makes the bill unknowable');
  assert.equal(inT.total, null);

  const out = D.propertyTaxBill({ assessedValue: HOME, location: 'outoftown',
    townRateCents: null, countyRateCents: COUNTY });
  assert.equal(out.complete, true, 'out of town, the town rate is irrelevant — do not withhold');
  assert.equal(out.total, 3379);
});

/* ============================================================ the rounding rule */

test('the headline is the sum of the rounded rows, not a separately rounded total', () => {
  /* At $104,000 the two differ by a dollar, on a sheet that invites the reader to
     check it with a calculator. The rows must add up to the headline. */
  const b = D.propertyTaxBill({ assessedValue: 104000, location: 'intown',
    townRateCents: TOWN, countyRateCents: COUNTY });
  assert.equal(b.town.rounded + b.county.rounded, b.total);
  assert.equal(b.total, 1237);
  assert.notEqual(b.total, Math.round(D.taxOnValue(104000, TOWN) + D.taxOnValue(104000, COUNTY)));
});

test('rows add up to the headline at every value, in town and out', () => {
  for (const v of [102000, 104000, 105000, 110000, 333333, 500000, 787878]) {
    for (const loc of ['intown', 'outoftown']) {
      const b = D.propertyTaxBill({ assessedValue: v, location: loc,
        townRateCents: TOWN, countyRateCents: COUNTY });
      const shown = b.applicable.reduce((a, x) => a + x.share.rounded, 0);
      assert.equal(shown, b.total, `$${v} ${loc}: the printed rows must sum to the headline`);
    }
  }
});

/* ==================================================== town policy vs the bill */

test('town policy rows are part of the bill only inside the limits', () => {
  /* "One cent on the tax rate costs you $50/yr" and "if the rate rose 10 cents,
     at least +$500/yr" are the TOWN's rate on the reader's home. Out of town they
     cost the household nothing, and the audit named them explicitly. */
  assert.equal(D.townPolicyIsPartOfTheBill('intown'), true);
  assert.equal(D.townPolicyIsPartOfTheBill('outoftown'), false);
  assert.equal(D.townPolicyIsPartOfTheBill(undefined), false);
});

test('one cent on a rate is rate-independent, and N cents scales linearly', () => {
  assert.equal(D.oneCentOnValue(500000), 50);
  assert.equal(D.oneCentOnValue(400000), 40);
  assert.equal(D.centsOnValue(500000, 10), 500);
  assert.equal(D.centsOnValue(500000, 0), 0);
  assert.equal(D.centsOnValue(500000, null), null);
  assert.equal(D.oneCentOnValue(null), null);
});

/* ================================================================= utilities */

test('a block-rate bill charges the fixed block, then per 1,000 above the threshold', () => {
  const set = { threshold_gallons: 2000, block1_charge: 20, block2_per_1000: 5 };
  assert.equal(D.blockBill(set, 0), 20, 'below the threshold is the fixed charge alone');
  assert.equal(D.blockBill(set, 2000), 20, 'at the threshold is still the fixed charge');
  assert.equal(D.blockBill(set, 4000), 30, '2,000 gallons over at $5 per 1,000');
  assert.equal(D.blockBill(set, 9000), 55);
  assert.equal(D.blockBill(null, 4000), null, 'no rate set means no bill, not a zero bill');
});

test('the utility bill is computed at the reader own consumption, inside or outside', () => {
  const utility = {
    rate_sets: {
      water_inside: { current: { threshold_gallons: 2000, block1_charge: 20, block2_per_1000: 4 },
                      recommended: { threshold_gallons: 2000, block1_charge: 22, block2_per_1000: 5 } },
      sewer_inside: { current: { threshold_gallons: 2000, block1_charge: 30, block2_per_1000: 6 },
                      recommended: { threshold_gallons: 2000, block1_charge: 33, block2_per_1000: 7 } },
      water_outside: { current: { threshold_gallons: 2000, block1_charge: 40, block2_per_1000: 8 },
                       recommended: { threshold_gallons: 2000, block1_charge: 44, block2_per_1000: 10 } },
      sewer_outside: { current: { threshold_gallons: 2000, block1_charge: 60, block2_per_1000: 12 },
                       recommended: { threshold_gallons: 2000, block1_charge: 66, block2_per_1000: 14 } },
    },
    stormwater: { residential_current: 108, residential_recommended: 120 },
  };
  const inside = D.utilityBill({ utility, gallons: 4000, location: 'intown' });
  assert.equal(inside.exact, true);
  assert.equal(inside.waterBill, 32);           // 22 + 2 * 5
  assert.equal(inside.sewerBill, 47);           // 33 + 2 * 7
  assert.equal(inside.stormBill, 10);           // 120 / 12
  assert.equal(inside.billTotal, 89);
  assert.equal(inside.annualTotal, 1068);
  // the increase: (32+47+10) - (28+42+9)
  assert.equal(Math.round(inside.total * 100) / 100, 10);

  const outside = D.utilityBill({ utility, gallons: 4000, location: 'outoftown' });
  assert.equal(outside.waterBill, 64);          // 44 + 2 * 10
  assert.ok(outside.billTotal > inside.billTotal,
    'the outside-the-limits schedule is the dearer one — a location mix-up must be visible');
});

test('with no rate schedule the bill falls back to the published increases, and says so', () => {
  /* The town publishes the increase only at 2,000 and 4,000 gallons. The fallback
     must pick the nearer of the two and report which one it used, so the page never
     presents an extrapolation as an exact bill. */
  const seen = [];
  const lookup = m => { seen.push(m); return m.includes('water') ? 3.72 : 5.24; };
  const near2k = D.utilityBill({ utility: null, gallons: 2400, location: 'intown', increaseLookup: lookup });
  assert.equal(near2k.exact, false);
  assert.equal(near2k.gallons, 2000, 'must report the published level it actually used');
  assert.ok(seen.every(m => m.endsWith('_min')), '2,400 gallons is nearer the 2,000 example');

  const near4k = D.utilityBill({ utility: null, gallons: 9000, location: 'outoftown', increaseLookup: lookup });
  assert.equal(near4k.gallons, 4000);
  assert.equal(Math.round(near4k.total * 100) / 100, 8.96);
  assert.equal(near4k.annualTotal, null, 'the fallback knows the increase, not the whole bill');
});

/* ================================================== tax and utilities stay apart */

test('the resident total keeps tax and utility money separate', () => {
  /* Water and sewer are charged to the users of the service, not paid out of property
     tax, and the site says so throughout. Holding them in one object must not become
     adding them together. */
  const bill = D.propertyTaxBill({ assessedValue: HOME, location: 'intown',
    townRateCents: TOWN, countyRateCents: COUNTY });
  const util = { exact: true, billTotal: 100, total: 10 };
  const t = D.residentTotal(bill, util);
  assert.equal(t.propertyTaxAnnual, 5944);
  assert.equal(t.utilityAnnual, 1200);
  assert.equal(t.utilityIncreaseAnnual, 120);
  assert.equal(Object.values(t).includes(5944 + 1200), false,
    'there must be no combined tax-plus-utility figure to quote by accident');
});

test('an incomplete bill stays incomplete through the resident total', () => {
  const bill = D.propertyTaxBill({ assessedValue: HOME, location: 'intown',
    townRateCents: null, countyRateCents: COUNTY });
  const t = D.residentTotal(bill, { exact: true, billTotal: 100, total: 10 });
  assert.equal(t.complete, false);
  assert.equal(t.propertyTaxAnnual, null);
});

/* ====================================================== provenance selection */

const DOCS = [
  { id: 'old', fiscal_year: 2025 },
  { id: 'new', fiscal_year: 2027 },
  { id: 'mid', fiscal_year: 2026 },
];
const FACTS = [
  { metric: 'rate', fiscal_year: 2026, value: 51.3, source_doc: 'old' },
  { metric: 'rate', fiscal_year: 2027, value: 99.9, source_doc: 'old' },
  { metric: 'rate', fiscal_year: 2027, value: 51.3, source_doc: 'new' },
  { metric: 'gap', fiscal_year: 2026, value: -748667, source_doc: 'new' },
  { metric: 'gap', fiscal_year: 2029, value: -2534674, source_doc: 'mid' },
];
const YEAR = (() => { const m = D.docYearIndex(DOCS); return id => m.get(id) || 0; })();

test('the most recently ISSUED document wins, not the first row or the largest value', () => {
  const rows = D.latestByYear(FACTS, 'rate', YEAR);
  assert.deepEqual(rows.map(r => r.fiscal_year), [2026, 2027]);
  assert.equal(rows[1].value, 51.3, 'FY2027 must come from the FY2027 document, not the FY2025 one');
  assert.notEqual(rows[1].value, 99.9);
});

test('factForYear fetches the year the sentence names, not the newest document', () => {
  /* This is a real defect this project already paid for: latestFact() picks by
     document recency and returned FY2026's estimate (-$748,667) to a sentence that
     called it FY2029, understating the town's own projected FY2029 shortfall
     (-$2,534,674) by 3.4x, two paragraphs above a timeline stating the right number. */
  assert.equal(D.latestFact(FACTS, 'gap', YEAR).value, -748667);
  assert.equal(D.factForYear(FACTS, 'gap', 2029, YEAR).value, -2534674);
  assert.equal(D.factForYear(FACTS, 'gap', 2028, YEAR), null,
    'a year we hold nothing for is null, so the sentence is withheld');
});

test('a rate change is measured across two published years, or withheld', () => {
  const rc = D.rateChange(FACTS, 'rate', YEAR);
  assert.equal(rc.prev.fiscal_year, 2026);
  assert.equal(rc.cur.fiscal_year, 2027);
  assert.equal(rc.delta, 0, 'the town rate did not change — measured, not asserted');

  assert.equal(D.rateChange(FACTS, 'gap', YEAR).delta, -1786007);
  assert.equal(D.rateChange([FACTS[0]], 'rate', YEAR), null,
    'one year is not a change — withhold rather than guess');
  assert.equal(D.rateChange(FACTS, 'nosuchmetric', YEAR), null);
});

/* ============================================================ shared limits */

test('the share link emits only what the link parser accepts', () => {
  /* shareUrl() and loadShared() carried the same four bounds written out twice. A
     reader who typed a $5B home value once got a link that silently opened at the
     $400,000 default on the recipient's screen — and attributed that default to the
     sender. One set of constants is what keeps the round trip closed.

     Note on what this does NOT claim: the number input deliberately still accepts
     values below LIMITS.home.min. That asymmetry was examined and left alone —
     reaching it needs a sub-$1,000 assessment the page already renders as absurd,
     and no figure about Hillsborough or Orange County is misstated by it. See
     "Considered and rejected" in docs/2026-08-03_FRONTEND_AUDIT.md. */
  assert.equal(D.LIMITS.home.min, 1000);
  assert.equal(D.LIMITS.home.max, 1e9);
  for (const v of [-1, 0, 500, 999, 1000, 400000, 2e9, 1e12]) {
    const emitted = D.clampHome(v);
    assert.ok(emitted >= D.LIMITS.home.min && emitted <= D.LIMITS.home.max,
      `$${v} must be emitted inside the range the parser accepts, got ${emitted}`);
    assert.equal(D.clampHome(emitted), emitted, 'clamping must be idempotent');
  }
  for (const g of [-5, 0, 4000, 200000, 999999]) {
    const emitted = D.clampGallons(g);
    assert.ok(emitted >= D.LIMITS.gallons.min && emitted <= D.LIMITS.gallons.max);
    assert.equal(D.clampGallons(emitted), emitted);
  }
  assert.equal(D.clampGallons(-5), 0);
  assert.equal(D.clampGallons(999999), 200000);
});

/* ===========================================================================
 * The 2026-08-03 frontend audit — one test per finding it left open.
 *
 * Every assertion below was written against the failure the audit DESCRIBES, then run
 * against the pre-fix behaviour to confirm it fails, then run again after the fix. The
 * findings are traced through code with the data held constant, so several of these
 * simulate the roll-forward that has not happened yet — which is exactly the point:
 * "the next fiscal roll is the real test, and these unit tests are how to run it early".
 * ======================================================================== */

/* -- F-01: town-policy dollars are withheld outside the limits ------------- */

test('F-01 a town-policy cent converts to dollars only inside the limits', () => {
  // 1 cent on a $500,000 home is $50 — a real figure, and a real cost, IN town.
  assert.equal(D.townPolicyDollarsOnThisHome(HOME, 'intown', 1), 50);
  assert.equal(D.townPolicyDollarsOnThisHome(HOME, 'intown', 10), 500);
  /* Out of town every one of these is $0, and the copy around them says "costs you",
     "on your home", "for a home like yours". null is how a caller is told to drop the
     column rather than print $0 under a second-person sentence. */
  assert.equal(D.townPolicyDollarsOnThisHome(HOME, 'outoftown', 1), null);
  assert.equal(D.townPolicyDollarsOnThisHome(HOME, 'outoftown', 10), null);
  // Not simply "falsy": a caller must be able to tell null from a genuine zero.
  assert.notEqual(D.townPolicyDollarsOnThisHome(HOME, 'outoftown', 10), 0);
});

/* -- F-12: the year-over-year row includes every component that moved ------ */

test('F-12 a town rate rise is inside "next year costs you about"', () => {
  /* The failure, verbatim from the audit: town rate 51.3 -> 55.3 (delta 4.0), no county
     change, in-town $500,000 home. The callout announced "The town's rate rises 4 cents"
     while the row above still said "+$122 more" — omitting the $200 it costs. */
  const c = D.annualBillChange({
    assessedValue: HOME, location: 'intown',
    townDeltaCents: 4.0, countyIncreaseCents: null, utilityMonthlyDelta: 10.21,
  });
  assert.equal(c.town, 200);
  assert.equal(Math.round(c.total), Math.round(200 + 10.21 * 12));
});

test('F-12 but a town rate rise is NOT quoted to an out-of-town household', () => {
  // Adding rc.delta unconditionally would be F-01 again with a different label.
  const c = D.annualBillChange({
    assessedValue: HOME, location: 'outoftown',
    townDeltaCents: 4.0, countyIncreaseCents: 3.75, utilityMonthlyDelta: 0,
  });
  assert.equal(c.town, 0);
  assert.equal(Math.round(c.county), 188);   // the county rise reaches everyone
  assert.equal(Math.round(c.total), 188);
});

/* -- F-14: a missing divisor withholds rather than fabricates one ---------- */

test('F-14 no revenue-per-cent means no cents-equivalent, not a fallback', () => {
  // With the figure: $3,567,819 over $240,000 a cent ~= 14.87 cents.
  assert.equal(D.centsEquivalent(3567819, 240000).toFixed(2), '14.87');
  /* Without it, the card used `|| 240000` and published a sourced-looking 14.87 cents
     immediately below its own honest note that the divisor was "n/a". */
  assert.equal(D.centsEquivalent(3567819, null), null);
  assert.equal(D.centsEquivalent(3567819, undefined), null);
  assert.equal(D.centsEquivalent(3567819, 0), null);
});

/* -- F-11: "% of the total" means of the total the page named -------------- */

test('F-11 shares divide by the published total when the parts agree with it', () => {
  const parts = [{ value: 19480000 }, { value: 14000000 }, { value: 2940539 }];
  const s = D.fundShares(parts, 36420539);
  assert.equal(s.agrees, true);
  assert.equal(s.label, 'of the total');
  assert.equal(s.sharePct(19480000).toFixed(1), '53.5');
});

test('F-11 and say so when they do not', () => {
  /* The audit's scenario: publish a $38.00M total against the same $36.42M of fund rows.
     The page rendered "⚠ differs by $1.58M" directly below "53.5% of the total" — and
     against the total it had just named, that share is 51.3%. */
  const parts = [{ value: 19480000 }, { value: 14000000 }, { value: 2940539 }];
  const s = D.fundShares(parts, 38000000);
  assert.equal(s.agrees, false);
  /* The DEFECT was the label, not the arithmetic. 53.5% is the General Fund's share of
     the three funds and is correct; calling it "of the total" was the false part, because
     against the $38.00M the page had just named it is 51.3%. So the number is unchanged
     and the claim it makes is corrected — which also keeps the legend consistent with the
     bar beside it. */
  assert.equal(s.label, 'of the three funds');
  assert.equal(s.sharePct(19480000).toFixed(1), '53.5');
  assert.notEqual(s.label, 'of the total');
  // A stacked bar still has to FILL, so widths always divide by the sum.
  assert.equal(s.widthPct(19480000).toFixed(1), '53.5');
  assert.equal(Math.round(s.difference), 1579461);
  // And against the total the page named, the share really is the other number —
  // which is why claiming "of the total" was wrong.
  assert.equal((19480000 / 38000000 * 100).toFixed(1), '51.3');
});

/* -- F-15: the variance sentence branches on the sign --------------------- */

test('F-15 an overspend is not described as spending less than planned', () => {
  const under = D.budgetVariance(16761617, 14100000);
  assert.equal(under.direction, 'under');
  /* The failure: actual $17,000,000 against a final budget of $16,761,617 produced
     "−1.4% less than planned" — a double negative most readers take as an underspend,
     in a panel titled "Did they spend what they said they would?" about a named board. */
  const over = D.budgetVariance(16761617, 17000000);
  assert.equal(over.direction, 'over');
  assert.equal(over.pct.toFixed(1), '1.4');
  assert.ok(over.pct > 0, 'the magnitude is unsigned; the direction carries the sign');
  assert.equal(D.budgetVariance(16761617, 16761617).direction, 'exact');
  assert.equal(D.budgetVariance(0, 100), null);
  assert.equal(D.budgetVariance(null, 100), null);
});

/* -- F-08: the capital split checks its own shape -------------------------- */

const CIP = (cols) => ([{ expenditures_by_account: [{ amounts: cols }] }]);

test('F-08 the split holds while the first column is the current project budget', () => {
  const p = CIP([14500000, 1000000, 1000000, 1000000, 1000000, 1000000, 1000000, 1000000]);
  const s = D.splitProjectCost(p, 21500000, 8);
  assert.equal(s.shapeOk, true);
  assert.equal(s.already, 14500000);
  assert.equal(s.window, 7000000);
  assert.equal(s.reconciles, true);
});

test('F-08 and refuses to describe a plan whose columns changed', () => {
  /* The town drops the standalone current-budget column, leaving seven entries.
     amounts[0] is now the first PLAN year, and the page went on reporting it as money
     "already in current project budgets" — the same $14.5M-class misattribution the
     split was written to correct, arithmetically self-consistent and silent. */
  const p = CIP([1000000, 1000000, 1000000, 1000000, 1000000, 1000000, 1000000]);
  const s = D.splitProjectCost(p, 7000000, 8);
  assert.equal(s.shapeOk, false, 'seven columns must not pass an eight-column split');
  assert.equal(s.columns, 7);
});

test('F-08 and notices when the parts stop summing to the published total', () => {
  const p = CIP([14500000, 1000000, 1000000, 1000000, 1000000, 1000000, 1000000, 1000000]);
  assert.equal(D.splitProjectCost(p, 30000000, 8).reconciles, false);
});

/* -- F-19: an artefact that leaves the page names the rates that apply ----- */

test('F-19 the copied block states the rates this household actually pays', () => {
  const inTown = D.applicableRates({ location: 'intown',
    townRateCents: TOWN, countyRateCents: COUNTY });
  assert.deepEqual(inTown.rates.map(r => r.key), ['town', 'county']);
  /* In town the block said "Tax rate: 51.3 cents", which does not reconcile with the
     total three lines above it — the household is charged 51.3 + 67.58. */
  assert.equal(inTown.combined.toFixed(2), '118.88');

  const out = D.applicableRates({ location: 'outoftown',
    townRateCents: TOWN, countyRateCents: COUNTY });
  assert.deepEqual(out.rates.map(r => r.key), ['county']);
  assert.equal(out.combined, COUNTY);
  assert.ok(!out.rates.some(r => r.key === 'town'),
    'the town rate must not travel off the page with an out-of-town household');
});

/* -- F-18: the sentence names what the number contains -------------------- */

test('F-18 the exact bill really does include stormwater', () => {
  const u = D.utilityBill({
    utility: {
      rate_sets: {
        water_inside: { current: { block1_charge: 20, block2_per_1000: 5, threshold_gallons: 2000, fiscal_year: 2026 },
                        recommended: { block1_charge: 22, block2_per_1000: 5.5, threshold_gallons: 2000, fiscal_year: 2027 } },
        sewer_inside: { current: { block1_charge: 30, block2_per_1000: 8, threshold_gallons: 2000, fiscal_year: 2026 },
                        recommended: { block1_charge: 33, block2_per_1000: 8.8, threshold_gallons: 2000, fiscal_year: 2027 } },
      },
      stormwater: { residential_current: 105, residential_recommended: 120 },
    },
    gallons: 4000, location: 'intown',
  });
  assert.deepEqual(u.components, ['water', 'sewer', 'stormwater']);
  assert.equal(D.componentPhrase(u.components), 'water, sewer and the stormwater fee');
  // And the years come from the data, not from a literal in the copy (F-22).
  assert.equal(u.fiscalYear, 2027);
  assert.equal(u.priorFiscalYear, 2026);
});

test('F-18 the FALLBACK does not, and says so', () => {
  /* The fallback total is water + sewer with no stormwater component at all, while four
     surfaces each carried "water, sewer and the stormwater fee together add about $X a
     month" about this very number. Exact path $10.21; this path $8.96; the difference is
     exactly the omitted fee. */
  const u = D.utilityBill({
    utility: null, gallons: 4000, location: 'intown',
    increaseLookup: m => (m.includes('water') ? 3.72 : m.includes('sewer') ? 5.24 : null),
  });
  assert.equal(u.exact, false);
  assert.deepEqual(u.components, ['water', 'sewer']);
  assert.ok(!D.componentPhrase(u.components).includes('stormwater'),
    'the sentence must not name a charge the arithmetic left out');
  assert.equal(u.total.toFixed(2), '8.96');
});

test('F-18 and with neither increase published it withholds instead of printing $0', () => {
  const u = D.utilityBill({ utility: null, gallons: 4000, location: 'intown',
    increaseLookup: () => null });
  assert.equal(u.known, false);
  assert.equal(u.total, null, 'a sourced-looking $0 is a claim; null is an absence');
});
