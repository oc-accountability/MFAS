/* Hillsborough / Orange County fiscal transparency — client-side analytics.
 *
 * Everything is computed here in the browser against the published JSON, so
 * adding a fact to the pipeline changes the site with no code edit.
 *
 * Charting rules followed deliberately (from the dataviz method):
 *   - never a dual axis; two units means two charts
 *   - diverging blue/red only where the data has real polarity (surplus/deficit)
 *   - single-series charts get no legend box; the title names the series
 *   - values labelled selectively (endpoint / extreme), never every point
 *   - 2px surface gaps separate touching marks; 2px surface rings on markers
 *   - every chart ships a table twin
 *   - text never wears the series colour
 */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;

const state = {
  yearMin: null, yearMax: null, data: null,
  homeValue: 400000, location: 'intown', useLevel: 'avg',
};

/* ---------------------------------------------------------------- formatters */
const usd = n => '$' + Math.round(n).toLocaleString('en-US');
const usd2 = n => '$' + n.toFixed(2);
const usdSigned = n => (n < 0 ? '−' : '') + '$' + Math.abs(Math.round(n)).toLocaleString('en-US');
const compact = n => {
  const a = Math.abs(n), s = n < 0 ? '−' : '';
  if (a >= 1e9) return s + '$' + (a / 1e9).toFixed(2) + 'B';
  if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(a >= 1e7 ? 1 : 2) + 'M';
  if (a >= 1e3) return s + '$' + Math.round(a / 1e3) + 'K';
  return s + '$' + Math.round(a);
};
/* U+2212 minus, not an ASCII hyphen — it matches the dollar figures and lines up
   in tabular-nums columns, where a hyphen sits visibly high and narrow. */
const pctPlain = n => (n < 0 ? '−' : '') + Math.abs(n).toFixed(Math.abs(n) % 1 === 0 ? 0 : 1) + '%';
/* A tax rate is cents per $100 of value, NOT a percentage. Labelling 51.3 cents
 * as "51.3%" would overstate the rate ~19.5x to anyone skimming. */
const cents = n => n.toFixed(n % 1 === 0 ? 0 : 1);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* --------------------------------------------------------------- data access */
let _docMap = null;
function docsById() {
  if (!_docMap) {
    _docMap = new Map();
    for (const d of state.data.documents.documents) _docMap.set(d.id, d);
  }
  return _docMap;
}
const docYear = id => (docsById().get(id) || {}).fiscal_year || 0;
const facts = metric => state.data.facts.facts.filter(f => f.metric === metric);
const inRange = f => f.fiscal_year == null
  || (f.fiscal_year >= state.yearMin && f.fiscal_year <= state.yearMax);

/** One value per fiscal year: the reading from the most recent document. */
function latestByYear(metric) {
  const by = new Map();
  for (const f of facts(metric)) {
    if (f.fiscal_year == null) continue;
    const prev = by.get(f.fiscal_year);
    if (!prev || docYear(f.source_doc) > docYear(prev.source_doc)) by.set(f.fiscal_year, f);
  }
  return [...by.values()].sort((a, b) => a.fiscal_year - b.fiscal_year);
}
function one(metric) {
  const rows = facts(metric);
  if (!rows.length) return null;
  return rows.reduce((a, b) => (docYear(b.source_doc) > docYear(a.source_doc) ? b : a));
}
const val = (metric, fallback = null) => { const f = one(metric); return f ? f.value : fallback; };

function cite(f) {
  if (!f) return '';
  const d = docsById().get(f.source_doc);
  const name = d ? d.filename : f.source_doc;
  const label = esc(name + (f.source_page ? `, p.${f.source_page}` : ''));
  if (d && d.official_url) return `<a class="src-link" href="${esc(d.official_url)}">${label}</a>`;
  return `<span class="src-link" title="Source file and SHA-256 recorded in data/datasets/documents.json">${label}</span>`;
}

/* ------------------------------------------------------------------- tooltip */
const tip = Object.assign(document.createElement('div'), { id: 'tip' });
document.body.appendChild(tip);
function showTip(html, ev) {
  tip.innerHTML = html;
  tip.classList.add('on');
  const r = tip.getBoundingClientRect();
  let x = ev.clientX + 14, y = ev.clientY - 12;
  if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
  if (y + r.height > innerHeight - 8) y = innerHeight - r.height - 8;
  tip.style.left = Math.max(8, x) + 'px';
  tip.style.top = Math.max(8, y) + 'px';
}
const hideTip = () => tip.classList.remove('on');
/** Hover + keyboard focus show the same thing — a tooltip must never gate a value. */
function bindTip(el, html) {
  el.addEventListener('mouseenter', e => showTip(html, e));
  el.addEventListener('mousemove', e => showTip(html, e));
  el.addEventListener('mouseleave', hideTip);
  el.setAttribute('tabindex', '0');
  el.setAttribute('role', 'img');
  el.addEventListener('focus', () => {
    const b = el.getBoundingClientRect();
    showTip(html, { clientX: b.left + b.width / 2, clientY: b.top });
  });
  el.addEventListener('blur', hideTip);
}

/* ----------------------------------------------------------- svg primitives */
const NS = 'http://www.w3.org/2000/svg';
const mk = (n, a = {}) => {
  const e = document.createElementNS(NS, n);
  for (const k in a) e.setAttribute(k, a[k]);
  return e;
};
/** Bar with the data-end rounded and the baseline end square. */
function barPath(x, y, w, h, r, roundTop) {
  r = Math.max(0, Math.min(r, w / 2, h));
  if (h <= 0.5) return `M${x} ${y}h${w}`;
  return roundTop
    ? `M${x} ${y + h}V${y + r}a${r} ${r} 0 0 1 ${r} ${-r}h${w - 2 * r}a${r} ${r} 0 0 1 ${r} ${r}V${y + h}Z`
    : `M${x} ${y}V${y + h - r}a${r} ${r} 0 0 0 ${r} ${r}h${w - 2 * r}a${r} ${r} 0 0 0 ${r} ${-r}V${y}Z`;
}
function niceTicks(lo, hi, n = 4) {
  if (lo === hi) { lo = Math.min(0, lo); hi = hi || 1; }
  const raw = (hi - lo) / n;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(raw) || 1)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw) || mag * 10;
  const out = [];
  for (let v = Math.floor(lo / step) * step; v <= hi + step * 0.5; v += step) out.push(+v.toFixed(6));
  return out;
}

