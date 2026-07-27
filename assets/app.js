/* Your town, your money — resident-facing view of Hillsborough's published budget.
 *
 * Organised around the questions a resident actually has, in order:
 *   what does this cost me -> what does it pay for -> is the money healthy ->
 *   what's coming -> how do I speak up -> where did these numbers come from
 *
 * Personalisation is real, not theatre: the page adapts to the three things the
 * reader tells us (home value, in/out of town, water use), remembers them in
 * localStorage, and weaves them through the copy. It never invents anything
 * about them — there is no address, parcel or neighbourhood data here, and the
 * page says which figures are estimates from their own input.
 *
 * Charting rules kept from the dataviz method: no dual axes; diverging colour
 * only for real polarity; no legend for a single series; selective labels; 2px
 * surface gaps and rings; a table twin for every chart; text never wears the
 * series colour.
 */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;

const DEFAULT_HOME = 400000;   // the town's own worked example, so it is a fair default
/* Amy's household uses about 9,000 gallons a month, and the site used to offer only
 * the town's two published examples — 4,000 ("average") and 2,000 ("low"). Water use
 * is now a real number the reader sets, because the fee schedule gives the whole rate
 * structure and the bill at any consumption is exact rather than extrapolated. */
const DEFAULT_GALLONS = 4000;  // the town's own "average", so the default matches its prose
const GAL_PRESETS = [2000, 4000, 6000, 9000, 12000];
const state = {
  yearMin: null, yearMax: null, data: null,
  homeValue: DEFAULT_HOME, location: 'intown', gallons: DEFAULT_GALLONS, returning: false,
};

/* ------------------------------------------------------- remembered settings */
const STORE = 'hoa-home';
function loadHome() {
  try {
    const raw = localStorage.getItem(STORE);
    if (!raw) return;
    const o = JSON.parse(raw);
    if (typeof o.homeValue === 'number' && o.homeValue > 0) state.homeValue = o.homeValue;
    if (o.location === 'intown' || o.location === 'outoftown') state.location = o.location;
    if (typeof o.gallons === 'number' && o.gallons >= 0) state.gallons = o.gallons;
    // Readers who set a level before water use became a number keep their choice.
    else if (o.useLevel === 'min') state.gallons = 2000;
    else if (o.useLevel === 'avg') state.gallons = 4000;
    state.returning = true;
  } catch (e) { /* private mode, or corrupt value — defaults are fine */ }
}
function saveHome() {
  try {
    localStorage.setItem(STORE, JSON.stringify({
      homeValue: state.homeValue, location: state.location, gallons: state.gallons,
    }));
  } catch (e) { /* nothing here is worth breaking the page over */ }
}

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
/* U+2212 minus, not an ASCII hyphen — matches the dollar figures and aligns in
   tabular-nums columns, where a hyphen sits visibly high and narrow. */
const pctPlain = n => (n < 0 ? '−' : '') + Math.abs(n).toFixed(Math.abs(n) % 1 === 0 ? 0 : 1) + '%';
/* A tax rate is cents per $100 of value, NOT a percentage. Labelling 51.3 cents
   as "51.3%" would overstate the rate ~19.5x to anyone skimming. */
const cents = n => n.toFixed(n % 1 === 0 ? 0 : 1);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* -------------------------------------------------------------- data access */
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
const val = (metric, fb = null) => { const f = one(metric); return f ? f.value : fb; };
const forYear = (metric, fy) => latestByYear(metric).find(f => f.fiscal_year === fy) || null;
function quote(key) {
  const qs = (state.data.household && state.data.household.town_statements) || [];
  return qs.find(q => q.key === key) || null;
}
function cite(f) {
  if (!f) return '';
  const d = docsById().get(f.source_doc);
  const name = d ? d.filename : f.source_doc;
  const label = esc(name + (f.source_page ? `, p.${f.source_page}` : ''));
  if (d && d.official_url) return `<a class="src-link" href="${esc(d.official_url)}">${label}</a>`;
  return `<span class="src-link" title="Source file and SHA-256 recorded in data/datasets/documents.json">${label}</span>`;
}

/* ------------------------------------------------- reporting a problem ------ */
const REPO = 'https://github.com/oc-accountability/hoa-funds';

/** A pre-filled GitHub issue.
 *
 * Pre-filling is the point: a report that arrives already carrying the figure,
 * the document and the page is one somebody can act on. A bare "a number looks
 * wrong" usually cannot be chased down and quietly dies.
 */
function reportUrl(about, detail) {
  const idx = (state.data && state.data.index) || {};
  const body = [
    `**What looks wrong**`,
    ``,
    `<!-- Please describe the problem. If it is a specific figure, the value you`,
    `expected and where you saw the correct one is the most useful thing. -->`,
    ``,
    `---`,
    `**Where on the site**: ${about || 'not specified'}`,
    detail ? `**Figure in question**: ${detail}` : null,
    `**Page**: ${location.href}`,
    idx.counts ? `**Dataset**: ${idx.counts.facts} figures, `
      + `${idx.counts.documents} documents` : null,
    ``,
    `<!-- Reported from the website. Thank you — corrections make this more useful`,
    `for everyone. -->`,
  ].filter(Boolean).join('\n');
  return `${REPO}/issues/new?title=${encodeURIComponent('Possible error: ' + (about || 'website'))}`
    + `&body=${encodeURIComponent(body)}`;
}

/** A small inline "flag this" control for one specific figure. */
function flagButton(about, detail) {
  const a = document.createElement('a');
  a.className = 'flag';
  a.href = reportUrl(about, detail);
  a.target = '_blank';
  a.rel = 'noopener';
  a.textContent = 'report a problem with this';
  return a;
}

/* ------------------------------------------------------------------ tooltip */
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

/* --------------------------------------------------------- svg primitives */
const NS = 'http://www.w3.org/2000/svg';
const mk = (n, a = {}) => {
  const e = document.createElementNS(NS, n);
  for (const k in a) e.setAttribute(k, a[k]);
  return e;
};
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
function titled(svg, text) { const t = mk('title'); t.textContent = text; svg.appendChild(t); }
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

/* ------------------------------------------------------------ chart cards */
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
/** Collapsed detail, so the default view answers the question without a wall of charts. */
function disclosure(label, buildInner) {
  const d = document.createElement('details');
  d.className = 'more';
  const s = document.createElement('summary');
  s.textContent = label;
  d.appendChild(s);
  const inner = document.createElement('div');
  inner.className = 'inner';
  d.appendChild(inner);
  let built = false;
  d.addEventListener('toggle', () => {
    if (d.open && !built) { buildInner(inner); built = true; }
  });
  return d;
}

/* ============================ chart forms ============================= */
function chartSurplus() {
  const rows = latestByYear('general_fund_surplus_deficit').filter(inRange);
  if (!rows.length) return null;
  const vals = rows.map(r => r.value);
  // Pad the domain so the deepest bar never touches the lowest gridline — its
  // label sits below the bar end and would collide with the year labels.
  const ticks = niceTicks(Math.min(0, ...vals) * 1.14, Math.max(0, ...vals) * 1.14, 4);
  const lo = Math.min(...ticks), hi = Math.max(...ticks);
  const y = v => M.t + (hi - v) / (hi - lo) * (H - M.t - M.b);
  const band = (W - M.l - M.r) / rows.length;
  const bw = Math.min(24, band * 0.46);
  const cx = i => M.l + band * (i + 0.5);

  const svg = frame();
  titled(svg, 'General Fund surplus or deficit by year');
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
    [{ label: 'Year' }, { label: 'Amount', num: true }, { label: 'Basis' }, { label: 'Source' }],
    rows.map(r => ['FY' + r.fiscal_year, usdSigned(r.value), esc(r.basis || '—'), cite(r)]));
  return card('Does the town spend more than it takes in?',
    'Bars below the line mean the town plans to spend more than it collects that year, covering the gap from savings.',
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
  svg.appendChild(mk('path', {
    d, fill: 'none', stroke: 'var(--series-1)', 'stroke-width': 2,
    'stroke-linejoin': 'round', 'stroke-linecap': 'round'
  }));
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
    [{ label: 'Year' }, { label: 'Value', num: true }, { label: 'Basis' }, { label: 'Source' }],
    rows.map(r => ['FY' + r.fiscal_year, fmtV(r.value), esc(r.basis || '—'), cite(r)]));
  return card(title, note, svg, null, table);
}

function chartDumbbell(items, title, note, fmtV, labels) {
  if (!items.length) return null;
  const all = items.flatMap(i => [i.a, i.b]);
  // Scale to the data range, not to zero: in a dumbbell the mark POSITION encodes
  // the value and the line encodes the change, so no length is measured from an
  // origin. Forcing zero squeezes clustered values into a corner and hides the
  // very differences the chart exists to show.
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
    [{ label: 'Year' }, { label: 'Value', num: true }, { label: 'Source' }],
    rows.map(r => ['FY' + r.fiscal_year, fmtV(r.value), cite(r)]));
  return card(title, note, svg, null, table);
}

