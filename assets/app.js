/* Hillsborough / Orange County fiscal transparency — client-side analytics.
 *
 * All computation happens here in the browser against the published JSON, so
 * adding a fact to the pipeline changes the site with no code edit.
 *
 * Charting rules this file follows deliberately (from the dataviz method):
 *   - never a dual axis; two units means two charts
 *   - diverging blue/red only where the data has real polarity (surplus/deficit)
 *   - single-series charts get no legend box; the title names the series
 *   - values are labelled selectively (endpoint / extreme), never every point
 *   - every chart ships a table twin, which is also the relief for the one
 *     palette slot below 3:1 contrast
 *   - text never wears the series colour
 */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const state = { yearMin: null, yearMax: null, data: null };

/* ---------------------------------------------------------------- formatters */
const usd = n => '$' + Math.round(n).toLocaleString('en-US');
const usdSigned = n => (n < 0 ? '−' : '') + '$' + Math.abs(Math.round(n)).toLocaleString('en-US');
const compact = n => {
  const a = Math.abs(n);
  const s = n < 0 ? '−' : '';
  if (a >= 1e9) return s + '$' + (a / 1e9).toFixed(2) + 'B';
  if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(a >= 1e7 ? 1 : 2) + 'M';
  if (a >= 1e3) return s + '$' + Math.round(a / 1e3) + 'K';
  return s + '$' + Math.round(a);
};
const pct = n => (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(n).toFixed(1) + '%';
const pctPlain = n => n.toFixed(n % 1 === 0 ? 0 : 1) + '%';
/* A tax rate is cents per $100 of value, NOT a percentage. Labelling 51.3 cents
 * as "51.3%" would overstate the rate by a factor of ~19.5 to anyone skimming. */
const cents = n => n.toFixed(n % 1 === 0 ? 0 : 1);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* --------------------------------------------------------------- data access */
function docsById() {
  const m = new Map();
  for (const d of state.data.documents.documents) m.set(d.id, d);
  return m;
}
// Recency of the *document*, so "the latest reading for a year" is well defined.
function docYear(id) {
  const d = docsById().get(id);
  return (d && d.fiscal_year) || 0;
}
function facts(metric) {
  return state.data.facts.facts.filter(f => f.metric === metric);
}
function inRange(f) {
  if (f.fiscal_year == null) return true;
  return f.fiscal_year >= state.yearMin && f.fiscal_year <= state.yearMax;
}
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
function cite(f) {
  const d = docsById().get(f.source_doc);
  const name = d ? d.filename : f.source_doc;
  const pg = f.source_page ? `, p.${f.source_page}` : '';
  const label = esc(name + pg);
  if (d && d.official_url) return `<a class="src-link" href="${esc(d.official_url)}">${label}</a>`;
  return `<span class="src-link" title="Source file recorded in data/datasets/documents.json">${label}</span>`;
}

/* ------------------------------------------------------------------- tooltip */
const tip = Object.assign(document.createElement('div'), { id: 'tip' });
document.body.appendChild(tip);
function showTip(html, ev) {
  tip.innerHTML = html;
  tip.classList.add('on');
  const r = tip.getBoundingClientRect();
  let x = ev.clientX + 14, y = ev.clientY - 10;
  if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
  if (y + r.height > innerHeight - 8) y = innerHeight - r.height - 8;
  tip.style.left = Math.max(8, x) + 'px';
  tip.style.top = Math.max(8, y) + 'px';
}
const hideTip = () => tip.classList.remove('on');
/** Attach hover + keyboard focus to a hit target. Focus shows the same as hover. */
function bindTip(el, html) {
  el.addEventListener('mouseenter', e => showTip(html, e));
  el.addEventListener('mousemove', e => showTip(html, e));
  el.addEventListener('mouseleave', hideTip);
  el.setAttribute('tabindex', '0');
  el.addEventListener('focus', e => {
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
  const span = hi - lo, raw = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(raw) || 1)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw) || mag * 10;
  const out = [];
  for (let v = Math.floor(lo / step) * step; v <= hi + step * 0.5; v += step) out.push(+v.toFixed(6));
  return out;
}

const M = { t: 20, r: 74, b: 36, l: 62 };
const W = 700, H = 262;

function frame(cls) {
  const svg = mk('svg', {
    class: 'chart ' + (cls || ''), viewBox: `0 0 ${W} ${H}`,
    role: 'img', preserveAspectRatio: 'xMidYMid meet'
  });
  return svg;
}
function yAxis(svg, ticks, y, fmt) {
  for (const t of ticks) {
    const yy = y(t);
    svg.appendChild(mk('line', { class: 'gridline', x1: M.l, x2: W - M.r, y1: yy, y2: yy }));
    const lab = mk('text', { class: 'tick', x: M.l - 9, y: yy + 4, 'text-anchor': 'end' });
    lab.textContent = fmt(t);
    svg.appendChild(lab);
  }
}
function xLabels(svg, items, cx, label) {
  for (const it of items) {
    const t = mk('text', { class: 'tick', x: cx(it), y: H - M.b + 17, 'text-anchor': 'middle' });
    t.textContent = label(it);
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

/* ============================ chart: diverging columns ==================== */
function chartSurplus() {
  const rows = latestByYear('general_fund_surplus_deficit').filter(inRange);
  if (!rows.length) return null;
  const vals = rows.map(r => r.value);
  const ticks = niceTicks(Math.min(0, ...vals), Math.max(0, ...vals), 4);
  const lo = Math.min(...ticks), hi = Math.max(...ticks);
  const y = v => M.t + (hi - v) / (hi - lo) * (H - M.t - M.b);
  const bandW = (W - M.l - M.r) / rows.length;
  const bw = Math.min(24, bandW * 0.5);
  const cx = r => M.l + bandW * (rows.indexOf(r) + 0.5);

  const svg = frame();
  svg.appendChild(mk('title', {})).textContent =
    'General Fund surplus or deficit by fiscal year';
  yAxis(svg, ticks, y, v => compact(v));

  const zero = y(0);
  svg.appendChild(mk('line', { class: 'axisline', x1: M.l, x2: W - M.r, y1: zero, y2: zero }));

  for (const r of rows) {
    const up = r.value >= 0;
    const h = Math.abs(y(r.value) - zero);
    const x = cx(r) - bw / 2;
    svg.appendChild(mk('path', {
      d: barPath(x, up ? zero - h : zero, bw, h, 4, up),
      fill: up ? 'var(--pos)' : 'var(--neg)'
    }));
    // value on the cap, outside the bar so it can never be clipped
    const lab = mk('text', {
      class: 'dlabel', x: cx(r), 'text-anchor': 'middle',
      y: up ? zero - h - 7 : zero + h + 15
    });
    lab.textContent = compact(r.value);
    svg.appendChild(lab);

    const hit = mk('rect', {
      class: 'hit', x: cx(r) - Math.max(12, bandW / 2), y: M.t,
      width: Math.max(24, bandW), height: H - M.t - M.b
    });
    bindTip(hit, `<div class="t">FY${r.fiscal_year}</div>
      <div class="r">Surplus / (deficit): <b>${usdSigned(r.value)}</b></div>
      <div class="r">Basis: ${esc(r.basis || '—')}</div>
      <div class="src">${cite(r)}</div>`);
    svg.appendChild(hit);
  }
  xLabels(svg, rows, cx, r => 'FY' + r.fiscal_year);

  const table = () => tableOf('General Fund surplus / (deficit). Negative values are deficits.',
    [{ label: 'Fiscal year' }, { label: 'Amount', num: true }, { label: 'Basis' }, { label: 'Source' }],
    rows.map(r => ['FY' + r.fiscal_year, usdSigned(r.value), esc(r.basis || '—'), cite(r)]));

  return card('General Fund surplus and deficit',
    'The most recent figure the town has published for each year. Bars below the line are deficits.',
    svg, null, table);
}

/* ================================ chart: line ============================= */
function chartLine(metric, title, note, fmtV, refLine) {
  const rows = latestByYear(metric).filter(inRange);
  if (rows.length < 2) return null;
  const vals = rows.map(r => r.value);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (refLine != null) { lo = Math.min(lo, refLine); hi = Math.max(hi, refLine); }
  const pad = (hi - lo) * 0.15 || 1;
  const ticks = niceTicks(Math.max(0, lo - pad), hi + pad, 4);
  const tlo = Math.min(...ticks), thi = Math.max(...ticks);
  const y = v => M.t + (thi - v) / (thi - tlo) * (H - M.t - M.b);
  const bandW = (W - M.l - M.r) / rows.length;
  const cx = r => M.l + bandW * (rows.indexOf(r) + 0.5);

  const svg = frame();
  svg.appendChild(mk('title', {})).textContent = title;
  yAxis(svg, ticks, y, fmtV);

  if (refLine != null) {
    svg.appendChild(mk('line', {
      class: 'reference', x1: M.l, x2: W - M.r, y1: y(refLine), y2: y(refLine)
    }));
    const rl = mk('text', { class: 'reflabel', x: W - M.r + 6, y: y(refLine) + 4 });
    rl.textContent = `${fmtV(refLine)} floor`;
    svg.appendChild(rl);
  }

  const d = rows.map((r, i) => `${i ? 'L' : 'M'}${cx(r)} ${y(r.value)}`).join(' ');
  svg.appendChild(mk('path', {
    d, fill: 'none', stroke: 'var(--series-1)', 'stroke-width': 2,
    'stroke-linejoin': 'round', 'stroke-linecap': 'round'
  }));

  rows.forEach((r, i) => {
    // 2px surface ring keeps the marker legible where it crosses the line
    svg.appendChild(mk('circle', {
      cx: cx(r), cy: y(r.value), r: 4.5,
      fill: 'var(--series-1)', stroke: 'var(--surface-1)', 'stroke-width': 2
    }));
    if (i === rows.length - 1) {
      const lab = mk('text', { class: 'dlabel', x: cx(r) + 10, y: y(r.value) + 4 });
      lab.textContent = fmtV(r.value);
      svg.appendChild(lab);
    }
    const hit = mk('rect', {
      class: 'hit', x: cx(r) - Math.max(12, bandW / 2), y: M.t,
      width: Math.max(24, bandW), height: H - M.t - M.b
    });
    bindTip(hit, `<div class="t">FY${r.fiscal_year}</div>
      <div class="r"><b>${fmtV(r.value)}</b></div>
      <div class="r">Basis: ${esc(r.basis || '—')}</div>
      <div class="src">${cite(r)}</div>`);
    svg.appendChild(hit);
  });
  xLabels(svg, rows, cx, r => 'FY' + r.fiscal_year);

  const table = () => tableOf(title,
    [{ label: 'Fiscal year' }, { label: 'Value', num: true }, { label: 'Basis' }, { label: 'Source' }],
    rows.map(r => ['FY' + r.fiscal_year, fmtV(r.value), esc(r.basis || '—'), cite(r)]));

  return card(title, note, svg, null, table);
}

/* ============================== chart: dumbbell ========================== */
/** Before -> after per item. One hue, two ordinal steps. */
function chartDumbbell(items, title, note, fmtV, labels) {
  if (!items.length) return null;
  const all = items.flatMap(i => [i.a, i.b]);
  const ticks = niceTicks(Math.min(0, ...all), Math.max(...all), 4);
  const tlo = Math.min(...ticks), thi = Math.max(...ticks);
  const h = Math.max(150, 46 * items.length + M.t + M.b);
  const svg = mk('svg', {
    class: 'chart', viewBox: `0 0 ${W} ${h}`, role: 'img',
    preserveAspectRatio: 'xMidYMid meet'
  });
  const L = 150, R = 96;
  const x = v => L + (v - tlo) / (thi - tlo) * (W - L - R);
  const bandH = (h - M.t - M.b) / items.length;
  const cy = i => M.t + bandH * (i + 0.5);

  svg.appendChild(mk('title', {})).textContent = title;
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
    const name = mk('text', { class: 'tick', x: L - 12, y: yy + 4, 'text-anchor': 'end' });
    name.textContent = it.label;
    svg.appendChild(name);

    const delta = it.b - it.a;
    const dl = mk('text', {
      class: 'dlabel', x: Math.max(x(it.a), x(it.b)) + 11, y: yy + 4
    });
    dl.textContent = (delta >= 0 ? '+' : '−') + fmtV(Math.abs(delta)).replace('$', '$');
    svg.appendChild(dl);

    const hit = mk('rect', {
      class: 'hit', x: L - 140, y: yy - Math.max(12, bandH / 2),
      width: W - L + 140 - 8, height: Math.max(24, bandH)
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

/* =============================== chart: columns =========================== */
function chartColumns(rows, title, note, fmtV) {
  if (!rows.length) return null;
  const ticks = niceTicks(0, Math.max(...rows.map(r => r.value)), 4);
  const thi = Math.max(...ticks);
  const y = v => M.t + (thi - v) / thi * (H - M.t - M.b);
  const bandW = (W - M.l - M.r) / rows.length;
  const bw = Math.min(24, bandW * 0.5);
  const cx = i => M.l + bandW * (i + 0.5);
  const svg = frame();
  svg.appendChild(mk('title', {})).textContent = title;
  yAxis(svg, ticks, y, fmtV);
  const base = y(0);
  svg.appendChild(mk('line', { class: 'axisline', x1: M.l, x2: W - M.r, y1: base, y2: base }));

  rows.forEach((r, i) => {
    const hh = base - y(r.value);
    svg.appendChild(mk('path', {
      d: barPath(cx(i) - bw / 2, y(r.value), bw, hh, 4, true), fill: 'var(--series-1)'
    }));
    const lab = mk('text', { class: 'dlabel', x: cx(i), y: y(r.value) - 7, 'text-anchor': 'middle' });
    lab.textContent = fmtV(r.value);
    svg.appendChild(lab);
    const hit = mk('rect', {
      class: 'hit', x: cx(i) - Math.max(12, bandW / 2), y: M.t,
      width: Math.max(24, bandW), height: H - M.t - M.b
    });
    bindTip(hit, `<div class="t">FY${r.fiscal_year}</div>
      <div class="r"><b>${fmtV(r.value)}</b></div>
      <div class="src">${cite(r)}</div>`);
    svg.appendChild(hit);
  });
  xLabels(svg, rows.map((r, i) => i), i => cx(i), i => 'FY' + rows[i].fiscal_year);

  const table = () => tableOf(title,
    [{ label: 'Fiscal year' }, { label: 'Value', num: true }, { label: 'Source' }],
    rows.map(r => ['FY' + r.fiscal_year, fmtV(r.value), cite(r)]));
  return card(title, note, svg, null, table);
}

/* ============================== the calculator ============================ */
function renderCalculator(host) {
  const rateF = one('property_tax_rate');
  const perCentF = one('revenue_per_cent_of_tax_rate');
  const housingCents = one('capital_projects_tax_rate_equivalent_cents');
  if (!rateF) return;

  const sec = document.createElement('section');
  sec.innerHTML = `
    <h2>What the town's share costs you</h2>
    <p class="sub">
      The town's property tax rate is <strong>${cents(rateF.value)}&nbsp;cents per $100</strong>
      of assessed value (${esc(rateF.basis)}, FY${rateF.fiscal_year}). Enter what your home is
      assessed at and this works out the town's portion of your bill.
      This is the <em>town</em> rate only — your full bill also includes Orange County and any
      special district, which are not in this dataset.
    </p>
    <div class="card hero">
      <div>
        <label class="field" for="hv">Assessed home value</label>
        <input type="number" id="hv" min="0" step="5000" value="400000" inputmode="numeric">
        <input type="range" id="hvr" min="50000" max="1500000" step="5000" value="400000"
               aria-label="Assessed home value slider">
        <ul class="breakdown" id="bd"></ul>
      </div>
      <div>
        <p class="hero-label">Estimated annual town property tax</p>
        <div class="hero-figure" id="heroV">—</div>
        <p class="hero-note" id="heroN"></p>
      </div>
    </div>`;
  host.appendChild(sec);

  const num = $('#hv', sec), rng = $('#hvr', sec);
  const draw = () => {
    const v = Math.max(0, +num.value || 0);
    const rate = rateF.value / 100;              // cents -> dollars per $100
    const annual = v / 100 * rate;
    $('#heroV', sec).textContent = usd(annual);
    $('#heroN', sec).innerHTML =
      `That is ${usd(annual / 12)} a month at the FY${rateF.fiscal_year} rate of ` +
      `${cents(rateF.value)} cents per $100. Source: ${cite(rateF)}.`;

    const oneCent = v / 100 * 0.01;
    const items = [
      ['One cent on the tax rate, to you', usd(oneCent) + ' / yr'],
    ];
    if (perCentF) items.push(['One cent on the tax rate, town-wide',
      usd(perCentF.value) + ' raised']);
    const need = one('tax_rate_increase_needed_cents');
    if (need) items.push([
      `A ${cents(need.value)}-cent rise (the town's FY${need.fiscal_year} scenario)`,
      '+' + usd(oneCent * need.value) + ' / yr']);
    if (housingCents) items.push([
      `Major capital projects (${cents(housingCents.value)} cents)`,
      usd(oneCent * housingCents.value) + ' / yr']);

    $('#bd', sec).innerHTML = items.map(([k, val]) =>
      `<li><span class="k">${esc(k)}</span><span class="v">${esc(val)}</span></li>`).join('');
  };
  num.addEventListener('input', () => { rng.value = num.value; draw(); });
  rng.addEventListener('input', () => { num.value = rng.value; draw(); });
  draw();
}

/* ================================== KPIs ================================= */
function renderKpis(host) {
  const defs = [
    ['total_budget', 'Total budget, all funds', compact],
    ['general_fund_expenditures', 'General Fund', compact],
    ['general_fund_balance_pct_of_expenditures', 'Savings as % of spending', pctPlain],
    ['general_fund_surplus_deficit', 'Deficit, latest projection', compact],
  ];
  const tiles = [];
  for (const [metric, label, fmt] of defs) {
    let f;
    if (metric === 'general_fund_surplus_deficit') {
      const rows = latestByYear(metric);
      f = rows.length ? rows[rows.length - 1] : null;
    } else f = one(metric);
    if (!f) continue;
    tiles.push(`<div class="tile">
      <p class="k">${esc(label)}</p>
      <div class="v">${esc(fmt(f.value))}</div>
      <p class="d">FY${f.fiscal_year} · ${esc(f.basis || '')}</p>
    </div>`);
  }
  const sec = document.createElement('section');
  sec.innerHTML = `<h2>The headline numbers</h2>
    <p class="sub">Each tile is the most recent published figure for that measure. Hover any chart
    below for the document and page a number came from.</p>
    <div class="kpis">${tiles.join('')}</div>`;
  host.appendChild(sec);
}

/* ============================ projection drift ============================ */
function renderDrift(host) {
  const cmps = state.data.projections.comparisons.filter(c =>
    c.metric === 'general_fund_balance_available_cash' &&
    c.fiscal_year >= state.yearMin && c.fiscal_year <= state.yearMax);
  if (!cmps.length) return;
  const items = cmps.map(c => {
    const rs = [...c.readings].sort((a, b) => docYear(a.source_doc) - docYear(b.source_doc));
    return {
      label: 'FY' + c.fiscal_year, a: rs[0].value, b: rs[rs.length - 1].value,
      src: rs.map(r => esc(r.source_doc) + (r.source_page ? ` p.${r.source_page}` : ''))
        .join(' → ')
    };
  });
  const sec = document.createElement('section');
  sec.innerHTML = `<h2>How the town's own projections moved</h2>
    <p class="sub">
      Hillsborough publishes a three-year financial plan, so the same fiscal year appears in
      several budget documents. This compares what an earlier document projected for a year with
      what a later document reported for that same year. The gap is not an error — a projection
      and a budget are different things, and the town's FY2025 message says plainly that it
      budgets conservatively and that most years "end up with deficits less than projected."
      It is shown because it is the honest measure of how much weight a projection deserves.
    </p>`;
  const c = chartDumbbell(items, 'General Fund savings: first projection vs latest figure',
    'Each row is one fiscal year. The line spans the earlier and later readings.',
    compact, ['Earlier document', 'Later document']);
  if (c) sec.appendChild(c);
  host.appendChild(sec);
}

/* ========================== the records request =========================== */
function renderRequest(host) {
  const r = state.data.requests;
  const s = r.summary;
  const filledPct = s.data_cells_requested ? s.data_cells_provided / s.data_cells_requested * 100 : 0;
  const sec = document.createElement('section');
  const rowsHtml = r.tables.map(t => {
    const ico = t.status === 'answered' ? '✓' : t.status === 'partial' ? '○' : '✕';
    return `<tr>
      <td>${esc(t.section || '—')}</td>
      <td>${esc(t.title)}</td>
      <td class="num">${t.cells_provided} / ${t.cells_expected}</td>
      <td><span class="status ${esc(t.status)}"><span class="ico" aria-hidden="true">${ico}</span>
        ${esc(t.status)}</span></td>
    </tr>`;
  }).join('');

  sec.innerHTML = `<h2>The open records request</h2>
    <p class="sub">
      The initiative sent the Town of Hillsborough a workbook asking for staffing, utility,
      capital-project, debt, revenue and affordable-housing figures on a consistent basis. In the
      copy held in this archive, this much has been filled in:
    </p>
    <div class="card">
      <div class="meter">
        <div class="track"><div class="fill" style="width:${Math.max(0.6, filledPct).toFixed(1)}%"></div></div>
        <div class="cap">
          <span><strong>${s.data_cells_provided}</strong> of
            <strong>${s.data_cells_requested}</strong> requested figures provided</span>
          <span>${filledPct.toFixed(1)}%</span>
        </div>
      </div>
      <p class="sub" style="margin:16px 0 0">
        ${s.tables_unanswered} of ${s.tables_requested} requested tables are still entirely blank.
        This reflects the file in this archive at the time it was collected — it is a status
        snapshot, not a finding that the town declined to respond.
      </p>
      <blockquote style="margin:16px 0 0;padding-left:14px;border-left:3px solid var(--grid);
        color:var(--text-secondary);font-size:14px">
        ${r.cover_note.map(l => esc(l)).join('<br>')}
      </blockquote>
      <div class="tablewrap" style="margin-top:18px">
        <table><caption>Every table requested, and whether it has been populated.</caption>
        <thead><tr><th>Section</th><th>Table</th><th class="num">Filled</th><th>Status</th></tr></thead>
        <tbody>${rowsHtml}</tbody></table>
      </div>
    </div>`;
  host.appendChild(sec);
}

/* ============================ capital projects =========================== */
function renderProjects(host) {
  const ps = state.data.requests.projects_with_cost_changes
    .filter(p => p.original_budget_usd != null && p.current_budget_usd != null);
  if (!ps.length) return;
  const items = ps.map(p => ({
    label: p.project, a: p.original_budget_usd, b: p.current_budget_usd,
    src: 'Data request workbook, Project Cost Changes'
  }));
  const sec = document.createElement('section');
  sec.innerHTML = `<h2>Capital projects: budget then, budget now</h2>
    <p class="sub">
      Two projects the initiative has tracked cost growth on. These figures come from the
      initiative's own workbook rather than an audited statement, so they are published as
      claims to verify. The Dam Repair row is the striking one:
      <strong>${pctPlain(ps.find(p => /dam/i.test(p.project)) ?
        ps.find(p => /dam/i.test(p.project)).increase_pct : 0)}</strong> growth.
    </p>`;
  const c = chartDumbbell(items, 'Original budget vs current budget',
    'Each row is one project.', compact, ['Original budget', 'Current budget']);
  if (c) sec.appendChild(c);
  host.appendChild(sec);
}

/* ============================== source documents ========================= */
function renderDocs(host) {
  const docs = state.data.documents.documents;
  const sum = state.data.documents.summary;
  const rows = docs.slice().sort((a, b) =>
    (a.category || '').localeCompare(b.category) || a.filename.localeCompare(b.filename))
    .map(d => {
      const ok = d.values_extractable;
      const badge = d.format !== 'pdf'
        ? `<span class="badge">${esc(d.format)}</span>`
        : ok ? `<span class="badge ok">digital text</span>`
             : `<span class="badge warn">scanned — OCR unreliable</span>`;
      return `<tr>
        <td>${esc(d.filename)}</td>
        <td>${esc(d.category)}</td>
        <td class="num">${d.fiscal_year || '—'}</td>
        <td class="num">${d.pages || '—'}</td>
        <td class="num">${(d.bytes / 1048576).toFixed(1)} MB</td>
        <td>${badge}</td>
        <td class="mono" title="${esc(d.sha256 || '')}">${esc((d.sha256 || '').slice(0, 10))}</td>
      </tr>`;
    }).join('');

  const sec = document.createElement('section');
  sec.innerHTML = `<h2>Source documents</h2>
    <p class="sub">
      ${sum.unique_documents} unique documents (${sum.duplicate_copies_in_archive} duplicate copies
      in the original archive were collapsed). ${sum.pdf_digital_text} have real digital text and
      are safe to read figures from; ${sum.pdf_scanned_ocr} are scans whose character recognition
      transposes digits, so no figure on this site is taken from them. The first 10 characters of
      each file's SHA-256 are shown; the full hash is in
      <span class="mono">data/datasets/documents.json</span>.
    </p>
    <div class="card"><div class="tablewrap"><table>
      <caption>The documents behind every number on this page.</caption>
      <thead><tr><th>File</th><th>Category</th><th class="num">FY</th><th class="num">Pages</th>
        <th class="num">Size</th><th>Text</th><th>SHA-256</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`;
  host.appendChild(sec);
}

/* ================================= filters =============================== */
function renderFilters(host, years) {
  const opts = ys => ys.map(y => `<option value="${y}">FY${y}</option>`).join('');
  const sec = document.createElement('div');
  sec.className = 'filters';
  sec.innerHTML = `
    <div class="f"><label class="field" for="ymin">From fiscal year</label>
      <select id="ymin">${opts(years)}</select></div>
    <div class="f"><label class="field" for="ymax">To fiscal year</label>
      <select id="ymax">${opts(years)}</select></div>
    <p class="hint">This range scopes every chart below. Beyond FY2027 the figures are the town's
      own multi-year projections, not budgets.</p>`;
  host.appendChild(sec);
  const a = $('#ymin', sec), b = $('#ymax', sec);
  a.value = state.yearMin; b.value = state.yearMax;
  const on = () => {
    state.yearMin = Math.min(+a.value, +b.value);
    state.yearMax = Math.max(+a.value, +b.value);
    a.value = state.yearMin; b.value = state.yearMax;
    render();
  };
  a.addEventListener('change', on);
  b.addEventListener('change', on);
}

/* ================================== render =============================== */
function render() {
  const main = $('#main');
  main.innerHTML = '';
  const years = [...new Set(state.data.facts.facts
    .map(f => f.fiscal_year).filter(v => v != null))].sort((x, y) => x - y);

  renderCalculator(main);
  renderKpis(main);

  const charts = document.createElement('section');
  charts.innerHTML = `<h2>Budget, savings and deficits</h2>
    <p class="sub">Savings in dollars and savings as a share of spending are different measures,
    so they get separate charts rather than being stacked on one plot with two scales.</p>`;
  main.appendChild(charts);
  renderFilters(charts, years);

  const grid = document.createElement('div');
  grid.className = 'grid2';
  const built = [
    chartSurplus(),
    chartLine('general_fund_balance_available_cash', 'General Fund savings (available cash)',
      'The town’s cash reserve.', compact),
    chartLine('general_fund_balance_pct_of_expenditures', 'Savings as a share of yearly spending',
      'The town states its aim is to stay no lower than 50%.', pctPlain, 50),
    chartColumns(latestByYear('admin_spend_total').filter(inRange),
      'Administrative spending', 'Figures supplied by a county commissioner, not audited.', compact),
  ].filter(Boolean);
  built.forEach(c => grid.appendChild(c));
  charts.appendChild(grid);

  renderDrift(main);
  renderProjects(main);
  renderRequest(main);
  renderDocs(main);
}

/* ================================== boot ================================= */
async function boot() {
  try {
    const idx = await (await fetch('data/index.json')).json();
    const names = ['facts', 'metrics', 'documents', 'projections', 'requests', 'issues'];
    const loaded = await Promise.all(names.map(n =>
      fetch('data/' + idx.datasets[n]).then(r => r.json())));
    state.data = Object.fromEntries(names.map((n, i) => [n, loaded[i]]));
    state.data.index = idx;

    const ys = state.data.facts.facts.map(f => f.fiscal_year).filter(v => v != null);
    state.yearMin = Math.min(...ys);
    state.yearMax = Math.max(...ys);

    $('#loading').remove();
    render();

    $('#footMeta').textContent =
      `${idx.counts.facts} published figures · ${idx.counts.documents} source documents · ` +
      `${idx.counts.documents_with_trustworthy_text} with digital text · ` +
      `${idx.counts.documents_scanned_needing_transcription} scanned and pending transcription.`;
  } catch (err) {
    $('#loading').textContent =
      'Could not load the published data. If you are opening index.html straight from disk, ' +
      'a browser will block the fetch — serve the folder over HTTP instead ' +
      '(for example: python3 -m http.server).';
    console.error(err);
  }
}

/* theme toggle must win over the OS setting in both directions */
$('#themeToggle').addEventListener('click', () => {
  const cur = document.documentElement.getAttribute('data-theme');
  const dark = cur ? cur === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.setAttribute('data-theme', dark ? 'light' : 'dark');
});

boot();