const M = { t: 22, r: 76, b: 34, l: 60 };
const W = 700, H = 250;

const frame = () => mk('svg', {
  class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img',
  preserveAspectRatio: 'xMidYMid meet'
});
function titled(svg, text) {
  const t = mk('title');
  t.textContent = text;
  svg.appendChild(t);
}
function yAxis(svg, ticks, y, fmt) {
  for (const t of ticks) {
    const yy = y(t);
    svg.appendChild(mk('line', { class: 'gridline', x1: M.l, x2: W - M.r, y1: yy, y2: yy }));
    const lab = mk('text', { class: 'tick', x: M.l - 9, y: yy + 3.5, 'text-anchor': 'end' });
    lab.textContent = fmt(t);
    svg.appendChild(lab);
  }
}
function xLabels(svg, n, cx, label) {
  for (let i = 0; i < n; i++) {
    const t = mk('text', { class: 'tick', x: cx(i), y: H - M.b + 17, 'text-anchor': 'middle' });
    t.textContent = label(i);
    svg.appendChild(t);
  }
}

/* --------------------------------------------------------------- chart cards */
function card(title, note, svg, legend, tableFn) {
  const c = document.createElement('div');
  c.className = 'chart-card';
  const head = document.createElement('div');
  head.className = 'chart-head';
  head.innerHTML = `<h3>${esc(title)}</h3>` + (note ? `<p class="note">${note}</p>` : '');
  c.appendChild(head);
  const scroll = document.createElement('div');
  scroll.className = 'chart-scroll';
  scroll.appendChild(svg);
  c.appendChild(scroll);
  if (legend) {
    const ul = document.createElement('ul');
    ul.className = 'legend';
    ul.innerHTML = legend;
    c.appendChild(ul);
  }
  if (tableFn) {
    const btn = document.createElement('button');
    btn.className = 'tabtoggle';
    btn.type = 'button';
    btn.textContent = 'Show the numbers';
    btn.setAttribute('aria-expanded', 'false');
    const holder = document.createElement('div');
    holder.hidden = true;
    btn.addEventListener('click', () => {
      if (!holder.childElementCount) holder.innerHTML = tableFn();
      holder.hidden = !holder.hidden;
      btn.textContent = holder.hidden ? 'Show the numbers' : 'Hide the numbers';
      btn.setAttribute('aria-expanded', String(!holder.hidden));
    });
    c.appendChild(btn);
    c.appendChild(holder);
  }
  return c;
}
function tableOf(caption, cols, rows) {
  return `<div class="tablewrap"><table><caption>${caption}</caption><thead><tr>` +
    cols.map(c => `<th${c.num ? ' class="num"' : ''}>${esc(c.label)}</th>`).join('') +
    `</tr></thead><tbody>` +
    rows.map(r => '<tr>' + r.map((v, i) =>
      `<td${cols[i] && cols[i].num ? ' class="num"' : ''}>${v}</td>`).join('') + '</tr>').join('') +
    `</tbody></table></div>`;
}
function section(id, num, title, blurb) {
  const s = document.createElement('section');
  s.id = id;
  s.innerHTML = `<div class="sec-head"><span class="sec-num">${num}</span>
    <h2>${title}</h2>${blurb ? `<p>${blurb}</p>` : ''}</div>`;
  return s;
}

/* ====================== 01 — household calculator ======================= */
function renderHousehold(host) {
  const rateF = one('property_tax_rate');
  if (!rateF) return;
  const perCentF = one('revenue_per_cent_of_tax_rate');

  const sec = section('household', '01', 'What the town costs your household',
    `The town's property tax rate is <strong>${cents(rateF.value)} cents per $100</strong> of assessed
     value (${esc(rateF.basis)}, FY${rateF.fiscal_year}). Enter what your home is assessed at to see
     the town's share of your bill, and what next year's utility increases add on top.
     This is the <em>town</em> rate only — your full bill also includes Orange County and any special
     district, which are not in this dataset.`);

  const panel = document.createElement('div');
  panel.className = 'panel panel-pad';
  panel.innerHTML = `
    <div class="calc">
      <div>
        <div class="field">
          <label class="field-label" for="hv">Assessed home value</label>
          <input type="number" id="hv" min="0" step="5000" value="${state.homeValue}" inputmode="numeric">
          <input type="range" id="hvr" min="50000" max="1500000" step="5000" value="${state.homeValue}"
                 aria-label="Assessed home value slider">
        </div>
        <div class="field">
          <span class="field-label" id="locLbl">Where is the property?</span>
          <div class="seg" role="group" aria-labelledby="locLbl">
            <button type="button" data-loc="intown" aria-pressed="true">Inside town limits</button>
            <button type="button" data-loc="outoftown" aria-pressed="false">Outside town</button>
          </div>
        </div>
        <div class="field">
          <span class="field-label" id="useLbl">Household water use</span>
          <div class="seg" role="group" aria-labelledby="useLbl">
            <button type="button" data-use="avg" aria-pressed="true">Average · 4,000 gal/mo</button>
            <button type="button" data-use="min" aria-pressed="false">Low · 2,000 gal/mo</button>
          </div>
        </div>
      </div>
      <div class="readout">
        <p class="cap">Estimated annual town property tax</p>
        <div class="hero-figure" id="heroV">—</div>
        <p class="hero-sub" id="heroN"></p>
        <ul class="rows" id="bd"></ul>
        <div class="callout" id="calloutBox"></div>
      </div>
    </div>`;
  sec.appendChild(panel);
  host.appendChild(sec);

  const num = $('#hv', sec), rng = $('#hvr', sec);

  function draw(animate) {
    const v = Math.max(0, +num.value || 0);
    state.homeValue = v;
    const annual = v / 100 * (rateF.value / 100);
    const oneCent = v / 100 * 0.01;

    setFigure($('#heroV', sec), annual, animate);
    $('#heroN', sec).innerHTML =
      `${usd(annual / 12)} a month at the FY${rateF.fiscal_year} rate of ${cents(rateF.value)} cents
       per $100. Source: ${cite(rateF)}.`;

    const water = val(`water_bill_increase_monthly_${state.location}_${state.useLevel}`);
    const sewer = val(`sewer_bill_increase_monthly_${state.location}_${state.useLevel}`);
    const utilMo = (water || 0) + (sewer || 0);

    const rows = [];
    rows.push([`Town property tax`, `<small>FY${rateF.fiscal_year}, rate unchanged</small>`,
      usd(annual) + ' / yr']);
    if (water != null) rows.push([`Water bill increase`,
      `<small>FY2026 → FY2027, ${state.useLevel === 'avg' ? '4,000' : '2,000'} gal/mo</small>`,
      '+' + usd2(water) + ' / mo']);
    if (sewer != null) rows.push([`Sewer bill increase`, `<small>same basis</small>`,
      '+' + usd2(sewer) + ' / mo']);
    rows.push([`One cent on the tax rate, to you`, `<small>town-wide it raises ${
      perCentF ? usd(perCentF.value) : 'n/a'}</small>`, usd(oneCent) + ' / yr']);

    const need = one('tax_rate_increase_needed_cents');
    if (need) rows.push([`A ${cents(need.value)}-cent rise`,
      `<small>the town's FY${need.fiscal_year} deficit scenario</small>`,
      '+' + usd(oneCent * need.value) + ' / yr']);

    let html = rows.map(([k, sub, v2]) =>
      `<li><span class="k">${k}${sub}</span><span class="v">${v2}</span></li>`).join('');
    if (utilMo > 0) {
      html += `<li class="total"><span class="k">What next year adds, in total</span>
        <span class="v">+${usd(utilMo * 12)} / yr</span></li>`;
    }
    $('#bd', sec).innerHTML = html;

    const box = $('#calloutBox', sec);
    const wr = val('water_rate_increase_pct'), sr = val('sewer_rate_increase_pct');
    if (utilMo > 0 && wr && sr) {
      box.className = 'callout warn';
      box.innerHTML = `<strong>No property tax increase this year — but your bill still goes up.</strong>
        Water and sewer rates each rise ${pctPlain(wr)} in FY2027, which adds about
        <strong>${usd2(utilMo)} a month</strong> (${usd(utilMo * 12)} a year) for this household.
        A flat tax rate is not the same as a flat bill.`;
    } else {
      box.className = 'callout';
      box.innerHTML = `The tax rate is unchanged for FY${rateF.fiscal_year}.`;
    }
  }

  num.addEventListener('input', () => { rng.value = num.value; draw(false); });
  rng.addEventListener('input', () => { num.value = rng.value; draw(false); });
  $$('.seg button', sec).forEach(b => b.addEventListener('click', () => {
    const key = b.dataset.loc ? 'location' : 'useLevel';
    const v = b.dataset.loc || b.dataset.use;
    state[key] = v;
    $$(`[data-${b.dataset.loc ? 'loc' : 'use'}]`, sec)
      .forEach(o => o.setAttribute('aria-pressed', String(o === b)));
    draw(false);
  }));
  draw(!REDUCED);
}

