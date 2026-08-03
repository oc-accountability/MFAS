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

  /**
   * What N cents of the TOWN's rate would cost this household — or null.
   *
   * `const oneCent = homeValue / 100 * 0.01` was written inline five separate times and
   * multiplied by town-rate cent figures with no reference to the reader's location, so
   * roughly eighteen personalised dollar amounts were published to a household the same
   * page had just told pays the town nothing: "One cent on the tax rate costs YOU ·
   * $50 / yr", "at least $500 a year for a home like YOURS", twelve driver rows reading
   * "$729/yr on YOUR home". Two of them printed onto the takeaway a resident carries
   * into a board meeting, where they cannot click through (finding F-01).
   *
   * The distinction the fix has to keep: the CENTS figure is a real town-policy fact and
   * is worth showing to anyone. It is the second-person DOLLAR column that is false
   * outside the limits. So this returns null there and the caller drops the column,
   * rather than the whole row.
   */
  function townPolicyDollarsOnThisHome(assessedValue, location, cents) {
    if (!townPolicyIsPartOfTheBill(location)) return null;
    return centsOnValue(assessedValue, cents);
  }

  /**
   * How much more this household pays next year, from every component that moved.
   *
   * The row labelled "So next year costs you about +$X more" was built from the county
   * increase plus twelve months of utility increase. `townRateChange()` had already been
   * called eleven lines above and its delta was used only as a text label — so with a
   * town rate rise of 4 cents the callout correctly announced it while the row directly
   * above still omitted the $200 it costs, understating the year by 62% (finding F-12).
   *
   * `townDeltaCents` is a REQUIRED argument rather than an optional one, so a future
   * caller cannot forget it the way the original did. It is location-gated: adding it
   * unconditionally would quote a town rate rise to an out-of-town household, which is
   * F-01 again wearing a different hat.
   */
  function annualBillChange(o) {
    const opts = o || {};
    const town = townPolicyDollarsOnThisHome(
      opts.assessedValue, opts.location, opts.townDeltaCents) || 0;
    const county = centsOnValue(opts.assessedValue, opts.countyIncreaseCents) || 0;
    const utility = isNum(opts.utilityMonthlyDelta) ? opts.utilityMonthlyDelta * 12 : 0;
    return { town: town, county: county, utility: utility, total: town + county + utility };
  }

  /**
   * A cents-on-the-rate equivalent of a dollar amount — or nothing.
   *
   * Both divisions in the FY2029 cliff card fell back to `|| 240000`, a literal
   * transcription of one year's revenue-per-cent, while the note 28 lines above
   * rendered an honest "n/a" for the same missing value. The card could therefore say
   * "the conversion uses the town's own published figure of n/a" and, immediately below,
   * "about 14.87 cents on the tax rate" — a sourced-looking figure whose divisor the
   * same card had just admitted it did not have (finding F-14).
   */
  function centsEquivalent(dollars, pennyYield) {
    if (!isNum(dollars) || !isNum(pennyYield) || pennyYield === 0) return null;
    return dollars / pennyYield;
  }

  /**
   * Shares of a stacked total, with the denominator STATED.
   *
   * Every bar width and legend percentage was `part / sum * 100` labelled "% of the
   * total", while the same function ten lines later rendered a ⚠ for exactly the case
   * where the parts do not sum to the published total. Publish a total the parts miss
   * and the page renders "differs from the stated total by $1.58M" directly below a
   * legend reading "53.5% of the total" — against the total it just named, 51.3%
   * (finding F-11).
   *
   * A stacked bar HAS to fill, so widths must always divide by the sum. The legend is a
   * claim about a published total and must divide by that. Two genuinely different uses,
   * returned separately rather than collapsed into one number that is wrong for one of
   * them.
   */
  function fundShares(parts, statedTotal) {
    const values = (parts || []).map(p => (isNum(p.value) ? p.value : 0));
    const sum = values.reduce((a, b) => a + b, 0);
    const agrees = isNum(statedTotal) && Math.abs(sum - statedTotal) < 1;
    const denominator = agrees ? statedTotal : sum;
    return {
      sum: sum,
      denominator: denominator,
      agrees: agrees,
      difference: isNum(statedTotal) ? Math.abs(sum - statedTotal) : null,
      /* "of the total" is only true when they agree. */
      label: agrees ? 'of the total' : 'of the three funds',
      widthPct: v => (sum ? v / sum * 100 : 0),
      sharePct: v => (denominator ? v / denominator * 100 : 0),
    };
  }

  /**
   * Budget against actual, with the DIRECTION derived rather than assumed.
   *
   * The sentence read "…and actually spent $X, {pct} less than planned" with no sign
   * branch, while the revenue figure on the very next line did branch. An overspend
   * would have published "−1.4% less than planned" — a double negative most readers
   * parse as an underspend — in a panel titled "Did they spend what they said they
   * would?", about a named board (finding F-15).
   */
  function budgetVariance(finalBudget, actual) {
    if (!isNum(finalBudget) || !isNum(actual) || finalBudget === 0) return null;
    const diff = finalBudget - actual;
    return {
      pct: Math.abs(diff / finalBudget * 100),
      signedPct: diff / finalBudget * 100,
      direction: diff > 0 ? 'under' : diff < 0 ? 'over' : 'exact',
      amount: Math.abs(diff),
    };
  }

  /**
   * The capital plan split into money already appropriated and money in the window.
   *
   * `amounts[0]` is the current project budget and `amounts.slice(1)` the seven plan
   * years; a fifth of the headline total sits in that first column, so reporting the
   * whole figure as the coming window misattributed $14.5M. The split was written to fix
   * that and then kept no check that it still held: drop the standalone current-budget
   * column and `amounts[0]` silently becomes the first plan year, reported as money
   * "already in current project budgets" — the same class of error again (finding F-08).
   *
   * So the shape is asserted, not assumed, and the parts are checked against the
   * published total the sentence prints beside them.
   */
  function splitProjectCost(projects, statedTotal, expectedColumns) {
    const rows = [];
    for (const p of projects || []) {
      for (const r of p.expenditures_by_account || []) rows.push(r.amounts || []);
    }
    const widths = new Set(rows.map(a => a.length));
    const shapeOk = widths.size === 1
      && (expectedColumns == null || widths.has(expectedColumns));
    const already = rows.reduce((a, amounts) => a + (amounts[0] || 0), 0);
    const window = rows.reduce(
      (a, amounts) => a + amounts.slice(1).reduce((x, v) => x + (v || 0), 0), 0);
    const reconciles = isNum(statedTotal)
      ? Math.abs(already + window - statedTotal) < 1 : null;
    return {
      already: already, window: window, sum: already + window,
      columns: widths.size === 1 ? [...widths][0] : null,
      shapeOk: shapeOk, reconciles: reconciles,
    };
  }

  /**
   * The rate sentence for an artefact that LEAVES the page.
   *
   * `copySnap` built a third hand-written row list with no location branch, so the block
   * a reader pastes into an email to a commissioner always said "Tax rate: 51.3 cents
   * per $100" — the TOWN's rate. Out of town that does not reconcile with the county
   * total three lines above it, and the reader's actual 67.58 cents never appeared. In
   * town it was equally wrong the other way: the household is charged 51.3 + 67.58 and
   * the line named only half of it (finding F-19).
   *
   * Returns the rates that actually apply, in order, so the caller cannot pick.
   */
  function applicableRates(o) {
    const opts = o || {};
    const out = [];
    if (isInTown(opts.location) && isNum(opts.townRateCents)) {
      out.push({ key: 'town', label: 'Town of Hillsborough', cents: opts.townRateCents });
    }
    if (isNum(opts.countyRateCents)) {
      out.push({ key: 'county', label: 'Orange County', cents: opts.countyRateCents });
    }
    const combined = out.reduce((a, r) => a + r.cents, 0);
    return { rates: out, combined: out.length ? combined : null };
  }

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
          /* What the total is actually made of — see the fallback below. */
          components: ['water', 'sewer', 'stormwater'],
          known: true,
          /* The YEARS the rows are labelled with, read from the rate sets rather than
             written into the copy. Three labels said "FY2027 rates" and "on FY2026"
             from string literals, so the first re-run against a new fee schedule would
             have shown FY2028 charges under an FY2027 heading on a page whose masthead
             promises every figure names the document it came from (finding F-22). */
          fiscalYear: (w.recommended || {}).fiscal_year || null,
          priorFiscalYear: (w.current || {}).fiscal_year || null,
        };
      }
    }
    /* THE FALLBACK NAMES WHAT IT CONTAINS, because it contains less than the callers
       assumed. The published increases cover water and sewer only — there is no
       stormwater component here at all — while four surfaces each carried their own
       hardcoded sentence saying "water, sewer and the stormwater fee together add about
       $X a month" about this very number. The exact path gives $10.21 and this one gives
       $8.96; the two differ by exactly the omitted fee (finding F-18).

       Callers render the component list rather than a fixed phrase, so the sentence can
       never name a charge the arithmetic left out. `known` is false when neither
       published increase is available, so a caller withholds instead of printing a
       sourced-looking $0. */
    // Published increases are given at 2,000 and 4,000 gallons only; pick the nearer.
    const level = Math.abs(g - 2000) < Math.abs(g - 4000) ? 'min' : 'avg';
    const w = lookup('water_bill_increase_monthly_' + location + '_' + level);
    const s = lookup('sewer_bill_increase_monthly_' + location + '_' + level);
    const parts = [];
    if (isNum(w)) parts.push('water');
    if (isNum(s)) parts.push('sewer');
    return {
      exact: false, gallons: level === 'min' ? 2000 : 4000,
      water: w, sewer: s,
      total: parts.length ? (w || 0) + (s || 0) : null,
      annualTotal: null,
      components: parts,
      known: parts.length > 0,
      fiscalYear: null, priorFiscalYear: null,
    };
  }

  /** "water, sewer and the stormwater fee" — built from what the total really holds. */
  function componentPhrase(components) {
    const names = (components || []).map(c => (c === 'stormwater' ? 'the stormwater fee' : c));
    if (!names.length) return '';
    if (names.length === 1) return names[0];
    return names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1];
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
    townPolicyDollarsOnThisHome: townPolicyDollarsOnThisHome,
    annualBillChange: annualBillChange,
    centsEquivalent: centsEquivalent,
    fundShares: fundShares,
    budgetVariance: budgetVariance,
    splitProjectCost: splitProjectCost,
    applicableRates: applicableRates,
    blockBill: blockBill,
    utilityBill: utilityBill,
    componentPhrase: componentPhrase,
    residentTotal: residentTotal,
    docYearIndex: docYearIndex,
    factsFor: factsFor,
    latestByYear: latestByYear,
    latestFact: latestFact,
    factForYear: factForYear,
    rateChange: rateChange,
  };
});