/* ==================== 01 — your bill ==================== */
/** One block-rate bill: a fixed charge for the first N gallons, then a rate per 1,000. */
function blockBill(set, gallons) {
  if (!set) return null;
  const over = Math.max(0, gallons - set.threshold_gallons);
  return set.block1_charge + (over / 1000) * set.block2_per_1000;
}
/**
 * The whole monthly utility bill at the reader's own consumption.
 *
 * The town publishes the *increase* only at 2,000 and 4,000 gallons, which is why this
 * page once offered just those two. Extrapolating between them would have been unsafe
 * if the rates were tiered — but the fee schedule shows two blocks and nothing more,
 * so any consumption computes exactly. Falls back to the published increases if the
 * rate structure is unavailable, so the page degrades rather than breaking.
 */
function utilMonthly() {
  const u = state.data && state.data.utility;
  const g = state.gallons;
  const loc = state.location === 'intown' ? 'inside' : 'outside';
  if (u && u.rate_sets) {
    const w = u.rate_sets[`water_${loc}`], s = u.rate_sets[`sewer_${loc}`];
    if (w && s) {
      const storm = (u.stormwater || {});
      const sNow = (storm.residential_recommended || 0) / 12;
      const sWas = (storm.residential_current || 0) / 12;
      const wNow = blockBill(w.recommended, g), wWas = blockBill(w.current, g);
      const sewNow = blockBill(s.recommended, g), sewWas = blockBill(s.current, g);
      return {
        exact: true, gallons: g,
        waterBill: wNow, sewerBill: sewNow, stormBill: sNow,
        billTotal: wNow + sewNow + sNow,
        water: wNow - wWas, sewer: sewNow - sewWas, storm: sNow - sWas,
        total: (wNow + sewNow + sNow) - (wWas + sewWas + sWas),
      };
    }
  }
  // Published increases are given at 2,000 and 4,000 gallons only; pick the nearer.
  const level = Math.abs(g - 2000) < Math.abs(g - 4000) ? 'min' : 'avg';
  const w = val(`water_bill_increase_monthly_${state.location}_${level}`);
  const s = val(`sewer_bill_increase_monthly_${state.location}_${level}`);
  return { exact: false, gallons: level === 'min' ? 2000 : 4000,
           water: w, sewer: s, total: (w || 0) + (s || 0) };
}
function annualTax() {
  const rate = val('property_tax_rate');
  return rate == null ? null : state.homeValue / 100 * (rate / 100);
}
/** Orange County's share — LARGER than the town's, and paid on top of it. */
function countyTax() {
  const rate = val('county_property_tax_rate');
  return rate == null ? null : state.homeValue / 100 * (rate / 100);
}
function totalPropertyTax() {
  const t = annualTax(), c = countyTax();
  if (t == null) return null;
  return c == null ? t : t + c;
}