/** Count up to a value on first paint only; instant on later edits. */
function setFigure(el, target, animate) {
  if (!animate) { el.textContent = usd(target); return; }
  const dur = 620, t0 = performance.now();
  const step = now => {
    const p = Math.min(1, (now - t0) / dur);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = usd(target * eased);
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* ======================= 02 — the budget, whole ========================= */
function renderBudget(host) {
  const total = one('total_budget');
  const parts = [
    ['general_fund_expenditures', 'General Fund', 'var(--series-1)',
     'Police, fire, streets, parks, planning, administration — the tax-funded side.'],
    ['water_sewer_fund_expenditures', 'Water & Sewer Fund', 'var(--series-2)',
     'Paid for by water and sewer bills, not property tax.'],
    ['stormwater_fund_expenditures', 'Stormwater Fund', 'var(--series-3)',
     'Paid for by the stormwater fee, charged per Equivalent Residential Unit.'],
  ].map(([m, label, colour, blurb]) => {
    const f = one(m);
    return f ? { label, colour, blurb, value: f.value, f } : null;
  }).filter(Boolean);

  if (!total || parts.length < 2) return;

  const sec = section('budget', '02', 'Where the money goes',
    `The FY2027 recommended budget is <strong>${compact(total.value)}</strong> across three funds.
     Only the General Fund is supported by property tax — the other two are paid for by the bills
     for those services, which is why a water rate rise is not a tax rise, and vice versa.`);

  const sum = parts.reduce((a, p) => a + p.value, 0);
  const panel = document.createElement('div');
  panel.className = 'panel panel-pad';

  const bars = parts.map(p =>
    `<span style="background:${p.colour};width:${(p.value / sum * 100).toFixed(3)}%"
       title="${esc(p.label)}: ${esc(compact(p.value))}"></span>`).join('');

  const legend = parts.map(p => `<li>
      <span class="sw" style="background:${p.colour}"></span>
      <span><span class="nm">${esc(p.label)}</span>
        <span class="amt">${esc(compact(p.value))}</span>
        <span class="pc">${(p.value / sum * 100).toFixed(1)}% of total</span></span>
    </li>`).join('');

  // Publishing a total that does not equal its parts would be its own small lie.
  const diff = Math.abs(sum - total.value);
  const check = diff < 1
    ? `The three funds sum exactly to the stated total of ${compact(total.value)} — checked by this
       page, not assumed.`
    : `⚠ The three funds sum to ${compact(sum)}, which differs from the stated total
       ${compact(total.value)} by ${compact(diff)}. Shown as found in the source.`;

  panel.innerHTML = `<div class="ptw" role="img"
      aria-label="${esc(parts.map(p => `${p.label} ${compact(p.value)}`).join('; '))}">${bars}</div>
    <ul class="ptw-legend">${legend}</ul>
    <p class="note" style="margin:var(--s5) 0 0;font-size:var(--t-xs);color:var(--text-muted)">
      ${check} Source: ${cite(total)}.</p>`;
  sec.appendChild(panel);

  // headline tiles
  const defs = [
    ['total_budget', 'Total budget, all funds', compact],
    ['general_fund_balance_pct_of_expenditures', 'Savings, as % of spending', pctPlain],
    ['general_fund_surplus_deficit', 'Deficit, furthest projection', compact],
    ['revenue_per_cent_of_tax_rate', 'One cent of tax raises', compact],
  ];
  const tiles = defs.map(([metric, label, fmt]) => {
    let f;
    if (metric === 'general_fund_surplus_deficit') {
      const rows = latestByYear(metric);
      f = rows.length ? rows[rows.length - 1] : null;
    } else f = one(metric);
    if (!f) return '';
    return `<div class="tile"><p class="k">${esc(label)}</p>
      <div class="v">${esc(fmt(f.value))}</div>
      <p class="d">FY${f.fiscal_year} · ${esc(f.basis || '')}</p></div>`;
  }).join('');
  const tw = document.createElement('div');
  tw.className = 'tiles';
  tw.style.marginTop = 'var(--s5)';
  tw.innerHTML = tiles;
  sec.appendChild(tw);

  host.appendChild(sec);
}

/* ============================ charts: forms ============================= */
function chartSurplus() {
  const rows = latestByYear('general_fund_surplus_deficit').filter(inRange);
  if (!rows.length) return null;
  const vals = rows.map(r => r.value);
  // Pad the domain so the deepest bar never reaches the lowest gridline — its
  // value label sits below the bar end and would otherwise collide with the
  // x-axis year labels.
  const ticks = niceTicks(Math.min(0, ...vals) * 1.14, Math.max(0, ...vals) * 1.14, 4);
  const lo = Math.min(...ticks), hi = Math.max(...ticks);
  const y = v => M.t + (hi - v) / (hi - lo) * (H - M.t - M.b);
  const band = (W - M.l - M.r) / rows.length;
  const bw = Math.min(24, band * 0.46);
  const cx = i => M.l + band * (i + 0.5);

  const svg = frame();
  titled(svg, 'General Fund surplus or deficit by fiscal year');
  yAxis(svg, ticks, y, compact);
  const zero = y(0);
  svg.appendChild(mk('line', { class: 'axisline', x1: M.l, x2: W - M.r, y1: zero, y2: zero }));

  rows.forEach((r, i) => {
    const up = r.value >= 0, h = Math.abs(y(r.value) - zero);
    svg.appendChild(mk('path', {
      d: barPath(cx(i) - bw / 2, up ? zero - h : zero, bw, h, 4, up),
      fill: up ? 'var(--pos)' : 'var(--neg)'
    }));
    const lab = mk('text', {
      class: 'dlabel', x: cx(i), 'text-anchor': 'middle',
      y: up ? zero - h - 7 : zero + h + 14
    });
    lab.textContent = compact(r.value);
    svg.appendChild(lab);
    const hit = mk('rect', {
      class: 'hit', x: cx(i) - Math.max(12, band / 2), y: M.t,
      width: Math.max(24, band), height: H - M.t - M.b
    });
    bindTip(hit, `<div class="t">FY${r.fiscal_year}</div>
      <div class="r">Surplus / (deficit): <b>${usdSigned(r.value)}</b></div>
      <div class="r">Basis: ${esc(r.basis || '—')}</div>
      <div class="src">${cite(r)}</div>`);
    svg.appendChild(hit);
  });
  xLabels(svg, rows.length, cx, i => 'FY' + rows[i].fiscal_year);

  const table = () => tableOf('General Fund surplus / (deficit). Negative values are deficits.',
    [{ label: 'Fiscal year' }, { label: 'Amount', num: true }, { label: 'Basis' }, { label: 'Source' }],
    rows.map(r => ['FY' + r.fiscal_year, usdSigned(r.value), esc(r.basis || '—'), cite(r)]));

  return card('General Fund surplus and deficit',
    'The most recent figure the town has published for each year. Bars below the line are deficits.',
    svg, null, table);
}

function chartLine(metric, title, note, fmtV, refLine, refLabel) {
  const rows = latestByYear(metric).filter(inRange);
  if (rows.length < 2) return null;
  const vals = rows.map(r => r.value);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (refLine != null) { lo = Math.min(lo, refLine); hi = Math.max(hi, refLine); }
  const pad = (hi - lo) * 0.16 || 1;
  const ticks = niceTicks(Math.max(0, lo - pad), hi + pad, 4);
  const tlo = Math.min(...ticks), thi = Math.max(...ticks);
  const y = v => M.t + (thi - v) / (thi - tlo) * (H - M.t - M.b);
  const band = (W - M.l - M.r) / rows.length;
  const cx = i => M.l + band * (i + 0.5);

  const svg = frame();
  titled(svg, title);
  yAxis(svg, ticks, y, fmtV);

  if (refLine != null) {
    svg.appendChild(mk('line', {
      class: 'reference', x1: M.l, x2: W - M.r, y1: y(refLine), y2: y(refLine)
    }));
    const rl = mk('text', { class: 'reflabel', x: W - M.r + 6, y: y(refLine) + 3.5 });
    rl.textContent = refLabel || `${fmtV(refLine)} floor`;
    svg.appendChild(rl);
  }

  const d = rows.map((r, i) => `${i ? 'L' : 'M'}${cx(i)} ${y(r.value)}`).join(' ');
  const path = mk('path', {
    d, fill: 'none', stroke: 'var(--series-1)', 'stroke-width': 2,
    'stroke-linejoin': 'round', 'stroke-linecap': 'round'
  });
  svg.appendChild(path);
  if (!REDUCED) {
    const len = path.getTotalLength ? 1400 : 0;
    if (len) {
      path.style.strokeDasharray = len;
      path.style.strokeDashoffset = len;
      path.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }],
        { duration: 800, easing: 'ease-out', fill: 'forwards' });
    }
  }

  rows.forEach((r, i) => {
    svg.appendChild(mk('circle', {
      cx: cx(i), cy: y(r.value), r: 4.5,
      fill: 'var(--series-1)', stroke: 'var(--surface-1)', 'stroke-width': 2
    }));
    if (i === rows.length - 1) {
      const lab = mk('text', { class: 'dlabel', x: cx(i) + 10, y: y(r.value) + 3.5 });
      lab.textContent = fmtV(r.value);
      svg.appendChild(lab);
    }
    const hit = mk('rect', {
      class: 'hit', x: cx(i) - Math.max(12, band / 2), y: M.t,
      width: Math.max(24, band), height: H - M.t - M.b
    });
    bindTip(hit, `<div class="t">FY${r.fiscal_year}</div>
      <div class="r"><b>${fmtV(r.value)}</b></div>
      <div class="r">Basis: ${esc(r.basis || '—')}</div>
      <div class="src">${cite(r)}</div>`);
    svg.appendChild(hit);
  });
  xLabels(svg, rows.length, cx, i => 'FY' + rows[i].fiscal_year);

  const table = () => tableOf(title,
    [{ label: 'Fiscal year' }, { label: 'Value', num: true }, { label: 'Basis' }, { label: 'Source' }],
    rows.map(r => ['FY' + r.fiscal_year, fmtV(r.value), esc(r.basis || '—'), cite(r)]));
  return card(title, note, svg, null, table);
}

