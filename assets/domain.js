/* domain.js — the calculations, with nothing else attached.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * On 2026-08-01 an external audit found the calculator charging TOWN property tax to
 * homes OUTSIDE the town limits: a $500,000 home was shown $5,944 instead of $3,379, a
 * 76% overstatement, on the site's primary trust surface. All 111 tests passed while it
 * was live, because the tests validate DATA and never execute the PAGE.
 *
 * The bug survived in four places at once — the hero readout, the printable takeaway,
 * the spending explorer and the "what it pays for" sentence — because each surface kept
 * its OWN copy of the calculation. That multiplicity was the real defect. One of them
 * was fixed and the other three were not, and nothing could tell.
 *
 * So: every figure this site publishes is computed HERE, once, by a function that takes
 * its inputs as arguments and touches nothing else. No DOM, no `state`, no localStorage,
 * no fetch, no globals. That is what makes it testable without a browser — see
 * tests/js/. A renderer's job is to format what this file returns, never to work it out.
 *
 * THREE RULES THIS FILE ENFORCES, because the site's promise depends on them:
 *
 *   1. "does not apply" is not "zero", and neither is "unknown".
 *      A household outside the limits owes the town nothing — that is `applies: false`,
 *      not `$0`. A rate we do not hold is `null` and the caller must WITHHOLD, not print
 *      a styled, sourced "$0" that reads as a measurement. The site's own doctrine is
 *      withhold rather than caveat; `complete: false` is how a caller is told to.
 *
 *   2. A headline is the sum of the rounded rows beneath it, never a separately rounded
 *      exact total. The two differ by $1 at many home values, on a sheet that invites the
 *      reader to check it with a calculator.
 *
 *   3. One quantity, one implementation. If you find yourself writing `homeValue / 100 *
 *      (rate / 100)` in a renderer, that is the defect this file was made to remove.
 *
 * Loads twice over: as a plain <script> in the browser (no build step — this site is
 * static by design) and as a CommonJS module under `node --test`. Same bytes both ways,
 * so the tested code is the shipped code.
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.MFAS = api;
})(typeof self !== 'undefined' ? self : globalThis, function () {
  'use strict';

  /* ------------------------------------------------------------------ limits */
  /* ONE set of bounds for the share round trip. shareUrl() and loadShared() carried
     the same four numbers written out twice, and "emit only what the parser accepts"
     is a rule that a second copy can silently break: a reader who typed a $5B home
     value once got a link that opened at the $400,000 default on the recipient's
     screen, and attributed that default to the sender. They cannot drift apart now
     because there is only one of them.

     The number input deliberately still accepts values below `home.min` — see the
     "Considered and rejected" table in docs/2026-08-03_FRONTEND_AUDIT.md. Reaching
     that gap needs a sub-$1,000 assessment the page already renders as absurd, and
     it misstates nothing about Hillsborough or Orange County, so the input's
     behaviour was left alone rather than changed under cover of a refactor. */
  const LIMITS = {
    home: { min: 1000, max: 1e9 },
    gallons: { min: 0, max: 200000 },
  };

  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const isNum = v => typeof v === 'number' && Number.isFinite(v);

  /* ------------------------------------------------------------ property tax */

  /** Dollars a year, from an assessed value and a rate in CENTS PER $100.
   *
   * A tax rate is not a percentage. 51.3 cents per $100 is 0.513% — labelling it
   * "51.3%" would overstate the bill ~19.5x. Returns null rather than 0 when the
   * rate is unknown, because a caller must be able to tell those apart.
   */
  function taxOnValue(assessedValue, rateCents) {
    if (!isNum(assessedValue) || !isNum(rateCents)) return null;
    return assessedValue / 100 * (rateCents / 100);
  }

  /** What one cent of ANY rate costs this home in a year. Rate-independent. */
  function oneCentOnValue(assessedValue) {
    return isNum(assessedValue) ? assessedValue / 100 * 0.01 : null;
  }

  /** What N cents of rate costs this home in a year. */
  function centsOnValue(assessedValue, cents) {
    const one = oneCentOnValue(assessedValue);
    return one == null || !isNum(cents) ? null : one * cents;
  }

  /** Does the town's own levy reach this household at all? */
  const isInTown = location => location === 'intown';

  /**
   * The whole property-tax bill, with each government's share kept separate and
   * each one saying whether it APPLIES before it says what it costs.
   *
   * Orange County's own explainer is the authority for the rule, in its words:
   * "all taxpayers in the county will pay the Orange County tax due. Taxpayers who
   * live within the municipal boundaries of Chapel Hill, Carrboro, Hillsborough, and
   * Mebane will ALSO have a tax due to one of those municipalities."
   * (Understanding Your Property Tax Bill, Orange County, 1 Aug 2025.)
   *
   * So: the county share applies to everyone; the town share applies only inside the
   * limits. `total` is the sum of the ROUNDED applicable rows (rule 2 above), and is
   * null — not zero — if any applicable rate is missing, so a caller withholds.
   */
  function propertyTaxBill(o) {
    const opts = o || {};
    const assessedValue = opts.assessedValue;
    const inTown = isInTown(opts.location);

    const mk = (applies, rateCents) => {
      const due = applies ? taxOnValue(assessedValue, rateCents) : 0;
      return {
        applies: applies,
        rateCents: applies ? (isNum(rateCents) ? rateCents : null) : null,
        due: due,
        rounded: due == null ? null : Math.round(due),
        known: !applies || due != null,
      };
    };

    const town = mk(inTown, opts.townRateCents);
    const county = mk(true, opts.countyRateCents);

    const complete = town.known && county.known;
    const total = complete ? town.rounded + county.rounded : null;

    return {
      town: town,
      county: county,
      total: total,
      monthly: total == null ? null : total / 12,
      complete: complete,
      /* The components a caller should actually print. Out of town this is the county
         alone — which is what stops a "$0 to the town" row rendering as a measurement
         of something rather than as not-applicable. */
      applicable: [
        town.applies ? { key: 'town', share: town } : null,
        county.applies ? { key: 'county', share: county } : null,
      ].filter(Boolean),
    };
  }

  /**
   * Is a TOWN POLICY comparison a component of this household's bill?
   *
   * "One cent on the tax rate costs you", the FY-scenario rows and the shortfall
   * arithmetic are all the TOWN's rate applied to the reader's home. Inside the
   * limits they are a live prospect. Outside them they cost the household nothing,
   * and the 2026-08-01 audit named exactly this: those rows were "visible to an
   * out-of-town household without explaining that those are hypothetical town policy
   * comparisons rather than components of that household's property-tax bill".
   *
   * The figure itself is arithmetically right either way, so this does not gate the
   * MATHS — it gates the FRAMING, and every surface asks the same question here
   * rather than each deciding for itself.
   */
  const townPolicyIsPartOfTheBill = location => isInTown(location);

  /* ------------------------------------------------------------- utility bill */

  /** One block-rate bill: a fixed charge for the first N gallons, then a rate per 1,000. */
  function blockBill(set, gallons) {
    if (!set || !isNum(gallons)) return null;
    const over = Math.max(0, gallons - set.threshold_gallons);
    return set.block1_charge + (over / 1000) * set.block2_per_1000;
  }

  /**
   * The whole monthly utility bill at the reader's own consumption.
   *
   * The town publishes the *increase* only at 2,000 and 4,000 gallons, which is why
   * this page once offered just those two. Extrapolating between them would have been
   * unsafe if the rates were tiered — but the fee schedule shows two blocks and nothing
   * more, so any consumption computes exactly. Falls back to the published increases
   * when the rate structure is unavailable, so the page degrades rather than breaking.
   *
   * `increaseLookup` is injected rather than read from a global: it is the only thing
   * this function needs from the fact table, and passing it keeps the function pure.
   */
  function utilityBill(o) {
    const opts = o || {};
    const u = opts.utility;
    const g = opts.gallons;
    const location = opts.location;
    const loc = isInTown(location) ? 'inside' : 'outside';
    const lookup = opts.increaseLookup || (() => null);

    if (u && u.rate_sets) {
      const w = u.rate_sets['water_' + loc], s = u.rate_sets['sewer_' + loc];
      if (w && s) {
        const storm = u.stormwater || {};
        const sNow = (storm.residential_recommended || 0) / 12;
        const sWas = (storm.residential_current || 0) / 12;
        const wNow = blockBill(w.recommended, g), wWas = blockBill(w.current, g);
        const sewNow = blockBill(s.recommended, g), sewWas = blockBill(s.current, g);
        const billTotal = wNow + sewNow + sNow;
        return {
          exact: true, gallons: g,
          waterBill: wNow, sewerBill: sewNow, stormBill: sNow,
          billTotal: billTotal,
          annualTotal: billTotal * 12,
          water: wNow - wWas, sewer: sewNow - sewWas, storm: sNow - sWas,
          total: billTotal - (wWas + sewWas + sWas),
        };
      }
    }
    // Published increases are given at 2,000 and 4,000 gallons only; pick the nearer.
    const level = Math.abs(g - 2000) < Math.abs(g - 4000) ? 'min' : 'avg';
    const w = lookup('water_bill_increase_monthly_' + location + '_' + level);
    const s = lookup('sewer_bill_increase_monthly_' + location + '_' + level);
    return {
      exact: false, gallons: level === 'min' ? 2000 : 4000,
      water: w, sewer: s, total: (w || 0) + (s || 0),
      annualTotal: null,
    };
  }

  /* ---------------------------------------------------------- resident total */

  /**
   * The household's whole annual picture, in one shape.
   *
   * The snapshot card and the printable takeaway each assembled this themselves and
   * could therefore disagree. Tax and utilities are deliberately kept APART and never
   * summed: water and sewer are charged to the users of the service, not paid out of
   * property tax, and the site says so throughout. Putting them in one object is not
   * the same as adding them together.
   */
  function residentTotal(bill, util) {
    const u = util || {};
    return {
      propertyTaxAnnual: bill.total,
      propertyTaxMonthly: bill.monthly,
      complete: bill.complete,
      utilityMonthly: u.exact ? u.billTotal : null,
      utilityAnnual: u.exact ? u.billTotal * 12 : null,
      utilityIncreaseMonthly: u.total == null ? null : u.total,
      utilityIncreaseAnnual: u.total == null ? null : u.total * 12,
    };
  }

  /* ----------------------------------------------------- provenance selection */
  /* Which reading of a metric to publish when several documents report it. The rule
     is always the same — the most recently ISSUED document wins, not the highest
     value, not the first one found — and it lives here so the charts, the hero, the
     takeaway and the copied text cannot each answer it differently. */

  /** id -> fiscal_year, for ranking readings by how recent their document is. */
  function docYearIndex(documents) {
    const m = new Map();
    for (const d of documents || []) m.set(d.id, d.fiscal_year || 0);
    return m;
  }

  const factsFor = (facts, metric) => (facts || []).filter(f => f.metric === metric);

  /** One reading per fiscal year — the most recently issued — oldest year first. */
  function latestByYear(facts, metric, docYear) {
    const year = docYear || (() => 0);
    const by = new Map();
    for (const f of factsFor(facts, metric)) {
      if (f.fiscal_year == null) continue;
      const prev = by.get(f.fiscal_year);
      if (!prev || year(f.source_doc) > year(prev.source_doc)) by.set(f.fiscal_year, f);
    }
    return [...by.values()].sort((a, b) => a.fiscal_year - b.fiscal_year);
  }

  /** The single reading to publish for a metric: the most recently issued document. */
  function latestFact(facts, metric, docYear) {
    const year = docYear || (() => 0);
    const rows = factsFor(facts, metric);
    if (!rows.length) return null;
    return rows.reduce((a, b) => (year(b.source_doc) > year(a.source_doc) ? b : a));
  }

  /** The reading for one named year. Use this, never latestFact(), when the sentence
   *  around it names a year: latestFact() picks by document recency and has already
   *  returned FY2026's estimate to a sentence that then called it FY2029. */
  function factForYear(facts, metric, fiscalYear, docYear) {
    return latestByYear(facts, metric, docYear)
      .find(f => f.fiscal_year === fiscalYear) || null;
  }

  /**
   * Year-over-year movement in a rate, MEASURED rather than asserted.
   *
   * Returns null when two years are not both published, so the claim is withheld
   * instead of guessed. Three sentences on this page went stale the last time a
   * "did not change" was asserted from a single year's data.
   */
  function rateChange(facts, metric, docYear) {
    const seq = latestByYear(facts, metric, docYear);
    if (seq.length < 2) return null;
    const prev = seq[seq.length - 2], cur = seq[seq.length - 1];
    return { prev: prev, cur: cur, delta: Math.round((cur.value - prev.value) * 100) / 100 };
  }

  return {
    LIMITS: LIMITS,
    clamp: clamp,
    clampHome: v => clamp(v, LIMITS.home.min, LIMITS.home.max),
    clampGallons: v => clamp(v, LIMITS.gallons.min, LIMITS.gallons.max),
    taxOnValue: taxOnValue,
    oneCentOnValue: oneCentOnValue,
    centsOnValue: centsOnValue,
    isInTown: isInTown,
    propertyTaxBill: propertyTaxBill,
    townPolicyIsPartOfTheBill: townPolicyIsPartOfTheBill,
    blockBill: blockBill,
    utilityBill: utilityBill,
    residentTotal: residentTotal,
    docYearIndex: docYearIndex,
    factsFor: factsFor,
    latestByYear: latestByYear,
    latestFact: latestFact,
    factForYear: factForYear,
    rateChange: rateChange,
  };
});