function renderYou(host) {
  const rateF = one('property_tax_rate');
  if (!rateF) return;
  const perCentF = one('revenue_per_cent_of_tax_rate');

  const cRate = one('county_property_tax_rate');
  const sec = section('you', '01', 'What your property tax actually costs you',
    `Start by telling us what your home is assessed at. Everything below then uses your figure
     instead of a generic one, and this page will remember it next time.
     <br><br>
     ${cRate
       ? `This now covers <strong>both</strong> bills a Hillsborough household pays: the town's
          ${cents(rateF.value)} cents per $100 <em>and</em> Orange County's
          ${cents(cRate.value)} cents. The county's is the larger of the two, which is easy to miss.
          It does <strong>not</strong> include fire district taxes, which vary by district.`
       : `This is the <strong>town's</strong> share only.`}`);

  if (state.returning) {
    const w = document.createElement('div');
    w.className = 'welcome';
    w.innerHTML = `<span>Welcome back — showing figures for a home assessed at
      <strong>${usd(state.homeValue)}</strong>,
      ${state.location === 'intown' ? 'inside town limits' : 'outside town'}.</span>
      <button type="button" id="changeHome">Not yours? Change it</button>`;
    sec.appendChild(w);
  }

  const panel = document.createElement('div');
  panel.className = 'panel panel-pad';
  panel.innerHTML = `
    <div class="calc">
      <div>
        <div class="field">
          <label class="field-label" for="hv">What is your home assessed at?</label>
          <input type="number" id="hv" min="0" step="5000" value="${state.homeValue}"
                 inputmode="numeric">
          <input type="range" id="hvr" min="50000" max="1500000" step="5000"
                 value="${state.homeValue}" aria-label="Assessed home value slider">
        </div>
        <div class="field">
          <span class="field-label" id="locLbl">Is your home inside town limits?</span>
          <div class="seg" role="group" aria-labelledby="locLbl">
            <button type="button" data-loc="intown"
              aria-pressed="${state.location === 'intown'}">Yes, in town</button>
            <button type="button" data-loc="outoftown"
              aria-pressed="${state.location === 'outoftown'}">No, outside</button>
          </div>
        </div>
        <div class="field">
          <label class="field-label" for="galSel">How much water does your household use?</label>
          <div class="dual">
            <select id="galSel" aria-describedby="galHelp">
              ${[['2000', 'Low · 2,000 gal/mo'], ['4000', 'Town average · 4,000 gal/mo'],
                 ['6000', 'Above average · 6,000 gal/mo'], ['9000', 'High · 9,000 gal/mo'],
                 ['12000', 'Very high · 12,000 gal/mo'], ['custom', 'Enter my own…']]
                .map(([v, t]) => `<option value="${v}"${
                  (v === 'custom' ? !GAL_PRESETS.includes(state.gallons)
                                  : String(state.gallons) === v) ? ' selected' : ''}>${t}</option>`)
                .join('')}
            </select>
            <div class="unit-input">
              <input type="number" id="galNum" min="0" max="200000" step="100"
                     value="${state.gallons}" inputmode="numeric"
                     aria-label="Gallons per month">
              <span class="unit">gal/mo</span>
            </div>
          </div>
          <p class="field-help" id="galHelp">Your last bill shows this. Pick the closest, or type
            your own number — the bill below is calculated from the town's published rate schedule
            at whatever figure you enter.</p>
        </div>
        <p class="reassure"><span class="ic" aria-hidden="true">✓</span>
          <span>Nothing you type leaves your device. It is saved only in this browser so the page
          can greet you with your own figures next time.</span></p>
      </div>
      <div class="readout">
        <p class="cap">Your property tax, per year${cRate ? ' — town and county combined' : ''}</p>
        <div class="hero-figure" id="heroV">—</div>
        <p class="hero-sub" id="heroN"></p>
        <ul class="rows" id="bd"></ul>
        <div class="callout" id="calloutBox"></div>
      </div>
    </div>`;
  sec.appendChild(panel);

  const snap = document.createElement('div');
  snap.className = 'snapshot';
  snap.style.marginTop = 'var(--s5)';
  snap.id = 'snapshot';
  sec.appendChild(snap);

  host.appendChild(sec);

  const num = $('#hv', sec), rng = $('#hvr', sec);

  function draw(animate) {
    state.homeValue = Math.max(0, +num.value || 0);
    const annual = annualTax();
    const county = countyTax();
    const total = totalPropertyTax();
    const oneCent = state.homeValue / 100 * 0.01;
    const u = utilMonthly();

    setFigure($('#heroV', sec), total, animate);
    $('#heroN', sec).innerHTML = county != null
      ? `That is <strong>${usd(total / 12)} a month</strong> — ${usd(annual)} to the town at
         ${cents(rateF.value)} cents per $100, plus ${usd(county)} to Orange County at
         ${cents(cRate.value)} cents. Sources: ${cite(rateF)} and ${cite(cRate)}.`
      : `That is <strong>${usd(annual / 12)} a month</strong>, at the FY${rateF.fiscal_year} rate of
         ${cents(rateF.value)} cents per $100 of value. Source: ${cite(rateF)}.`;

    const rows = [];
    rows.push(['Town of Hillsborough', `<small>FY${rateF.fiscal_year} — the town rate did not change</small>`,
      usd(annual) + ' / yr']);
    if (county != null) {
      const inc = val('county_tax_rate_increase_cents');
      rows.push(['Orange County',
        `<small>FY${cRate.fiscal_year}${inc ? ` — the county rate rose ${cents(inc)} cents` : ''}</small>`,
        usd(county) + ' / yr']);
    }
    const gal = u.gallons.toLocaleString('en-US');
    const where = state.location === 'intown' ? 'in town' : 'out of town';
    if (u.exact) {
      // The whole bill, not just the increase — which is the point of asking for real usage.
      rows.push(['Your water bill',
        `<small>${gal} gal/month, ${where} · FY2027 rates</small>`,
        usd2(u.waterBill) + ' / mo']);
      rows.push(['Your sewer bill', '<small>same usage, charged separately</small>',
        usd2(u.sewerBill) + ' / mo']);
      rows.push(['Stormwater fee', '<small>flat, not based on water use</small>',
        usd2(u.stormBill) + ' / mo']);
      rows.push(['All three utility bills',
        `<small>about ${usd(u.billTotal * 12)} a year — up ${usd2(u.total)}/mo on FY2026</small>`,
        usd2(u.billTotal) + ' / mo']);
    } else {
      if (u.water != null) rows.push(['Your water bill goes up by',
        `<small>${gal} gal/month, ${where}</small>`, '+' + usd2(u.water) + ' / mo']);
      if (u.sewer != null) rows.push(['Your sewer bill goes up by', '<small>same basis</small>',
        '+' + usd2(u.sewer) + ' / mo']);
    }
    rows.push(['One cent on the tax rate costs you',
      `<small>across the whole town it raises ${perCentF ? usd(perCentF.value) : 'n/a'}</small>`,
      usd(oneCent) + ' / yr']);
    const need = one('tax_rate_increase_needed_cents');
    if (need) rows.push([`If the rate rose ${cents(need.value)} cents`,
      `<small>the town's own FY${need.fiscal_year} scenario</small>`,
      '+' + usd(oneCent * need.value) + ' / yr']);

    let html = rows.map(([k, sub, v]) =>
      `<li><span class="k">${k}${sub}</span><span class="v">${v}</span></li>`).join('');
    const cInc = val('county_tax_rate_increase_cents');
    const addedTax = cInc ? state.homeValue / 100 * (cInc / 100) : 0;
    const addedAll = addedTax + u.total * 12;
    if (addedAll > 0) {
      html += `<li class="total"><span class="k">So next year costs you about</span>
        <span class="v">+${usd(addedAll)} more</span></li>`;
    }
    $('#bd', sec).innerHTML = html;

    const box = $('#calloutBox', sec);
    const wr = val('water_rate_increase_pct'), sr = val('sewer_rate_increase_pct');
    if (cInc && u.total > 0 && wr) {
      box.className = 'callout warn';
      box.innerHTML = `<strong>The town's rate held steady — the rest of your bill did not.</strong>
        Orange County's rate rose ${cents(cInc)} cents, which adds
        <strong>${usd(addedTax)} a year</strong> for a home like yours, and water and sewer each
        rise ${pctPlain(wr)}, adding about ${usd2(u.total)} a month. "No town tax increase" is true
        and is not the same as "your bill is flat".`;
    } else if (u.total > 0 && wr && sr) {
      box.className = 'callout warn';
      box.innerHTML = `<strong>Your property tax rate did not go up — but your bill still does.</strong>
        Water and sewer rates each rise ${pctPlain(wr)} in FY2027, which adds about
        <strong>${usd2(u.total)} a month</strong> for a household like yours. A flat tax rate is not
        the same as a flat bill, and that distinction is easy to miss.`;
    } else {
      box.className = 'callout';
      box.innerHTML = `The property tax rate is unchanged for FY${rateF.fiscal_year}.`;
    }

    // snapshot
    const s = $('#snapshot', sec);
    s.innerHTML = `<h3>Your snapshot</h3>
      <div class="big">${usd(total)}<span style="font-size:var(--t-md);font-weight:500;
        letter-spacing:0;margin-left:.35em">in property tax this year</span></div>
      <p class="cap">${county != null
        ? `${usd(annual)} to the town, ${usd(county)} to Orange County. `
        : ''}Plus about ${usd(u.total * 12)} more over the year as water and sewer rates rise.
        Based on a home assessed at ${usd(state.homeValue)},
        ${state.location === 'intown' ? 'inside' : 'outside'} town limits.</p>
      <div class="acts">
        <button type="button" id="printSnap">Print or save as PDF</button>
        <button type="button" id="copySnap">Copy these figures</button>
      </div>
      <p class="reassure" style="margin-top:var(--s4)"><span class="ic" aria-hidden="true">✓</span>
        <span>Estimated from the assessed value you entered and the town's published rates. Your
        actual bill depends on your county assessment.</span></p>`;
    $('#printSnap', s).addEventListener('click', () => window.print());
    $('#copySnap', s).addEventListener('click', async ev => {
      const text = `Town of Hillsborough — my share, FY${rateF.fiscal_year}\n` +
        `Home assessed at ${usd(state.homeValue)} (${state.location === 'intown'
          ? 'in town' : 'out of town'})\n` +
        `Town property tax: ${usd(annual)}/yr\n` +
        (county != null ? `Orange County property tax: ${usd(county)}/yr\n` +
          `Total property tax: ${usd(total)}/yr (${usd(total / 12)}/mo)\n` : '') +
        `Water/sewer increase: +${usd2(u.total)}/mo (about ${usd(u.total * 12)}/yr)\n` +
        `Tax rate: ${cents(rateF.value)} cents per $100 — unchanged for FY${rateF.fiscal_year}\n` +
        `Source: ${(docsById().get(rateF.source_doc) || {}).filename || rateF.source_doc}`;
      try {
        await navigator.clipboard.writeText(text);
        ev.target.textContent = 'Copied';
        setTimeout(() => { ev.target.textContent = 'Copy these figures'; }, 1800);
      } catch (e) {
        // Clipboard needs a secure context and permission; never leave the user stuck.
        ev.target.textContent = 'Copy blocked — use Print';
      }
    });
    saveHome();
  }

  const rerender = () => { draw(false); refreshDependents(); };
  num.addEventListener('input', () => { rng.value = num.value; rerender(); });
  rng.addEventListener('input', () => { num.value = rng.value; rerender(); });
  $$('.seg button', sec).forEach(b => b.addEventListener('click', () => {
    state.location = b.dataset.loc;
    $$('[data-loc]', sec).forEach(o => o.setAttribute('aria-pressed', String(o === b)));
    rerender();
  }));

  // Water use: the dropdown and the number box are two views of one value.
  const galSel = $('#galSel', sec), galNum = $('#galNum', sec);
  if (galSel && galNum) {
    galSel.addEventListener('change', () => {
      if (galSel.value === 'custom') { galNum.focus(); galNum.select(); return; }
      state.gallons = Number(galSel.value);
      galNum.value = state.gallons;
      rerender();
    });
    galNum.addEventListener('input', () => {
      // Clearing the box to retype must hold the previous figure. Number('') is 0,
      // which is finite and non-negative, so a numeric guard alone let an empty box
      // render a real-looking bill at zero gallons.
      if (galNum.value.trim() === '') return;
      const g = Number(galNum.value);
      if (!Number.isFinite(g) || g < 0) return;
      state.gallons = g;
      galSel.value = GAL_PRESETS.includes(g) ? String(g) : 'custom';
      rerender();
    });
  }
  const chg = $('#changeHome', sec);
  if (chg) chg.addEventListener('click', () => {
    num.focus();
    num.scrollIntoView({ block: 'center', behavior: REDUCED ? 'auto' : 'smooth' });
  });
  draw(!REDUCED && !state.returning);
}

/* An in-flight count-up MUST be cancelled before writing a new value. Otherwise a
 * reader who edits the figure within the animation window (620ms of page load)
 * watches their own number get overwritten by the previous one as the old
 * animation finishes — silently showing the wrong tax for their home. */
let _figAnim = null;
function setFigure(el, target, animate) {
  if (_figAnim !== null) { cancelAnimationFrame(_figAnim); _figAnim = null; }
  if (target == null) { el.textContent = '—'; return; }
  if (!animate) { el.textContent = usd(target); return; }
  const dur = 620, t0 = performance.now();
  const step = now => {
    const p = Math.min(1, (now - t0) / dur);
    el.textContent = usd(target * (1 - Math.pow(1 - p, 3)));
    _figAnim = p < 1 ? requestAnimationFrame(step) : null;
  };
  _figAnim = requestAnimationFrame(step);
}

/** Re-render the sections that quote the reader's own figures.
 *
 * Debounced, and it rebuilds "what's coming" in place rather than the whole page:
 * re-rendering everything on each keystroke would tear down the input the reader
 * is currently typing into and lose focus and caret position. */
let _refreshTimer = null;
function refreshDependents() {
  const pf = $('#paysforAnswer');
  if (pf) pf.innerHTML = paysForAnswer();
  clearTimeout(_refreshTimer);
  _refreshTimer = setTimeout(() => {
    const old = document.getElementById('coming');
    if (!old) return;
    const holder = document.createElement('div');
    renderComing(holder);
    const fresh = holder.firstElementChild;
    if (fresh) old.replaceWith(fresh);
  }, 180);
}

/* ==================== 02 — what it pays for ==================== */
function paysForAnswer() {
  const gf = one('general_fund_expenditures'), total = one('total_budget');
  const annual = annualTax();
  if (!gf || !total || annual == null) return '';
  return `Your <span class="fig">${usd(annual)}</span> in town property tax goes into the
    <strong>General Fund</strong> — <span class="fig">${compact(gf.value)}</span> of the town's
    <span class="fig">${compact(total.value)}</span> total. <span class="soft">Your water, sewer and
    stormwater bills pay for the other two funds. Those are not tax money, and a rise in one is not
    a rise in the other.</span>`;
}

function renderPaysFor(host) {
  const total = one('total_budget');
  const parts = [
    ['general_fund_expenditures', 'General Fund', 'var(--series-1)',
     'Police, fire, streets, parks, planning and administration. This is the part your property tax pays for.'],
    ['water_sewer_fund_expenditures', 'Water & Sewer Fund', 'var(--series-2)',
     'Paid for by water and sewer bills, not by property tax.'],
    ['stormwater_fund_expenditures', 'Stormwater Fund', 'var(--series-3)',
     'Paid for by the stormwater fee, charged per Equivalent Residential Unit.'],
  ].map(([m, label, colour, blurb]) => {
    const f = one(m);
    return f ? { label, colour, blurb, value: f.value, f } : null;
  }).filter(Boolean);
  if (!total || parts.length < 2) return;

  const sec = section('paysfor', '02', 'What your money pays for', '');
  const ans = document.createElement('p');
  ans.className = 'answer';
  ans.id = 'paysforAnswer';
  ans.innerHTML = paysForAnswer();
  sec.appendChild(ans);

  const sum = parts.reduce((a, p) => a + p.value, 0);
  const bars = parts.map(p =>
    `<span style="background:${p.colour};width:${(p.value / sum * 100).toFixed(3)}%"
       title="${esc(p.label)}: ${esc(compact(p.value))}"></span>`).join('');
  const legend = parts.map(p => `<li>
      <span class="sw" style="background:${p.colour}"></span>
      <span><span class="nm">${esc(p.label)}</span>
        <span class="amt">${esc(compact(p.value))}</span>
        <span class="pc">${(p.value / sum * 100).toFixed(1)}% of the total</span></span>
    </li>`).join('');
  // A total that does not equal its parts would be its own small lie.
  const diff = Math.abs(sum - total.value);
  const check = diff < 1
    ? `The three funds add up exactly to the stated total of ${compact(total.value)} — this page
       checks that rather than assuming it.`
    : `⚠ The three funds add to ${compact(sum)}, which differs from the stated total
       ${compact(total.value)} by ${compact(diff)}. Shown as found in the source.`;

  const panel = document.createElement('div');
  panel.className = 'panel panel-pad';
  panel.innerHTML = `<div class="ptw" role="img"
      aria-label="${esc(parts.map(p => `${p.label} ${compact(p.value)}`).join('; '))}">${bars}</div>
    <ul class="ptw-legend">${legend}</ul>
    <div class="gloss" style="margin-top:var(--s6)">${parts.map(p =>
      `<div><dt>${esc(p.label)}</dt><dd>${esc(p.blurb)}</dd></div>`).join('')}</div>
    <p class="reassure"><span class="ic" aria-hidden="true">✓</span><span>${check}
      Source: ${cite(total)}.</span></p>`;
  sec.appendChild(panel);

  // Recurring vs one-time: how much of the budget is already committed before
  // anyone chooses anything this year.
  const mf = state.data.mfas;
  if (mf && mf.recurrence_dimension) {
    const rd = mf.recurrence_dimension;
    const gf = rd.general_fund_fy2027_budget || {};
    const share = rd.recurring_share_of_classified_general_fund_pct;
    if (share) {
      const p4 = document.createElement('div');
      p4.className = 'panel panel-pad';
      p4.style.marginTop = 'var(--s5)';
      p4.innerHTML = `
        <h3 style="margin:0 0 var(--s3);font-size:var(--t-base);font-weight:640">
          How much of it is already committed?</h3>
        <p class="answer" style="font-size:var(--t-base);margin-bottom:var(--s4)">
          About <span class="fig">${pctPlain(share)}</span> of the General Fund goes on
          <strong>ongoing commitments</strong> — salaries, benefits, day-to-day operations and debt
          payments that recur every year.
          <span class="soft">Only ${gf['One-Time'] ? compact(gf['One-Time']) : 'a small share'} is
          one-time investment. That is the practical limit on how much any single budget can change
          direction: most of it was decided in earlier years.</span>
        </p>
        <ul class="rows" style="margin:0">
          ${Object.entries(gf).sort((a, b) => b[1] - a[1]).map(([k, v]) =>
            `<li><span class="k">${esc(k)}${k === 'Unclassified'
              ? '<small>transfers that mix routine subsidy with one-off funding — not split</small>'
              : ''}</span><span class="v">${usd(v)}</span></li>`).join('')}
        </ul>
        <p class="reassure"><span class="ic" aria-hidden="true">✓</span><span>Grouped by this site
          from the town's own expenditure categories — the town does not publish this split itself,
          so it is our classification, not its words. Anything genuinely mixed is left
          unclassified rather than forced into a bucket.</span></p>`;
      sec.appendChild(p4);
    }
  }

  // Cross-fund transfers: where money moves between the town's own funds.
  const tf = state.data.transfers;
  if (tf && tf.schedules) {
    const cur = tf.schedules.find(x => x.fiscal_year === 2027 && x.basis === 'budget');
    if (cur) {
      sec.appendChild(disclosure('See money moved between the town’s own funds', inner => {
        const dests = cur.destinations.filter(d =>
          cur.rows.some(r => r.to[d])) ;
        inner.innerHTML = `
          <p class="sub" style="font-size:var(--t-sm);color:var(--text-secondary);margin:0 0 var(--s4)">
            Funds do not operate in isolation — each year the town moves money from its operating
            funds into its capital funds and reserves. Read one fund alone and these look like
            unexplained gaps; laid out together they show what is being set aside to build things
            later. FY2027 budget.
          </p>
          <div class="tablewrap"><table>
            <caption>Transfers out of each fund, and where they went. Reads the outgoing side
              only — see the note below.</caption>
            <thead><tr><th>From</th>${dests.map(d =>
              `<th class="num">${esc(d)}</th>`).join('')}<th class="num">Total out</th></tr></thead>
            <tbody>${cur.rows.map(r => `<tr><td>${esc(r.from_fund)}</td>${
              dests.map(d => `<td class="num">${r.to[d] ? usd(r.to[d]) : '—'}</td>`).join('')
            }<td class="num" style="font-weight:650">${usd(r.total_out)}</td></tr>`).join('')}
            </tbody></table></div>
          <p class="reassure"><span class="ic" aria-hidden="true">✓</span><span>
            ${esc(tf.limitation)}</span></p>`;
      }));
    }
  }

  // The real answer to "where does it go" is the account-level detail. Behind a
  // disclosure so the ~790 KB dataset is only fetched if the reader wants it.
  sec.appendChild(disclosure('Break it down department by department', async inner => {
    inner.innerHTML = `<p class="loading" style="padding:var(--s5) 0">Loading the town's
      account-level spending…</p>`;
    try {
      const ok = await loadLineItems();
      inner.innerHTML = '';
      if (!ok) {
        inner.innerHTML = `<p class="sub">The detailed spending data is not published in this
          build.</p>`;
        return;
      }
      const panel2 = document.createElement('div');
      panel2.className = 'panel panel-pad';
      inner.appendChild(panel2);
      renderExplorer(panel2);
    } catch (err) {
      inner.innerHTML = `<p class="sub">Could not load the detailed spending data.</p>`;
      console.error(err);
    }
  }));

  host.appendChild(sec);
}

/* ==================== the spending explorer ==================== */
/* The account-level dataset is ~790 KB, so it is fetched only when the reader
 * actually opens the explorer. Loading it on first paint would cost every phone
 * visitor most of a megabyte to render a page most of them never drill into. */
let _li = null, _liv = null;
async function loadLineItems() {
  if (_li) return true;
  const idx = state.data.index;
  if (!idx.datasets.lineitems) return false;
  const [li, val] = await Promise.all([
    fetch('data/' + idx.datasets.lineitems).then(r => r.json()),
    idx.datasets.lineitem_validation
      ? fetch('data/' + idx.datasets.lineitem_validation).then(r => r.json())
      : Promise.resolve(null),
  ]);
  const C = Object.fromEntries(li.columns.map((c, i) => [c, i]));
  _li = { C, rows: li.rows, note: li.note };
  _liv = val;
  return true;
}

/** Is this (fund, year, basis) slice one the pipeline proved reconciles? */
function sliceVerified(fund, fy, basis) {
  if (!_liv) return null;
  const s = _liv.verified_slices.find(x =>
    x.fund === fund && x.fiscal_year === fy && x.basis === basis);
  return s ? s.verified : null;
}

function renderExplorer(host) {
  const { C, rows } = _li;
  const funds = [...new Set(rows.map(r => r[C.fund]))].sort();
  const slices = [...new Set(rows.map(r => r[C.fiscal_year] + '|' + r[C.basis]))]
    .map(s => s.split('|')).map(([y, b]) => ({ fy: +y, basis: b }))
    .sort((a, b) => a.fy - b.fy);

  const st = { fund: funds.includes('General Fund') ? 'General Fund' : funds[0],
               fy: 2027, basis: 'budget', open: null };
  if (!slices.some(s => s.fy === st.fy && s.basis === st.basis)) {
    st.fy = slices[0].fy; st.basis = slices[0].basis;
  }

  const wrap = document.createElement('div');
  host.appendChild(wrap);

  function draw() {
    const sel = rows.filter(r => r[C.fund] === st.fund
      && r[C.fiscal_year] === st.fy && r[C.basis] === st.basis);
    const total = sel.reduce((a, r) => a + r[C.value], 0);
    const byDept = new Map();
    for (const r of sel) {
      const d = r[C.department];
      if (!byDept.has(d)) byDept.set(d, { total: 0, rows: [] });
      const e = byDept.get(d);
      e.total += r[C.value];
      e.rows.push(r);
    }
    const depts = [...byDept.entries()].sort((a, b) => b[1].total - a[1].total);
    const max = depts.length ? depts[0][1].total : 1;
    const yourTax = annualTax() || 0;
    const verified = sliceVerified(st.fund, st.fy, st.basis);
    const taxFunded = st.fund === 'General Fund';

    wrap.innerHTML = `
      <div class="explorer-controls">
        <div class="f"><label class="field-label" for="exFund">Which fund?</label>
          <select id="exFund">${funds.map(f =>
            `<option ${f === st.fund ? 'selected' : ''}>${esc(f)}</option>`).join('')}</select></div>
        <div class="f"><label class="field-label" for="exYear">Which year?</label>
          <select id="exYear">${slices.map(s =>
            `<option value="${s.fy}|${s.basis}" ${s.fy === st.fy && s.basis === st.basis
              ? 'selected' : ''}>FY${s.fy} ${s.basis}</option>`).join('')}</select></div>
      </div>
      ${verified === false ? `<div class="callout warn" style="margin:0 0 var(--s5)">
        <strong>This particular year does not fully add up in the source.</strong> The account
        detail for FY${st.fy} ${esc(st.basis)} differs from the total the town publishes for it, and
        we have not established why. It is shown because hiding it would be worse, but treat it as
        provisional — the FY2027 budget figures reconcile exactly.</div>` : ''}
      <p class="answer" style="font-size:var(--t-base)">
        ${taxFunded && yourTax
          ? `Of the <span class="fig">${usd(yourTax)}</span> you pay the town, this is roughly how it
             divides — using the same proportions the town divides its
             ${esc(st.fund)} into.`
          : `How the ${esc(st.fund)} divides for FY${st.fy}.`}
        <span class="soft">${esc(st.fund)} total: ${compact(total)}.</span>
      </p>
      <ul class="spend">${depts.map(([name, e]) => {
        const pct = total ? e.total / total * 100 : 0;
        const yours = taxFunded && total ? yourTax * (e.total / total) : null;
        const isOpen = st.open === name;
        const accounts = [...e.rows].sort((a, b) => b[C.value] - a[C.value]);
        return `<li>
          <button class="row" type="button" data-dept="${esc(name)}"
                  aria-expanded="${isOpen}">
            <span class="nm">${esc(name)}<span class="caret">${isOpen ? '▾' : '▸'}</span></span>
            <span class="amt">${esc(compact(e.total))}${yours != null
              ? ` <span class="yours">· ${esc(usd(yours))} of yours</span>` : ''}</span>
            <span class="bar"><span style="width:${(e.total / max * 100).toFixed(2)}%"></span></span>
            <span class="sub">${pct.toFixed(1)}% of the fund · ${accounts.length} line
              item${accounts.length === 1 ? '' : 's'}</span>
          </button>
          ${isOpen ? `<ul class="accounts">${accounts.map(r =>
            `<li><span>${esc(r[C.account])}${
              // self-categorising rows (e.g. "Debt Service") would otherwise
              // render as "Debt Service · Debt Service"
              r[C.category] && r[C.category] !== r[C.account]
                ? `<span style="color:var(--text-muted)"> · ${esc(r[C.category])}</span>` : ''}</span>
              <span class="v">${esc(usd(r[C.value]))}</span></li>`).join('')}
            <li style="border-top:1px solid var(--hairline);margin-top:4px;padding-top:6px">
              <span style="color:var(--text-muted)">Every figure above is from
                ${cite({ source_doc: accounts[0][C.source_doc], source_page: accounts[0][C.page] })}
              </span></li></ul>` : ''}
        </li>`;
      }).join('')}</ul>
      <p class="reassure"><span class="ic" aria-hidden="true">✓</span><span>
        ${verified ? `These figures add up to the town's own published total for
          FY${st.fy} ${esc(st.basis)} — checked automatically, not assumed. ` : ''}
        ${taxFunded ? `The split of <em>your</em> share is a proportional illustration: your property
          tax is one of several revenues in this fund, so treat it as "where this fund goes", not as
          an audit trail for your individual dollars.` : ''}</span></p>`;

    $('#exFund', wrap).addEventListener('change', e => {
      st.fund = e.target.value; st.open = null; draw();
    });
    $('#exYear', wrap).addEventListener('change', e => {
      const [y, b] = e.target.value.split('|');
      st.fy = +y; st.basis = b; st.open = null; draw();
    });
    $$('.spend .row', wrap).forEach(b => b.addEventListener('click', () => {
      st.open = st.open === b.dataset.dept ? null : b.dataset.dept;
      draw();
    }));
    const fr = document.createElement('p');
    fr.style.margin = 'var(--s3) 0 0';
    fr.appendChild(flagButton('the spending breakdown',
      `${st.fund}, FY${st.fy} ${st.basis}`));
    wrap.appendChild(fr);
  }
  draw();
}

/* ==================== 03 — is the money healthy? ==================== */
function renderHealth(host) {
  const sec = section('health', '03', 'Is the town’s money in good shape?', '');

  const now = forYear('general_fund_balance_pct_of_expenditures', 2027)
    || one('general_fund_balance_pct_of_expenditures');
  const far = latestByYear('general_fund_balance_pct_of_expenditures').slice(-1)[0];
  const floorQ = quote('savings_floor');
  const dropQ = quote('savings_drop');
  const noTaxQ = quote('no_tax_increase');
  const FLOOR = 50;

  const ans = document.createElement('p');
  ans.className = 'answer';
  ans.innerHTML = now
    ? `Right now, yes — with a warning attached. The town holds savings worth
       <span class="fig">${pctPlain(now.value)}</span> of a year's spending, comfortably above the
       <span class="fig">${FLOOR}%</span> floor it sets for itself.
       <span class="soft">But it plans to spend more than it collects in every year of its
       three-year plan, covering the gap from those savings — and it expects them to fall to
       ${far ? pctPlain(far.value) : 'less'} by FY${far ? far.fiscal_year : ''}.</span>`
    : '';
  sec.appendChild(ans);

  const items = [];
  if (now) items.push([now.value >= FLOOR ? 'ok' : 'bad', now.value >= FLOOR ? '✓' : '!',
    'Savings are above the town’s own floor',
    `<span class="fig">${pctPlain(now.value)}</span> of a year's spending in FY${now.fiscal_year}.
     The town's stated aim is no lower than ${FLOOR}%.`]);
  if (far && far.fiscal_year !== (now && now.fiscal_year)) {
    items.push([far.value >= FLOOR ? 'watch' : 'bad', far.value >= FLOOR ? '~' : '!',
      `Savings are projected to fall by FY${far.fiscal_year}`,
      `Down to <span class="fig">${pctPlain(far.value)}</span> —
       ${far.value >= FLOOR ? 'still above the floor, but the town itself calls the drop concerning.'
        : 'below the floor the town sets for itself.'}`]);
  }
  const defs = latestByYear('general_fund_surplus_deficit').filter(f => f.value < 0);
  if (defs.length) {
    const worst = defs.reduce((a, b) => (b.value < a.value ? b : a));
    items.push(['watch', '~', `A planned shortfall in ${defs.length} of the coming years`,
      `The largest is <span class="fig">${usdSigned(worst.value)}</span> in FY${worst.fiscal_year}.
       Shortfalls are covered from savings, which is why the savings line matters.`]);
  }
  const rate = one('property_tax_rate');
  if (rate) items.push(['ok', '✓', 'Your property tax rate is not going up this year',
    `It stays at <span class="fig">${cents(rate.value)} cents</span> per $100 of value in
     FY${rate.fiscal_year}.`]);
  const wr = val('water_rate_increase_pct');
  if (wr) items.push(['watch', '~', 'Water and sewer rates are going up',
    `Each rises <span class="fig">${pctPlain(wr)}</span>, and the town recommends the same again for
     the two years after.`]);

  const panel = document.createElement('div');
  panel.className = 'panel panel-pad';
  panel.innerHTML = `<ul class="statlist">${items.map(([cls, ic, lb, dt]) =>
    `<li class="${cls}"><span class="ic" aria-hidden="true">${ic}</span>
      <span><span class="lb">${lb}</span><span class="dt">${dt}</span></span></li>`).join('')}</ul>`;

  for (const q of [floorQ, dropQ, noTaxQ]) {
    if (!q) continue;
    const bq = document.createElement('blockquote');
    bq.className = 'town';
    bq.innerHTML = `“${esc(q.text)}”
      <cite>The town’s own words — ${esc((docsById().get(q.source_doc) || {}).filename
        || q.source_doc)}, p.${q.source_page}</cite>`;
    panel.appendChild(bq);
  }
  sec.appendChild(panel);

  // ---- the audited outcome: the only fully checked year on the page ----------
  const aud = state.data.audited;
  if (aud && aud.rows && aud.rows.length) {
    const totE = aud.rows.find(r => r.section === 'expenditures' && r.is_total);
    const totR = aud.rows.find(r => r.section === 'revenues' && r.is_total);
    if (totE && totR) {
      const underPct = totE.final_budget ? (totE.final_budget - totE.actual) / totE.final_budget * 100 : 0;
      const overRev = totR.actual - totR.final_budget;
      const p2 = document.createElement('div');
      p2.className = 'panel panel-pad';
      p2.style.marginTop = 'var(--s5)';
      p2.innerHTML = `
        <h3 style="margin:0 0 var(--s3);font-size:var(--t-base);font-weight:640">
          Did they spend what they said they would?</h3>
        <p class="answer" style="font-size:var(--t-base);margin-bottom:var(--s4)">
          In <span class="fig">FY${aud.fiscal_year}</span> — the most recent year with audited
          accounts — the town budgeted <span class="fig">${usd(totE.final_budget)}</span> and
          actually spent <span class="fig">${usd(totE.actual)}</span>,
          <span class="fig">${pctPlain(underPct)}</span> less than planned.
          <span class="soft">Revenue came in ${usd(Math.abs(overRev))}
          ${overRev >= 0 ? 'above' : 'below'} budget.</span>
        </p>
        <p class="reassure"><span class="ic" aria-hidden="true">✓</span><span>
          This is the audited statement, checked by an outside accountant after the year closed —
          not a plan. It also lines up with the budget document's own figures for the same year to
          within a dollar${aud.cross_document_check && aud.cross_document_check.agree
            ? '' : ' (see the data files for detail)'}, across two separate documents.
          Source: ${cite({ source_doc: aud.source_doc, source_page: aud.source_page })}.
        </span></p>`;
      p2.appendChild(disclosure('See it line by line', inner2 => {
        const fmtc = v => v == null ? '—' : usd(v);
        const body = aud.rows.map(r => `<tr${r.is_total
          ? ' style="font-weight:650;border-top:1px solid var(--hairline-firm)"' : ''}>
          <td>${esc(r.line)}</td>
          <td class="num">${fmtc(r.final_budget)}</td>
          <td class="num">${fmtc(r.actual)}</td>
          <td class="num">${r.variance_derived == null ? '—'
            : (r.variance_derived >= 0 ? '+' : '−') + usd(Math.abs(r.variance_derived))}</td>
        </tr>`).join('');
        inner2.innerHTML = tableOf(
          `Audited General Fund, year ended 30 June ${aud.fiscal_year}. A positive variance means `
          + `revenue came in above budget, or spending came in below it.`,
          [{ label: 'Line' }, { label: 'Final budget', num: true },
           { label: 'Actual', num: true }, { label: 'Variance', num: true }],
          []) .replace('<tbody></tbody>', `<tbody>${body}</tbody>`);
      }));
      sec.appendChild(p2);
    }
  }

  // ---- the audited series, spanning digital and recognised sources ----------
  const ocr = state.data.ocr_statements;
  if (ocr && ocr.published && ocr.published.length) {
    const series = new Map();   // fiscal_year -> {revenues, expenditures, how}
    for (const p of ocr.published) {
      if (p.column_role !== 'actual' || !p.fiscal_year) continue;
      const e = series.get(p.fiscal_year) || { fy: p.fiscal_year, how: 'recognised' };
      e[p.section] = p.total;
      e.page = p.source_page;
      e.doc = p.source_doc;
      series.set(p.fiscal_year, e);
    }
    // FY2025 comes from the DIGITAL report — no recognition involved.
    if (aud && aud.rows) {
      const r = aud.rows.find(x => x.section === 'revenues' && x.is_total);
      const x2 = aud.rows.find(x => x.section === 'expenditures' && x.is_total);
      if (r && x2) series.set(aud.fiscal_year, {
        fy: aud.fiscal_year, revenues: r.actual, expenditures: x2.actual,
        how: 'digital', page: aud.source_page, doc: aud.source_doc });
    }
    const yrs = [...series.values()].sort((a, b) => a.fy - b.fy);
    if (yrs.length >= 2) {
      const p3 = document.createElement('div');
      p3.className = 'panel panel-pad';
      p3.style.marginTop = 'var(--s5)';
      const nDigital = yrs.filter(y => y.how === 'digital').length;
      p3.innerHTML = `
        <h3 style="margin:0 0 var(--s3);font-size:var(--t-base);font-weight:640">
          The audited record, year by year</h3>
        <p style="margin:0 0 var(--s4);font-size:var(--t-sm);color:var(--text-secondary)">
          What the town actually took in and actually spent, from its audited annual reports.
          ${nDigital} of these ${yrs.length} years came from a digital file;
          the rest were recovered from scanned pages by character recognition and then checked —
          each figure shown here is the total that its own page's individual lines add up to
          exactly.
        </p>
        <div class="tablewrap"><table>
          <caption>Audited General Fund actuals. "Read from" shows whether the figures came from a
            digital document or from a verified reading of a scan.</caption>
          <thead><tr><th>Year</th><th class="num">Revenue (actual)</th>
            <th class="num">Spending (actual)</th><th>Read from</th></tr></thead>
          <tbody>${yrs.map(y => `<tr>
            <td>FY${y.fy}</td>
            <td class="num">${y.revenues != null ? usd(y.revenues) : '—'}</td>
            <td class="num">${y.expenditures != null ? usd(y.expenditures) : '—'}</td>
            <td>${y.how === 'digital'
              ? '<span class="badge ok">digital original</span>'
              : '<span class="badge">scan, arithmetic-verified</span>'}</td>
          </tr>`).join('')}</tbody></table></div>
        <div class="callout warn" style="margin-top:var(--s5)">
          <strong>Best practice: these should all be digital originals.</strong>
          A figure read from a digital file is read directly; a figure recovered from a scan is an
          inference, however carefully verified. Asking the town to publish digital copies of the
          earlier reports would remove that distinction entirely — and it costs them nothing.
        </div>`;
      // Orange County's audited series, from the curated design workbook.
      const wc = state.data.warehouse_county;
      if (wc && wc.rows) {
        const byYear = new Map();
        for (const r of wc.rows) {
          if (!String(r.table || '').startsWith('2.0')) continue;
          const cat = String(r.Category || '').toLowerCase();
          if (!r.Actual_Amount) continue;
          const e = byYear.get(r.Fiscal_Year_ID) || {};
          if (cat === 'total revenues') e.rev = r.Actual_Amount;
          if (cat === 'total expenditures') e.exp = r.Actual_Amount;
          byYear.set(r.Fiscal_Year_ID, e);
        }
        const cy = [...byYear.entries()].filter(([, v]) => v.rev || v.exp)
          .sort((a, b) => a[0].localeCompare(b[0]));
        if (cy.length >= 2) {
          const v = wc.verification || {};
          const cw = document.createElement('div');
          cw.style.marginTop = 'var(--s6)';
          cw.innerHTML = `
            <h4 style="margin:0 0 var(--s3);font-size:var(--t-sm);font-weight:640">
              Orange County, the same years</h4>
            <p style="margin:0 0 var(--s4);font-size:var(--t-sm);color:var(--text-secondary)">
              The county is a much larger government than the town, and this is its audited General
              Fund. These figures come from a curated research workbook rather than from this site's
              own extraction — every row carries the county report and page it was taken from, and
              this build re-checks them against those pages
              ${v.every_figure_found ? `(<strong>${v.every_figure_found} of
              ${v.rows_checked_against_source_pdf}</strong> checkable rows matched exactly)` : ''}.
            </p>
            <div class="tablewrap"><table>
              <caption>Orange County audited General Fund actuals.</caption>
              <thead><tr><th>Year</th><th class="num">Revenue (actual)</th>
                <th class="num">Spending (actual)</th></tr></thead>
              <tbody>${cy.map(([fy, e]) => `<tr><td>${esc(fy)}</td>
                <td class="num">${e.rev ? usd(e.rev) : '—'}</td>
                <td class="num">${e.exp ? usd(e.exp) : '—'}</td></tr>`).join('')}</tbody>
            </table></div>`;
          p3.appendChild(cw);
        }
      }

      const fr = document.createElement('p');
      fr.style.margin = 'var(--s4) 0 0';
      fr.appendChild(flagButton('the audited record table',
        `FY${yrs[0].fy}–FY${yrs[yrs.length - 1].fy} audited actuals`));
      p3.appendChild(fr);
      sec.appendChild(p3);
    }
  }

  sec.appendChild(disclosure('See the charts behind this', inner => {
    const years = [...new Set(state.data.facts.facts
      .map(f => f.fiscal_year).filter(v => v != null))].sort((a, b) => a - b);
    const f = document.createElement('div');
    f.className = 'filters';
    const opts = ys => ys.map(y => `<option value="${y}">FY${y}</option>`).join('');
    f.innerHTML = `<div class="f"><label class="field-label" for="ymin">From year</label>
        <select id="ymin">${opts(years)}</select></div>
      <div class="f"><label class="field-label" for="ymax">To year</label>
        <select id="ymax">${opts(years)}</select></div>
      <p class="hint">Beyond FY2027 these are the town's own projections, not adopted budgets.</p>`;
    inner.appendChild(f);
    const a = $('#ymin', f), b = $('#ymax', f);
    a.value = state.yearMin; b.value = state.yearMax;
    const onChange = () => {
      state.yearMin = Math.min(+a.value, +b.value);
      state.yearMax = Math.max(+a.value, +b.value);
      grid.innerHTML = '';
      build();
    };
    a.addEventListener('change', onChange);
    b.addEventListener('change', onChange);

    const grid = document.createElement('div');
    grid.className = 'grid2';
    inner.appendChild(grid);
    function build() {
      [
        chartSurplus(),
        chartLine('general_fund_balance_pct_of_expenditures',
          'How much savings the town holds', 'Measured against a year of spending.',
          pctPlain, 50, '50% stated floor'),
        chartLine('general_fund_balance_available_cash', 'Savings in dollars',
          'The town’s cash reserve.', compact),
        chartColumns(latestByYear('admin_spend_total').filter(inRange),
          'Administrative spending',
          'Supplied by a county commissioner, not an audited total.', compact),
      ].filter(Boolean).forEach(c => grid.appendChild(c));
    }
    build();

    // projection drift, full width
    const cmps = state.data.projections.comparisons.filter(c =>
      c.metric === 'general_fund_balance_available_cash');
    if (cmps.length) {
      const note = document.createElement('p');
      note.className = 'sub';
      note.style.margin = 'var(--s6) 0 var(--s4)';
      note.style.color = 'var(--text-secondary)';
      note.style.fontSize = 'var(--t-sm)';
      note.innerHTML = `The town publishes a rolling three-year plan, so the same year appears in
        several documents. Its forecasts have come in better than predicted — which is worth knowing
        before treating a projection as a promise. This is not an accusation: the town says plainly
        that it budgets cautiously.`;
      inner.appendChild(note);
      const items2 = cmps.map(c => {
        const rs = [...c.readings].sort((x, y) => docYear(x.source_doc) - docYear(y.source_doc));
        return { label: 'FY' + c.fiscal_year, a: rs[0].value, b: rs[rs.length - 1].value,
          src: rs.map(r => esc(r.source_doc)).join(' → ') };
      });
      const c2 = chartDumbbell(items2, 'What was projected vs what was later reported',
        'Each row is one year.', compact, ['Earlier document', 'Later document']);
      if (c2) inner.appendChild(c2);
    }
  }));

  host.appendChild(sec);
}

/* ==================== 04 — what's coming ==================== */
function renderComing(host) {
  const sec = section('coming', '04', 'What’s coming for you', '');
  const need = one('tax_rate_increase_needed_cents');
  const scenario = one('fy29_scenario_increase_on_400k_home');
  const capCents = one('capital_projects_tax_rate_equivalent_cents');
  const houseCents = one('affordable_housing_tax_rate_equivalent_cents');
  const oneCent = state.homeValue / 100 * 0.01;

  const ans = document.createElement('p');
  ans.className = 'answer';
  ans.innerHTML = need
    ? `The town does not propose a tax increase this year, but it projects a shortfall of
       <span class="fig">${usdSigned(val('general_fund_surplus_deficit') || 0)}</span> by FY2029 that
       would need a rise of over <span class="fig">${cents(need.value)} cents</span> to close —
       about <span class="fig">${usd(oneCent * need.value)} a year</span> for a home like yours.
       <span class="soft">These are projections and will change.</span>`
    : '';
  sec.appendChild(ans);

  const def = latestByYear('general_fund_surplus_deficit');
  const pct = new Map(latestByYear('general_fund_surplus_deficit_pct').map(f => [f.fiscal_year, f]));
  const bal = new Map(latestByYear('general_fund_balance_pct_of_expenditures')
    .map(f => [f.fiscal_year, f]));

  const items = def.filter(f => f.fiscal_year >= 2027).map(f => {
    const p = pct.get(f.fiscal_year), bl = bal.get(f.fiscal_year);
    const bad = f.value < 0 && Math.abs(p ? p.value : 0) > 8;
    let body = `The town plans to ${f.value < 0 ? 'spend' : 'take in'}
      <span class="fig">${usdSigned(Math.abs(f.value))}</span>
      ${f.value < 0 ? 'more than it collects' : 'more than it spends'}`;
    if (p) body += ` (${pctPlain(Math.abs(p.value))} of its budget)`;
    body += '.';
    if (bl) body += ` Savings would sit at <span class="fig">${pctPlain(bl.value)}</span> of a
      year's spending${bl.value < 50 ? ' — below its own 50% floor.' : '.'}`;
    if (f.fiscal_year === 2029 && need && scenario) {
      body += ` Closing that gap would take over <span class="fig">${cents(need.value)} cents</span>
        on the rate — the town's own example is <span class="fig">${usd(scenario.value)} a year</span>
        on a $400,000 home, and <span class="fig">${usd(oneCent * need.value)}</span> on yours.`;
    }
    return `<li class="${bad ? 'bad' : ''}"><span class="node" aria-hidden="true"></span>
      <span class="yr">FY${f.fiscal_year} · ${esc(f.basis)}</span>
      <h4>${f.fiscal_year === 2027 ? 'This year, already adopted' : 'Projected'}</h4>
      <p>${body}</p></li>`;
  });

  const commitments = [];
  if (capCents) commitments.push(`the new fire station, the Ridgewalk Greenway and the train station
    are expected to need about <span class="fig">${cents(capCents.value)} cents</span> on the tax
    rate — roughly <span class="fig">${usd(oneCent * capCents.value)} a year</span> for your home`);
  if (houseCents) commitments.push(`the board has committed to raising affordable-housing spending
    until it reaches <span class="fig">${cents(houseCents.value)} cents</span>
    (about <span class="fig">${usd(oneCent * houseCents.value)} a year</span> for you)`);
  if (commitments.length) {
    items.push(`<li><span class="node" aria-hidden="true"></span>
      <span class="yr">Already promised</span><h4>Commitments on top of the above</h4>
      <p>${commitments.join('; ').replace(/^./, ch => ch.toUpperCase())}.</p></li>`);
  }

  const panel = document.createElement('div');
  panel.className = 'panel panel-pad';
  panel.innerHTML = `<ul class="timeline">${items.join('')}</ul>`;
  sec.appendChild(panel);

  const ps = state.data.requests.projects_with_cost_changes
    .filter(p => p.original_budget_usd != null && p.current_budget_usd != null);
  if (ps.length) {
    sec.appendChild(disclosure('See how project costs have grown', inner => {
      const c = chartDumbbell(ps.map(p => ({
        label: p.project, a: p.original_budget_usd, b: p.current_budget_usd,
        src: 'Data request workbook, Project Cost Changes'
      })), 'What these projects were budgeted at, then and now',
        `From the initiative's own workbook rather than an audited statement, so treat them as
         figures to verify. Both rows' arithmetic reconciles.`,
        compact, ['Original budget', 'Current budget']);
      if (c) inner.appendChild(c);
    }));
  }
  host.appendChild(sec);
}

/* ==================== 05 — speak up ==================== */
function renderVoice(host) {
  const sec = section('voice', '05', 'How to be heard', '');
  const part = (state.data.household && state.data.household.civic_participation) || [];
  const r = state.data.requests, s = r.summary;

  const ans = document.createElement('p');
  ans.className = 'answer';
  ans.innerHTML = `The budget is adopted by the mayor and Board of Commissioners, and the process
    includes public hearings you can attend. <span class="soft">Below are the dates the FY2027
    budget message names, and the questions residents have already put to the town.</span>`;
  sec.appendChild(ans);

  if (part.length) {
    const p = document.createElement('div');
    p.className = 'panel panel-pad';
    p.innerHTML = `<h3 style="margin:0 0 var(--s4);font-size:var(--t-base);font-weight:640">
        Dates named in the budget</h3>
      <ul class="rows" style="margin:0">${part.map(e =>
        `<li><span class="k">${esc(e.event)}</span>
          <span class="v">${esc(e.date_stated)}</span></li>`).join('')}</ul>
      <p class="reassure"><span class="ic" aria-hidden="true">✓</span><span>These are as printed in
        the FY2027 budget message. Check the town's current meeting calendar before you go — dates
        move.</span></p>`;
    sec.appendChild(p);
  }

  const filled = s.data_cells_requested
    ? s.data_cells_provided / s.data_cells_requested * 100 : 0;
  const q = document.createElement('div');
  q.className = 'panel panel-pad';
  q.style.marginTop = 'var(--s5)';
  q.innerHTML = `<h3 style="margin:0 0 var(--s3);font-size:var(--t-base);font-weight:640">
      Questions residents have already asked</h3>
    <p style="margin:0 0 var(--s5);font-size:var(--t-sm);color:var(--text-secondary)">
      Because organisational changes make year-to-year comparisons hard, residents sent the town a
      workbook asking for staffing, utility, capital-project, debt, revenue and housing figures on a
      consistent basis. This is how much of it has come back so far.</p>
    <div class="meter">
      <div class="track"><div class="fill" style="width:${Math.max(0.7, filled).toFixed(1)}%"></div></div>
      <div class="cap"><span><strong>${s.data_cells_provided}</strong> of
        <strong>${s.data_cells_requested}</strong> requested figures provided</span>
        <span><strong>${filled.toFixed(1)}%</strong></span></div>
    </div>
    <p class="reassure"><span class="ic" aria-hidden="true">✓</span><span>${s.tables_unanswered} of
      ${s.tables_requested} requested tables are still blank. This reflects the copy of the workbook
      in our archive when it was collected — it is a status snapshot, <strong>not</strong> a finding
      that the town refused to answer.</span></p>`;
  q.appendChild(disclosure('See every question asked', inner => {
    inner.innerHTML = `<div class="tablewrap"><table>
      <caption>Every table requested, and whether it has been filled in.</caption>
      <thead><tr><th>Topic</th><th>Table</th><th class="num">Filled</th><th>Status</th></tr></thead>
      <tbody>${r.tables.map(t => {
        const ic = t.status === 'answered' ? '✓' : t.status === 'partial' ? '○' : '✕';
        return `<tr><td>${esc(t.section || '—')}</td><td>${esc(t.title)}</td>
          <td class="num">${t.cells_provided} / ${t.cells_expected}</td>
          <td><span class="status ${esc(t.status)}">
            <span class="ico" aria-hidden="true">${ic}</span>${esc(t.status)}</span></td></tr>`;
      }).join('')}</tbody></table></div>`;
  }));
  sec.appendChild(q);
  host.appendChild(sec);
}

/* ==================== 06 — the receipts ==================== */
const GLOSSARY = [
  ['Fiscal year (FY)', 'The town’s budget year runs 1 July to 30 June. FY2027 means the year ending 30 June 2027.'],
  ['General Fund', 'The main account for services paid out of taxes — police, fire, streets, parks, planning, administration.'],
  ['Fund balance', 'Savings. Money not spent in earlier years, kept for emergencies and cash flow. The town aims to hold no less than 50% of a year’s spending.'],
  ['Property tax rate', 'Charged in cents per $100 of assessed value. At 51.3 cents, a $100,000 home pays $513 a year to the town. That is 0.513% of the value — not 51.3%.'],
  ['Ad valorem tax', 'Latin for “according to value” — in other words, the property tax.'],
  ['Revenue-neutral rate', 'After a revaluation raises property values, this is the rate that would bring in the same money as before. A rate above it is a real increase even if the cents figure looks lower.'],
  ['ERU', 'Equivalent Residential Unit — the unit the stormwater fee is charged in, based on how much hard surface sheds rain.'],
  ['Enterprise fund', 'A fund paid for by the people who use the service rather than by taxes. Water & Sewer and Stormwater are these.'],
  ['Budget vs estimate vs projection', 'A budget is the plan adopted. An estimate is where the year is expected to land. A projection is a later year in the plan, and least certain. This page never mixes them.'],
  ['Audited', 'Checked by an outside accountant after the year ends. Audited figures are the most reliable, and are the ones this page cannot yet show — see the note at the bottom.'],
];

function renderReceipts(host) {
  const docs = state.data.documents.documents, sum = state.data.documents.summary;
  const sec = section('receipts', '06', 'Where every number came from', '');
  const ans = document.createElement('p');
  ans.className = 'answer';
  ans.innerHTML = `Every figure on this page traces to one of
    <span class="fig">${sum.unique_documents}</span> documents the town published.
    <span class="soft">${sum.pdf_digital_text} of them can be read reliably by computer;
    ${sum.pdf_scanned_ocr} are scans whose hidden text scrambles digits, so nothing on this page is
    taken from those.</span>`;
  sec.appendChild(ans);

  // ---- best effort, and how to tell us we got it wrong -----------------------
  const effort = document.createElement('div');
  effort.className = 'panel panel-pad';
  effort.style.marginBottom = 'var(--s5)';
  effort.innerHTML = `
    <h3 style="margin:0 0 var(--s3);font-size:var(--t-base);font-weight:640">
      This is a best-effort project — please tell us if something looks wrong</h3>
    <p style="margin:0 0 var(--s4);font-size:var(--t-sm);color:var(--text-secondary)">
      This site is built and maintained by residents, not by the town. Every figure is traced to a
      published document and checked by machine wherever the document makes that possible, but the
      source material runs to thousands of pages and <strong>we do not claim it is
      flawless</strong>. If a figure looks wrong, is out of date, or reads misleadingly, the fastest
      way to get it fixed is to say so — a report costs you a minute and makes the site better for
      everyone who reads it after you.
    </p>
    <p style="margin:0 0 var(--s2);font-size:var(--t-sm);color:var(--text-secondary)">
      Reports go to a public tracker, so you can see what has been raised and what has been done
      about it. If you are comfortable with GitHub you can also propose the fix yourself.
    </p>
    <div class="btn-row">
      <a class="btn primary" href="${reportUrl('general')}" target="_blank" rel="noopener">
        <span class="ic" aria-hidden="true">⚑</span> Report a problem</a>
      <a class="btn" href="${REPO}/issues" target="_blank" rel="noopener">
        <span class="ic" aria-hidden="true">☰</span> See what's been reported</a>
      <a class="btn" href="${REPO}/fork" target="_blank" rel="noopener">
        <span class="ic" aria-hidden="true">⑂</span> Propose a fix yourself</a>
    </div>
    <p class="reassure" style="margin-top:var(--s4)">
      <span class="ic" aria-hidden="true">✓</span><span>The whole pipeline is open. Anyone can rebuild
      this dataset from the same documents and check that it reproduces exactly what you see here.
      Corrections are welcome from anyone, including the town.</span></p>`;
  sec.appendChild(effort);

  // ---- how the documents were read, and what would make it safer -------------
  const clause = document.createElement('div');
  clause.className = 'panel panel-pad';
  clause.style.marginBottom = 'var(--s5)';
  clause.innerHTML = `
    <h3 style="margin:0 0 var(--s3);font-size:var(--t-base);font-weight:640">
      How these documents were read — and what would make it safer</h3>
    <p style="margin:0 0 var(--s4);font-size:var(--t-sm);color:var(--text-secondary)">
      Some of the town's reports are published only as <strong>scanned images</strong> rather than as
      real digital files. Figures from those have to be recovered by character recognition. We do not
      take that recognition on trust: a recovered figure is shown only when its column adds up
      <em>exactly</em> to the total printed beside it on the same page, so a misread digit cannot pass
      unnoticed. Anything that fails that check is withheld rather than published.
    </p>
    <div class="callout warn" style="margin:0">
      <strong>Best practice: replace every scanned PDF with the original digital copy.</strong>
      A digital original is read directly, character for character, and removes this entire class of
      risk instead of managing it. Where the town has published a digital original we use it and
      ignore the scan completely — that is how the audited FY2025 figures on this page were read, and
      why they carry no recognition risk at all. Obtaining digital originals for the remaining years
      from the town is the single best thing anyone could do for the accuracy of this site.
    </div>
    <p class="reassure"><span class="ic" aria-hidden="true">✓</span><span>
      Every figure on this page records how it was read. You can see which documents are digital and
      which are scans in the list below, and the full method is in
      <span class="mono">docs/EXTRACTION_NOTES.md</span>.</span></p>`;
  sec.appendChild(clause);

  sec.appendChild(disclosure('See all the source documents', inner => {
    const rows = docs.slice().sort((a, b) =>
      (a.category || '').localeCompare(b.category) || a.filename.localeCompare(b.filename))
      .map(d => {
        const badge = d.format !== 'pdf' ? `<span class="badge">${esc(d.format)}</span>`
          : d.values_extractable ? `<span class="badge ok">readable</span>`
            : `<span class="badge warn">scanned — not used for figures</span>`;
        return `<tr><td>${esc(d.filename)}</td><td class="num">${d.fiscal_year || '—'}</td>
          <td class="num">${d.pages || '—'}</td>
          <td class="num">${(d.bytes / 1048576).toFixed(1)} MB</td><td>${badge}</td>
          <td class="mono" title="${esc(d.sha256 || '')}">${esc((d.sha256 || '').slice(0, 10))}</td></tr>`;
      }).join('');
    inner.innerHTML = `<div class="tablewrap"><table>
      <caption>The ${sum.unique_documents} documents behind this page. The code after each is the
        first part of its SHA-256 fingerprint, so you can prove your copy is the same file.</caption>
      <thead><tr><th>Document</th><th class="num">Year</th><th class="num">Pages</th>
        <th class="num">Size</th><th>Can we read it?</th><th>Fingerprint</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  }));

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
  renderYou(main);
  renderPaysFor(main);
  renderHealth(main);
  renderComing(main);
  renderVoice(main);
  renderReceipts(main);
  if (firstPaint) { setupScrollSpy(); firstPaint = false; }
}

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
    loadHome();
    const idx = await (await fetch('data/index.json')).json();
    const names = ['facts', 'metrics', 'documents', 'projections', 'requests', 'issues',
                   'household', 'audited', 'ocr_statements', 'warehouse_county', 'mfas',
                   'transfers', 'utility', 'cost_of_ownership'];
    const loaded = await Promise.all(names.map(n => idx.datasets[n]
      ? fetch('data/' + idx.datasets[n]).then(r => r.json()) : Promise.resolve(null)));
    state.data = Object.fromEntries(names.map((n, i) => [n, loaded[i]]));
    state.data.index = idx;

    const ys = state.data.facts.facts.map(f => f.fiscal_year).filter(v => v != null);
    state.yearMin = Math.min(...ys);
    state.yearMax = Math.max(...ys);

    $('#loading').remove();
    render();

    $('#chipCount').textContent = `${idx.counts.facts} figures, every one sourced`;
    $('#footMeta').textContent =
      `${idx.counts.facts} published figures · ${idx.counts.metrics} measures · ` +
      `${idx.counts.documents} source documents · ` +
      `${idx.counts.documents_with_trustworthy_text} readable · ` +
      `${idx.counts.documents_scanned_needing_transcription} scanned and excluded.`;
  } catch (err) {
    $('#loading').textContent =
      'Could not load the town’s figures. If you opened this file straight from your computer, your ' +
      'browser blocks the data load — open the published web address instead.';
    console.error(err);
  }
}

$('#themeToggle').addEventListener('click', () => {
  const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('hoa-theme', next); } catch (e) {}
});

boot();