function chartDumbbell(items, title, note, fmtV, labels) {
  if (!items.length) return null;
  const all = items.flatMap(i => [i.a, i.b]);
  // Scale to the data range, not to zero. In a dumbbell the mark POSITION encodes
  // the value and the connecting line encodes the change — no length is measured
  // from an origin, so a zero baseline is not required (unlike a bar chart). With
  // values clustered at $11-16M, forcing zero squeezes every pair into the right
  // quarter of the plot and hides the very differences the chart exists to show.
  const lo0 = Math.min(...all), hi0 = Math.max(...all);
  const pad = (hi0 - lo0) * 0.18 || Math.abs(hi0 * 0.1) || 1;
  const ticks = niceTicks(Math.max(0, lo0 - pad), hi0 + pad, 4);
  const tlo = Math.min(...ticks), thi = Math.max(...ticks);
  const h = Math.max(148, 44 * items.length + M.t + M.b);
  const svg = mk('svg', {
    class: 'chart', viewBox: `0 0 ${W} ${h}`, role: 'img',
    preserveAspectRatio: 'xMidYMid meet'
  });
  titled(svg, title);
  const L = 132, R = 92;
  const x = v => L + (v - tlo) / (thi - tlo) * (W - L - R);
  const band = (h - M.t - M.b) / items.length;
  const cy = i => M.t + band * (i + 0.5);

  for (const t of ticks) {
    svg.appendChild(mk('line', { class: 'gridline', x1: x(t), x2: x(t), y1: M.t, y2: h - M.b }));
    const lab = mk('text', { class: 'tick', x: x(t), y: h - M.b + 17, 'text-anchor': 'middle' });
    lab.textContent = fmtV(t);
    svg.appendChild(lab);
  }

  items.forEach((it, i) => {
    const yy = cy(i);
    svg.appendChild(mk('line', {
      x1: x(it.a), x2: x(it.b), y1: yy, y2: yy,
      stroke: 'var(--axis)', 'stroke-width': 2, 'stroke-linecap': 'round'
    }));
    for (const [v, col] of [[it.a, 'var(--step-early)'], [it.b, 'var(--step-late)']]) {
      svg.appendChild(mk('circle', {
        cx: x(v), cy: yy, r: 5.5, fill: col,
        stroke: 'var(--surface-1)', 'stroke-width': 2
      }));
    }
    const name = mk('text', { class: 'tick', x: L - 12, y: yy + 3.5, 'text-anchor': 'end' });
    name.textContent = it.label;
    svg.appendChild(name);

    const delta = it.b - it.a;
    const dl = mk('text', { class: 'dlabel', x: Math.max(x(it.a), x(it.b)) + 11, y: yy + 3.5 });
    dl.textContent = (delta >= 0 ? '+' : '−') + fmtV(Math.abs(delta));
    svg.appendChild(dl);

    const hit = mk('rect', {
      class: 'hit', x: 0, y: yy - Math.max(12, band / 2),
      width: W - 8, height: Math.max(24, band)
    });
    bindTip(hit, `<div class="t">${esc(it.label)}</div>
      <div class="r">${esc(labels[0])}: <b>${fmtV(it.a)}</b></div>
      <div class="r">${esc(labels[1])}: <b>${fmtV(it.b)}</b></div>
      <div class="r">Change: <b>${(delta >= 0 ? '+' : '−') + fmtV(Math.abs(delta))}</b></div>
      ${it.src ? `<div class="src">${it.src}</div>` : ''}`);
    svg.appendChild(hit);
  });

  const legend =
    `<li><span class="swatch" style="background:var(--step-early)"></span>${esc(labels[0])}</li>` +
    `<li><span class="swatch" style="background:var(--step-late)"></span>${esc(labels[1])}</li>`;
  const table = () => tableOf(title,
    [{ label: 'Item' }, { label: labels[0], num: true }, { label: labels[1], num: true },
     { label: 'Change', num: true }, { label: 'Source' }],
    items.map(it => [esc(it.label), fmtV(it.a), fmtV(it.b),
      (it.b - it.a >= 0 ? '+' : '−') + fmtV(Math.abs(it.b - it.a)), it.src || '—']));
  return card(title, note, svg, legend, table);
}

function chartColumns(rows, title, note, fmtV) {
  if (!rows.length) return null;
  const ticks = niceTicks(0, Math.max(...rows.map(r => r.value)), 4);
  const thi = Math.max(...ticks);
  const y = v => M.t + (thi - v) / thi * (H - M.t - M.b);
  const band = (W - M.l - M.r) / rows.length;
  const bw = Math.min(24, band * 0.46);
  const cx = i => M.l + band * (i + 0.5);
  const svg = frame();
  titled(svg, title);
  yAxis(svg, ticks, y, fmtV);
  const base = y(0);
  svg.appendChild(mk('line', { class: 'axisline', x1: M.l, x2: W - M.r, y1: base, y2: base }));
  rows.forEach((r, i) => {
    svg.appendChild(mk('path', {
      d: barPath(cx(i) - bw / 2, y(r.value), bw, base - y(r.value), 4, true),
      fill: 'var(--series-1)'
    }));
    const lab = mk('text', { class: 'dlabel', x: cx(i), y: y(r.value) - 7, 'text-anchor': 'middle' });
    lab.textContent = fmtV(r.value);
    svg.appendChild(lab);
    const hit = mk('rect', {
      class: 'hit', x: cx(i) - Math.max(12, band / 2), y: M.t,
      width: Math.max(24, band), height: H - M.t - M.b
    });
    bindTip(hit, `<div class="t">FY${r.fiscal_year}</div><div class="r"><b>${fmtV(r.value)}</b></div>
      <div class="src">${cite(r)}</div>`);
    svg.appendChild(hit);
  });
  xLabels(svg, rows.length, cx, i => 'FY' + rows[i].fiscal_year);
  const table = () => tableOf(title,
    [{ label: 'Fiscal year' }, { label: 'Value', num: true }, { label: 'Source' }],
    rows.map(r => ['FY' + r.fiscal_year, fmtV(r.value), cite(r)]));
  return card(title, note, svg, null, table);
}

/* ========================= 03 — trends + filters ======================== */
function renderTrends(host) {
  const years = [...new Set(state.data.facts.facts
    .map(f => f.fiscal_year).filter(v => v != null))].sort((a, b) => a - b);

  const sec = section('trends', '03', 'Budget, savings and deficits',
    `Savings in dollars and savings as a share of spending are different measures, so they get
     separate charts rather than being stacked on one plot with two scales. Hover any point for the
     document and page it came from; every chart has a table view.`);

  const f = document.createElement('div');
  f.className = 'filters';
  const opts = ys => ys.map(y => `<option value="${y}">FY${y}</option>`).join('');
  f.innerHTML = `<div class="f"><label class="field-label" for="ymin">From fiscal year</label>
      <select id="ymin">${opts(years)}</select></div>
    <div class="f"><label class="field-label" for="ymax">To fiscal year</label>
      <select id="ymax">${opts(years)}</select></div>
    <p class="hint">This range scopes every chart in this section. Beyond FY2027 the figures are the
      town's own multi-year projections, not adopted budgets.</p>`;
  sec.appendChild(f);
  const a = $('#ymin', f), b = $('#ymax', f);
  a.value = state.yearMin; b.value = state.yearMax;
  const onChange = () => {
    state.yearMin = Math.min(+a.value, +b.value);
    state.yearMax = Math.max(+a.value, +b.value);
    render();
    const el = document.getElementById('trends');
    if (el) el.scrollIntoView({ block: 'start', behavior: 'auto' });
  };
  a.addEventListener('change', onChange);
  b.addEventListener('change', onChange);

  const grid = document.createElement('div');
  grid.className = 'grid2';
  [
    chartSurplus(),
    chartLine('general_fund_balance_available_cash', 'General Fund savings (available cash)',
      'The town’s cash reserve.', compact),
    chartLine('general_fund_balance_pct_of_expenditures', 'Savings as a share of yearly spending',
      'The town states its aim is to stay no lower than 50%.', pctPlain, 50, '50% stated floor'),
    chartColumns(latestByYear('admin_spend_total').filter(inRange),
      'Administrative spending',
      'Supplied by a county commissioner in the request workbook — not an audited total.', compact),
  ].filter(Boolean).forEach(c => grid.appendChild(c));
  sec.appendChild(grid);
  host.appendChild(sec);
}

/* ======================== 04 — projections moved ======================== */
function renderProjections(host) {
  const cmps = state.data.projections.comparisons.filter(c =>
    c.metric === 'general_fund_balance_available_cash');
  if (!cmps.length) return;
  const items = cmps.map(c => {
    const rs = [...c.readings].sort((x, y) => docYear(x.source_doc) - docYear(y.source_doc));
    return {
      label: 'FY' + c.fiscal_year, a: rs[0].value, b: rs[rs.length - 1].value,
      src: rs.map(r => esc(r.source_doc) + (r.source_page ? ` p.${r.source_page}` : '')).join(' → ')
    };
  });
  const sec = section('projections', '04', 'How the town’s own projections moved',
    `Hillsborough publishes a rolling three-year financial plan, so the same fiscal year appears in
     several budget documents. This compares what an earlier document projected for a year against
     what a later document reported for that same year.
     <br><br>
     The gap is <strong>not</strong> an error, and this is not an accusation. A projection and an
     adopted budget are different things, and the town's FY2025 budget message says plainly that it
     is "conservative on revenue projections and cautious on expenditure amounts" and that most
     years "end up with deficits less than projected or with an actual surplus generated." It is
     shown because it is the honest measure of how much weight a three-year projection deserves.`);
  // Full width: a dumbbell needs a label gutter plus room for the delta label, and
  // at half width the rows compress into an unreadable strip.
  const c = chartDumbbell(items, 'General Fund savings: first projection vs latest figure',
    'Each row is one fiscal year. The line spans the earlier and later readings.',
    compact, ['Earlier document', 'Later document']);
  if (c) sec.appendChild(c);
  host.appendChild(sec);
}

/* =========================== 05 — what's ahead ========================== */
function renderAhead(host) {
  const sec = section('ahead', '05', 'What’s ahead',
    `The town's own three-year plan, in its own figures. FY2027 is adopted; FY2028 and FY2029 are
     projections and will change.`);

  const def = latestByYear('general_fund_surplus_deficit');
  const pct = new Map(latestByYear('general_fund_surplus_deficit_pct').map(f => [f.fiscal_year, f]));
  const bal = new Map(latestByYear('general_fund_balance_pct_of_expenditures')
    .map(f => [f.fiscal_year, f]));
  const need = one('tax_rate_increase_needed_cents');
  const scenario = one('fy29_scenario_increase_on_400k_home');
  const capCents = one('capital_projects_tax_rate_equivalent_cents');
  const houseCents = one('affordable_housing_tax_rate_equivalent_cents');

  const items = def.filter(f => f.fiscal_year >= 2027).map(f => {
    const p = pct.get(f.fiscal_year), bl = bal.get(f.fiscal_year);
    const bad = f.value < 0 && Math.abs(p ? p.value : 0) > 8;
    let body = `General Fund ${f.value < 0 ? 'deficit' : 'surplus'} of
      <span class="fig">${usdSigned(f.value)}</span>`;
    if (p) body += ` (${pctPlain(p.value)} of the budget)`;
    body += '.';
    if (bl) body += ` Savings at <span class="fig">${pctPlain(bl.value)}</span> of yearly spending`
      + (bl.value < 50 ? ' — below the town’s own 50% floor.' : '.');
    if (f.fiscal_year === 2029 && need && scenario) {
      body += ` Closing this would take a rise of over <span class="fig">${cents(need.value)}
        cents</span>, about <span class="fig">${usd(scenario.value)} a year</span> on a
        $400,000 home.`;
    }
    return `<li class="${bad ? 'bad' : ''}"><span class="node" aria-hidden="true"></span>
      <span class="yr">FY${f.fiscal_year} · ${esc(f.basis)}</span>
      <h4>${f.fiscal_year === 2027 ? 'Adopted year' : 'Projection'}</h4>
      <p>${body}</p></li>`;
  });

  const commitments = [];
  if (capCents) commitments.push(`the fire station, Ridgewalk Greenway and train station projects are
    expected to need about <span class="fig">${cents(capCents.value)} cents</span> on the tax rate`);
  if (houseCents) commitments.push(`the board has committed to raising affordable-housing spending
    until it reaches <span class="fig">${cents(houseCents.value)} cents</span>`);
  if (commitments.length) {
    const body = commitments.join('; ').replace(/^./, ch => ch.toUpperCase());
    items.push(`<li><span class="node" aria-hidden="true"></span>
      <span class="yr">Beyond the plan</span><h4>Commitments already made</h4>
      <p>${body}. These sit on top of the deficits above.</p></li>`);
  }

  const panel = document.createElement('div');
  panel.className = 'panel panel-pad';
  panel.innerHTML = `<ul class="timeline">${items.join('')}</ul>`;
  sec.appendChild(panel);

  // capital cost growth
  const ps = state.data.requests.projects_with_cost_changes
    .filter(p => p.original_budget_usd != null && p.current_budget_usd != null);
  if (ps.length) {
    const c = chartDumbbell(ps.map(p => ({
      label: p.project, a: p.original_budget_usd, b: p.current_budget_usd,
      src: 'Data request workbook, Project Cost Changes'
    })), 'Capital projects: original budget vs current budget',
      `Figures from the initiative's own workbook rather than an audited statement, so they are
       published as claims to verify. Both rows' arithmetic reconciles.`,
      compact, ['Original budget', 'Current budget']);
    if (c) {
      c.style.marginTop = 'var(--s4)';
      sec.appendChild(c);
    }
  }
  host.appendChild(sec);
}

/* ========================== 06 — open request ========================== */
function renderRequest(host) {
  const r = state.data.requests, s = r.summary;
  const filled = s.data_cells_requested
    ? s.data_cells_provided / s.data_cells_requested * 100 : 0;

  const sec = section('request', '06', 'The open records request',
    `The initiative sent the Town of Hillsborough a workbook asking for staffing, utility,
     capital-project, debt, revenue and affordable-housing figures on a consistent basis, so that
     years could be compared without organisational changes muddying them. This is how much of it
     has been filled in.`);

  const rows = r.tables.map(t => {
    const ico = t.status === 'answered' ? '✓' : t.status === 'partial' ? '○' : '✕';
    return `<tr><td>${esc(t.section || '—')}</td><td>${esc(t.title)}</td>
      <td class="num">${t.cells_provided} / ${t.cells_expected}</td>
      <td><span class="status ${esc(t.status)}"><span class="ico" aria-hidden="true">${ico}</span>
        ${esc(t.status)}</span></td></tr>`;
  }).join('');

  const panel = document.createElement('div');
  panel.className = 'panel panel-pad';
  panel.innerHTML = `
    <div class="meter">
      <div class="track"><div class="fill" style="width:${Math.max(0.7, filled).toFixed(1)}%"></div></div>
      <div class="cap">
        <span><strong>${s.data_cells_provided}</strong> of
          <strong>${s.data_cells_requested}</strong> requested figures provided</span>
        <span><strong>${filled.toFixed(1)}%</strong></span>
      </div>
    </div>
    <p style="margin:var(--s5) 0 0;font-size:var(--t-sm);color:var(--text-secondary)">
      ${s.tables_unanswered} of ${s.tables_requested} requested tables are still entirely blank.
      This reflects the copy of the workbook held in this archive at the time it was collected — it
      is a status snapshot, <strong>not</strong> a finding that the town declined to respond.
    </p>
    <blockquote style="margin:var(--s5) 0 0;padding:var(--s4) var(--s5);
      border-left:3px solid var(--hairline-firm);color:var(--text-secondary);
      font-size:var(--t-sm);background:var(--page-2);border-radius:0 var(--r-sm) var(--r-sm) 0">
      ${r.cover_note.map(l => esc(l)).join('<br>')}
    </blockquote>
    <div class="tablewrap" style="margin-top:var(--s5)">
      <table><caption>Every table requested, and whether it has been populated.</caption>
      <thead><tr><th>Section</th><th>Table</th><th class="num">Filled</th><th>Status</th></tr></thead>
      <tbody>${rows}</tbody></table>
    </div>`;
  sec.appendChild(panel);
  host.appendChild(sec);
}

/* ====================== 07 — sources, say, glossary ==================== */
const GLOSSARY = [
  ['Fiscal year (FY)', 'The town’s budget year runs 1 July to 30 June. FY2027 means the year ending 30 June 2027.'],
  ['General Fund', 'The main account for services paid out of taxes — police, fire, streets, parks, planning, administration.'],
  ['Fund balance', 'Savings. Money not spent in prior years, held for emergencies and cash flow. The town aims to keep it at no less than 50% of a year’s spending.'],
  ['Property tax rate', 'Charged in cents per $100 of assessed value. At 51.3 cents, a $100,000 home pays $513 a year to the town. That is 0.513% — not 51.3%.'],
  ['Ad valorem tax', 'Latin for “according to value” — the property tax.'],
  ['Revenue-neutral rate', 'After a revaluation raises property values, this is the rate that would bring in the same total revenue as before. A rate above it is an effective increase even if the cents figure looks lower.'],
  ['ERU', 'Equivalent Residential Unit — the unit the stormwater fee is charged in, based on hard surface area that sheds rain.'],
  ['Enterprise fund', 'A fund paid for by fees from the people who use the service rather than by taxes. The Water & Sewer and Stormwater funds are these.'],
  ['Basis: budget / estimate / projection / actual', 'A budget is the plan adopted. An estimate is where the year is expected to land. A projection is a later year in the plan. An actual is audited and final. They are not interchangeable, and this site never mixes them.'],
  ['ACFR', 'Annual Comprehensive Financial Report — the audited yearly accounts, produced by an outside auditor after the year ends.'],
];

function renderSources(host) {
  const docs = state.data.documents.documents, sum = state.data.documents.summary;
  const sec = section('sources', '07', 'Sources, method and plain English',
    `Every figure on this page traces to one of these documents. Where the town has published a
     document itself, that is the copy worth reading — linking to it is the next improvement to this
     site.`);

  // civic participation first — it is the actionable part
  const part = (state.data.household && state.data.household.civic_participation) || [];
  if (part.length) {
    const p = document.createElement('div');
    p.className = 'panel panel-pad';
    p.style.marginBottom = 'var(--s5)';
    p.innerHTML = `<h3 style="margin:0 0 var(--s3);font-size:var(--t-base);font-weight:640">
        Have your say</h3>
      <p style="margin:0 0 var(--s4);font-size:var(--t-sm);color:var(--text-secondary)">
        The budget is adopted by the mayor and Board of Commissioners, and the process includes
        public hearings. Dates below are as printed in the FY2027 budget message — confirm them
        against the town's current meeting calendar before relying on them.</p>
      <ul class="rows" style="margin:0">${part.map(e =>
        `<li><span class="k">${esc(e.event)}</span>
          <span class="v">${esc(e.date_stated)}</span></li>`).join('')}</ul>`;
    sec.appendChild(p);
  }

  const rows = docs.slice().sort((a, b) =>
    (a.category || '').localeCompare(b.category) || a.filename.localeCompare(b.filename))
    .map(d => {
      const badge = d.format !== 'pdf'
        ? `<span class="badge">${esc(d.format)}</span>`
        : d.values_extractable
          ? `<span class="badge ok">digital text</span>`
          : `<span class="badge warn">scanned — OCR unreliable</span>`;
      return `<tr><td>${esc(d.filename)}</td><td>${esc(d.category)}</td>
        <td class="num">${d.fiscal_year || '—'}</td><td class="num">${d.pages || '—'}</td>
        <td class="num">${(d.bytes / 1048576).toFixed(1)} MB</td><td>${badge}</td>
        <td class="mono" title="${esc(d.sha256 || '')}">${esc((d.sha256 || '').slice(0, 10))}</td></tr>`;
    }).join('');

  const dp = document.createElement('div');
  dp.className = 'panel panel-pad';
  dp.innerHTML = `<p style="margin:0 0 var(--s4);font-size:var(--t-sm);color:var(--text-secondary)">
      ${sum.unique_documents} unique documents (${sum.duplicate_copies_in_archive} duplicate copies in
      the original archive were collapsed). <strong>${sum.pdf_digital_text}</strong> have real digital
      text and are safe to read figures from; <strong>${sum.pdf_scanned_ocr}</strong> are scans whose
      character recognition transposes digits, so no figure here is taken from them. The first 10
      characters of each SHA-256 are shown — the full hash is in
      <span class="mono">data/datasets/documents.json</span>.</p>
    <div class="tablewrap"><table>
      <caption>The documents behind every number on this page.</caption>
      <thead><tr><th>File</th><th>Category</th><th class="num">FY</th><th class="num">Pages</th>
        <th class="num">Size</th><th>Text</th><th>SHA-256</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  sec.appendChild(dp);

  const g = document.createElement('div');
  g.className = 'panel panel-pad';
  g.style.marginTop = 'var(--s5)';
  g.innerHTML = `<h3 style="margin:0 0 var(--s5);font-size:var(--t-base);font-weight:640">
      Budget words, in plain English</h3>
    <dl class="gloss">${GLOSSARY.map(([t, d]) =>
      `<div><dt>${esc(t)}</dt><dd>${esc(d)}</dd></div>`).join('')}</dl>`;
  sec.appendChild(g);

  host.appendChild(sec);
}

/* ================================ render =============================== */
let firstPaint = true;
function render() {
  const main = $('#main');
  main.innerHTML = '';
  renderHousehold(main);
  renderBudget(main);
  renderTrends(main);
  renderProjections(main);
  renderAhead(main);
  renderRequest(main);
  renderSources(main);
  if (firstPaint) { setupScrollSpy(); firstPaint = false; }
}

/** Highlight the nav link for the section currently in view. */
function setupScrollSpy() {
  const links = $$('#navLinks a');
  const byId = new Map(links.map(a => [a.getAttribute('href').slice(1), a]));
  const obs = new IntersectionObserver(entries => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      links.forEach(a => a.removeAttribute('aria-current'));
      const a = byId.get(e.target.id);
      if (a) a.setAttribute('aria-current', 'true');
    }
  }, { rootMargin: '-45% 0px -50% 0px' });
  byId.forEach((_, id) => {
    const el = document.getElementById(id);
    if (el) obs.observe(el);
  });
}

/* ================================= boot ================================ */
async function boot() {
  try {
    const idx = await (await fetch('data/index.json')).json();
    const names = ['facts', 'metrics', 'documents', 'projections', 'requests', 'issues', 'household'];
    const loaded = await Promise.all(names.map(n => idx.datasets[n]
      ? fetch('data/' + idx.datasets[n]).then(r => r.json()) : Promise.resolve(null)));
    state.data = Object.fromEntries(names.map((n, i) => [n, loaded[i]]));
    state.data.index = idx;

    const ys = state.data.facts.facts.map(f => f.fiscal_year).filter(v => v != null);
    state.yearMin = Math.min(...ys);
    state.yearMax = Math.max(...ys);

    $('#loading').remove();
    render();

    $('#chipCount').textContent =
      `${idx.counts.facts} figures · ${idx.counts.documents} documents`;

    const c = idx.counts;
    $('#verifyList').innerHTML = [
      ['Published figures', c.facts, ''],
      ['Source documents', c.documents, ''],
      ['With digital text', c.documents_with_trustworthy_text, ''],
      ['Scanned — excluded', c.documents_scanned_needing_transcription, 'warn'],
      ['Cross-document checks', c.multi_document_comparisons, ''],
    ].map(([k, v, cls]) =>
      `<div class="vr"><dt>${esc(k)}</dt><dd class="${cls}">${v}</dd></div>`).join('');
    $('#footMeta').textContent =
      `${idx.counts.facts} published figures · ${idx.counts.metrics} measures · ` +
      `${idx.counts.documents} source documents · ` +
      `${idx.counts.documents_with_trustworthy_text} with digital text · ` +
      `${idx.counts.documents_scanned_needing_transcription} scanned and pending transcription.`;
  } catch (err) {
    $('#loading').textContent =
      'Could not load the published data. If you opened index.html straight from disk, the browser ' +
      'blocks the fetch — serve the folder over HTTP instead (make serve).';
    console.error(err);
  }
}

/* theme toggle — persisted, and it wins over the OS setting in both directions */
$('#themeToggle').addEventListener('click', () => {
  const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('hoa-theme', next); } catch (e) {}
});

boot();
