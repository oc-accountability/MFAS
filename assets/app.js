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
  homeValue: DEFAULT_HOME, location: 'intown', gallons: DEFAULT_GALLONS,
  returning: false, fromLink: false,
  // Which fields the link actually supplied, and which the reader has touched.
  // Both matter for honesty: the notice must only attribute to the sender the
  // values the sender actually sent, and saving must never adopt a link-supplied
  // value the reader did not edit themselves.
  linkFields: {}, touched: {},
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
    /* A link-supplied value the reader never edited must not become "theirs":
       changing the gallons dropdown used to silently persist a stranger's
       home value, and the next visit greeted the reader with it as their own.
       Fields still owned by the link keep whatever the reader had saved before
       (or stay unwritten, so the default returns). */
    const prev = JSON.parse(localStorage.getItem(STORE) || '{}');
    const keep = (field, key) =>
      (state.linkFields[field] && !state.touched[field]) ? prev[key] : state[key];
    const out = {
      homeValue: keep('home', 'homeValue'),
      location: keep('where', 'location'),
      gallons: keep('gal', 'gallons'),
    };
    for (const k of Object.keys(out)) if (out[k] === undefined) delete out[k];
    localStorage.setItem(STORE, JSON.stringify(out));
  } catch (e) { /* nothing here is worth breaking the page over */ }
}

/** Figures carried in the address, so one resident can send another the exact view.
 *
 * An explicit link beats a remembered setting, so this runs after loadHome() and
 * overrides it — but it does NOT overwrite the reader's own saved figures until
 * they touch a control, and the page says out loud whose figures these are. The
 * link carries three numbers the sender typed and nothing else: no address, no
 * parcel, nothing identifying.
 */
function loadShared() {
  let q;
  try { q = new URLSearchParams(location.search); } catch (e) { return; }
  const home = Number(q.get('home'));
  const where = q.get('where');
  /* Number('') is 0 — finite and non-negative — so a bare `gal=` in a link set the
     recipient's water use to zero and rendered a real-looking bill for it. The
     input handler already guards against exactly this; the link parser now does
     the same. And a home under $1,000 renders a styled, sourced $0 tax bill, so
     the accepted range starts where an assessed value plausibly could. */
  const galRaw = q.get('gal');
  const gal = Number(galRaw);
  /* The SAME bounds shareUrl() emits — MFAS.LIMITS, so the accept and emit domains
     cannot drift apart. See assets/domain.js. */
  const L = MFAS.LIMITS;
  if (Number.isFinite(home) && home >= L.home.min && home <= L.home.max) {
    state.homeValue = home; state.linkFields.home = true;
  }
  if (where === 'intown' || where === 'outoftown') {
    state.location = where; state.linkFields.where = true;
  }
  if (galRaw !== null && galRaw.trim() !== '' && Number.isFinite(gal)
      && gal >= L.gallons.min && gal <= L.gallons.max) {
    state.gallons = gal; state.linkFields.gal = true;
  }
  if (Object.keys(state.linkFields).length) { state.fromLink = true; state.returning = false; }
}

/** The link-supplied fields the reader has not yet made their own. The sender's-
 * figures notice, the printed sheet and the copied text all key off this: an
 * artefact that shows a stranger's number without saying so has told the reader
 * something untrue. */
function senderFields() {
  return ['home', 'where', 'gal'].filter(f => state.linkFields[f] && !state.touched[f]);
}

/** The most recent two years of the town rate, so "did not change" is measured
 * rather than asserted. Returns null when two years are not both published —
 * the claim is then withheld, not guessed. */
function townRateChange() {
  return MFAS.rateChange(state.data.facts.facts, 'property_tax_rate', docYear);
}

/** The address that reproduces exactly what the reader is looking at.
 *
 * Emit ONLY what loadShared() accepts. A reader who typed a $5B home value used
 * to get a link that silently opened at the $400,000 default on the recipient's
 * screen — and attributed that default to the sender. The two domains must match.
 */
function shareUrl() {
  const u = new URL(location.href);
  u.search = new URLSearchParams({
    home: String(MFAS.clampHome(Math.round(state.homeValue))),
    where: state.location,
    gal: String(MFAS.clampGallons(Math.round(state.gallons))),
  }).toString();
  u.hash = 'you';
  return u.toString();
}

/* ---------------------------------------------------------------- formatters */
const usd = n => '$' + Math.round(n).toLocaleString('en-US');
const usd2 = n => '$' + n.toLocaleString('en-US',
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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
   as "51.3%" would overstate the rate ~19.5x to anyone skimming.
   Precision follows the source: the county's rate is printed as 67.58 and its
   increase as 3.75, and rounding those to 67.6 / 3.8 put numbers on the page
   that the documents never printed — a reader checking against the manager's
   message found figures that do not appear in it. */
const cents = n => {
  if (n % 1 === 0) return n.toFixed(0);
  return (Math.round(n * 10) === n * 10) ? n.toFixed(1) : n.toFixed(2);
};
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
/* Some datasets record their source as a filename rather than a manifest id. */
function docIdForFilename(name) {
  for (const d of state.data.documents.documents) if (d.filename === name) return d.id;
  return null;
}
const facts = metric => state.data.facts.facts.filter(f => f.metric === metric);
const inRange = f => f.fiscal_year == null
  || (f.fiscal_year >= state.yearMin && f.fiscal_year <= state.yearMax);

/* Which reading of a metric to publish when several documents report it. The rule
   lives in assets/domain.js so the charts, the hero, the printed sheet and the
   copied text cannot each answer it differently — and so it can be tested without
   a browser. These are the page's thin bindings to it. */
const latestByYear = metric =>
  MFAS.latestByYear(state.data.facts.facts, metric, docYear);
const one = metric => MFAS.latestFact(state.data.facts.facts, metric, docYear);
const val = (metric, fb = null) => { const f = one(metric); return f ? f.value : fb; };
const forYear = (metric, fy) =>
  MFAS.factForYear(state.data.facts.facts, metric, fy, docYear);
function quote(key) {
  const qs = (state.data.household && state.data.household.town_statements) || [];
  return qs.find(q => q.key === key) || null;
}
function cite(f) {
  if (!f) return '';
  const d = docsById().get(f.source_doc);
  const name = d ? d.filename : f.source_doc;
  const label = esc(name + (f.source_page ? `, p.${f.source_page}` : ''));
  // Escaping makes the URL safe as HTML; it does not make the SCHEME safe. These
  // fields are contributor-supplied by design (docs/PROVENANCE.md invites them), and
  // a `javascript:` URL would become an executable link the moment someone fills one
  // in. Only https is rendered as a link — anything else falls through to plain text
  // rather than being silently dropped, so a bad entry is visible instead of invisible.
  if (d && d.official_url && /^https:\/\//i.test(String(d.official_url))) {
    return `<a class="src-link" rel="noopener noreferrer" href="${esc(d.official_url)}">${label}</a>`;
  }
  return `<span class="src-link" title="Source file and SHA-256 recorded in data/datasets/documents.json">${label}</span>`;
}

/* ------------------------------------------------- reporting a problem ------ */
const REPO = 'https://github.com/oc-accountability/MFAS';

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
    /* Rebuilt from known parts, never location.href: a crafted link could smuggle
       arbitrary markdown through an extra query parameter, and a resident pressing
       "report a problem" would publish the attacker's text — a fabricated figure
       with the site's name on it — into the public issue tracker. */
    `**Page**: ${location.origin + location.pathname}${state.fromLink
      ? `?home=${Math.round(state.homeValue)}&where=${state.location}`
        + `&gal=${Math.round(state.gallons)}` : ''}`,
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
// WCAG 1.4.13: hover/focus content must be dismissable without moving the pointer.
document.addEventListener('keydown', e => { if (e.key === 'Escape') hideTip(); });
function bindTip(el, html) {
  el.addEventListener('mouseenter', e => showTip(html, e));
  el.addEventListener('mousemove', e => showTip(html, e));
  el.addEventListener('mouseleave', hideTip);
  el.setAttribute('tabindex', '0');
  el.setAttribute('role', 'img');
  /* The tooltip's content, as the element's accessible name — without it a
     screen-reader user tabs through dozens of unnamed "image" stops whose
     values (the point of the chart) never reach them. Same strings, tags
     stripped, so the two cannot say different things. */
  el.setAttribute('aria-label',
    html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim());
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
      // This table did not exist when the last scan ran. Without this it is a
      // scrollable region a mouse can reach and a keyboard cannot — see the note
      // above markScrollableRegions().
      scheduleScrollableScan();
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
  // The number doubles as the section's own permalink, so a reader can send someone
  // straight to the part they are talking about.
  s.innerHTML = `<div class="sec-head">
    <a class="sec-num" href="#${id}" title="Link to this section"
       aria-label="${num} — link to this section: ${esc(title)}">${num}<span aria-hidden="true">#</span></a>
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
    /* Every table in here is created on this event, AFTER the load-time scan has
       already run — so before this line the keyboard-reachability fix covered only
       the two tables rendered at load, and missed the ~30 behind disclosures.
       Measured at 390px: 5 regions overflowed, 1 was reachable, 4 were WCAG
       scrollable-region-focusable failures. Runs on close too, which is what
       removes the tab stop again. */
    scheduleScrollableScan();
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
    'Bars below the line mean the town plans — or, for years already past, estimates — spending more than it collects, covering the gap from savings.',
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
  const dataMax = Math.max(...rows.map(r => r.value));
  const ticks = niceTicks(0, dataMax, 4);
  /* The scale must cover the data: when the top tick landed below the max, the
     tallest bar and its label overflowed the viewBox top and the most recent
     year's figure was clipped in half. */
  const thi = Math.max(Math.max(...ticks), dataMax * 1.08);
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
/** The whole monthly utility bill at the reader's own consumption.
 *
 *  The maths — the two-block rate structure and the fallback to the town's published
 *  increases at 2,000 and 4,000 gallons — is in assets/domain.js, where it is unit
 *  tested against both paths. This binds it to the reader's current answers. */
function utilMonthly() {
  return MFAS.utilityBill({
    utility: state.data && state.data.utility,
    gallons: state.gallons,
    location: state.location,
    increaseLookup: val,
  });
}
/* Removing the town tax from an out-of-town bill fixes an OVERSTATEMENT and must not
   quietly create an UNDERSTATEMENT in its place. An Orange County bill outside a
   municipality still carries a fire district tax, and in part of the county a school
   district tax as well. Those vary by district and this page does not resolve an address
   to a district, so the rates are not applied — the gap is named instead of guessed,
   which is the same rule the rest of the site runs on. */
const OUT_OF_TOWN_CAVEAT =
  `<span class="soft">This is the county levy only. An Orange County bill outside a
   municipality also carries a <strong>fire district tax</strong>, and in the
   Chapel Hill-Carrboro school district a <strong>special district tax</strong> as well —
   both vary by where the property sits, and this page does not work out which district an
   address falls in, so neither is included above.</span>`;

/** The TOWN's share — charged only to a home inside the town limits.
 *
 * This returned the town tax unconditionally until 2026-08-01, so a household that
 * answered "No, outside" was still shown the town's levy: at a $500,000 assessment the
 * page said $5,944 when the answer was $3,379, an overstatement of $2,565 a year (76%).
 * The page asks where the home is, promises "what your property tax actually costs you",
 * and then ignored the answer — on its primary trust surface.
 *
 * Orange County's own explainer is the authority for the rule, in its words:
 * "all taxpayers in the county will pay the Orange County tax due. Taxpayers who live
 * within the municipal boundaries of Chapel Hill, Carrboro, Hillsborough, and Mebane
 * will ALSO have a tax due to one of those municipalities."
 * (Understanding Your Property Tax Bill, Orange County, 1 Aug 2025.)
 */
function townTax() {
  if (state.location !== 'intown') return 0;
  return propertyBill().town.due;
}
/** Orange County's share — LARGER than the town's, and paid on top of it. */
function countyTax() {
  return propertyBill().county.due;
}

/** The whole property-tax bill, from the domain layer.
 *
 * `townLevyIfInTown()` and `totalPropertyTax()` used to sit here. Both were written to
 * be the single source for these figures and BOTH HAD ZERO CALL SITES — every surface
 * computed its own copy instead, which is exactly how the out-of-town defect survived
 * in four places at once. Worse, `totalPropertyTax()` used the opposite rounding rule
 * from the two live sites, so the first surface wired to the obviously-named helper
 * would have published a total $1 below the hero.
 *
 * They are gone. `MFAS.propertyTaxBill` is the single source, it is unit tested, and
 * it distinguishes "does not apply" from "unknown" from "zero" — so a caller can tell
 * when to withhold instead of printing a styled, sourced $0.
 */
function propertyBill() {
  return MFAS.propertyTaxBill({
    assessedValue: state.homeValue,
    location: state.location,
    townRateCents: val('property_tax_rate'),
    countyRateCents: val('county_property_tax_rate'),
  });
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

  const wSlot = document.createElement('div');
  sec.appendChild(wSlot);

  const panel = document.createElement('div');
  panel.className = 'panel panel-pad';
  panel.innerHTML = `
    <div class="calc">
      <div>
        <div class="field">
          <label class="field-label" for="hv">What is your home assessed at?</label>
          <input type="number" id="hv" min="0" max="1000000000" step="5000"
                 value="${state.homeValue}" inputmode="numeric">
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
      </div>
    </div>
    <!-- Full width, below both columns. Inside the readout it made the right column
         far taller than the left and left a quarter of the panel empty, and it is the
         one sentence in this section a reader most needs to see. -->
    <div class="callout" id="calloutBox"></div>`;
  sec.appendChild(panel);

  const snap = document.createElement('div');
  snap.className = 'snapshot';
  snap.style.marginTop = 'var(--s5)';
  snap.id = 'snapshot';
  sec.appendChild(snap);

  host.appendChild(sec);

  const num = $('#hv', sec), rng = $('#hvr', sec);

  /* Rebuilt on every draw, from current state. The old notice was written once and
     never touched again, so after the reader typed their own value it still said
     "these are the sender's figures" above an input showing the reader's own — two
     contradictory statements on one screen. It also attributed values to the sender
     that the link never carried (a bare ?where=intown link disclaimed the reader's
     own saved home value as a stranger's). */
  function drawWelcome() {
    const sf = senderFields();
    if (sf.length) {
      const bits = [];
      if (sf.includes('home')) bits.push(`a home assessed at <strong>${usd(state.homeValue)}</strong>`);
      if (sf.includes('where')) bits.push(state.location === 'intown'
        ? 'inside town limits' : 'outside town limits');
      if (sf.includes('gal')) bits.push(`water use of
        <strong>${state.gallons.toLocaleString('en-US')} gallons a month</strong>`);
      wSlot.innerHTML = `<div class="welcome"><span>You followed a link that set
        ${bits.join(', ')}. ${bits.length === 3 || sf.includes('home')
          ? "These are the sender's figures, not yours."
          : "Those came from the sender, not from you."}</span>
        <button type="button" id="changeHome">Use my own instead</button></div>`;
    } else if (state.returning) {
      const where = state.location === 'intown' ? 'inside town limits' : 'outside town';
      wSlot.innerHTML = `<div class="welcome"><span>Welcome back — showing figures for a home
        assessed at <strong>${usd(state.homeValue)}</strong>, ${where}.</span>
        <button type="button" id="changeHome">Not yours? Change it</button></div>`;
    } else {
      wSlot.innerHTML = '';
    }
    const chg = $('#changeHome', wSlot);
    if (chg) chg.addEventListener('click', () => {
      if (senderFields().length) {
        /* "Use my own instead" must DO that: put back what the reader had saved
           (or the defaults), for every field still carrying the sender's value. */
        let saved = {};
        try { saved = JSON.parse(localStorage.getItem(STORE) || '{}'); } catch (e) {}
        if (state.linkFields.home && !state.touched.home) {
          state.homeValue = (typeof saved.homeValue === 'number' && saved.homeValue > 0)
            ? saved.homeValue : DEFAULT_HOME;
        }
        if (state.linkFields.where && !state.touched.where) {
          state.location = (saved.location === 'intown' || saved.location === 'outoftown')
            ? saved.location : 'intown';
        }
        if (state.linkFields.gal && !state.touched.gal) {
          state.gallons = (typeof saved.gallons === 'number' && saved.gallons >= 0)
            ? saved.gallons : DEFAULT_GALLONS;
        }
        state.linkFields = {};
        state.returning = Object.keys(saved).length > 0;
        num.value = state.homeValue; rng.value = state.homeValue;
        const gs = $('#galSel', sec), gn = $('#galNum', sec);
        if (gn) gn.value = state.gallons;
        if (gs) gs.value = GAL_PRESETS.includes(state.gallons) ? String(state.gallons) : 'custom';
        $$('[data-loc]', sec).forEach(o =>
          o.setAttribute('aria-pressed', String(o.dataset.loc === state.location)));
        draw(false);
        refreshDependents();
      } else {
        num.focus();
        num.scrollIntoView({ block: 'center', behavior: REDUCED ? 'auto' : 'smooth' });
      }
    });
  }

  function draw(animate) {
    state.homeValue = Math.min(1e9, Math.max(0, +num.value || 0));
    drawWelcome();
    const annual = townTax();
    const county = countyTax();
    const oneCent = MFAS.oneCentOnValue(state.homeValue);
    const u = utilMonthly();
    /* The headline is the sum of the rounded rows beneath it, not a separately
       rounded exact total: at many home values the two differed by $1, on a sheet
       that invites the reader to check it with a calculator. */
    const annualR = Math.round(annual);
    const countyR = county != null ? Math.round(county) : null;
    const total = annualR + (countyR || 0);

    const inTown = state.location === 'intown';
    setFigure($('#heroV', sec), total, animate);
    $('#heroN', sec).innerHTML = !inTown
      ? (county != null
        ? `That is <strong>${usd(countyR / 12)} a month</strong>, all of it to Orange County at
           ${cents(cRate.value)} cents per $100. <strong>No town property tax</strong> — the
           county's own bill explainer puts it plainly: every taxpayer in the county pays the
           county tax, and only those inside Chapel Hill, Carrboro, Hillsborough or Mebane
           <em>also</em> pay a municipal tax. Source: ${cite(cRate)}.
           ${OUT_OF_TOWN_CAVEAT}`
        : '')
      : county != null
        ? `That is <strong>${usd(total / 12)} a month</strong> — ${usd(annualR)} to the town at
           ${cents(rateF.value)} cents per $100, plus ${usd(countyR)} to Orange County at
           ${cents(cRate.value)} cents. Sources: ${cite(rateF)} and ${cite(cRate)}.`
        : `That is <strong>${usd(annualR / 12)} a month</strong>, at the FY${rateF.fiscal_year} rate of
           ${cents(rateF.value)} cents per $100 of value. Source: ${cite(rateF)}.`;

    /* "The town rate did not change" is measured against the prior year's published
       rate, never asserted: when the two years are not both in the data, the claim
       is dropped rather than guessed — a sub-label that silently went stale is how
       three sentences on this page became false the last time. */
    const rc = townRateChange();
    const rateNote = rc == null ? ''
      : rc.delta === 0 ? ' — the town rate did not change'
        : rc.delta > 0 ? ` — the town rate rose ${cents(rc.delta)} cents`
          : ` — the town rate fell ${cents(-rc.delta)} cents`;
    const rows = [];
    if (inTown) {
      rows.push(['Town of Hillsborough', `<small>FY${rateF.fiscal_year}${rateNote}</small>`,
        usd(annualR) + ' / yr']);
    }
    if (county != null) {
      const inc = val('county_tax_rate_increase_cents');
      rows.push(['Orange County',
        `<small>FY${cRate.fiscal_year}${inc ? ` — the county rate rose ${cents(inc)} cents` : ''}</small>`,
        usd(countyR) + ' / yr']);
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
    /* The town states "over N cents" — a floor, not an exact figure — so the dollar
       translation is "at least", and the row does not attribute the flat-N-cents
       arithmetic to the town (its own printed example is $440 on a $400,000 home,
       which implies ~11 cents). */
    const need = one('tax_rate_increase_needed_cents');
    if (need) rows.push([`If the rate rose ${cents(need.value)} cents`,
      `<small>the town says over ${cents(need.value)} cents would be needed by
       FY${need.fiscal_year}</small>`,
      'at least +' + usd(oneCent * need.value) + ' / yr']);

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

    /* Two honesty rules here. The "held steady" framing only renders when the data
       shows the town rate actually flat year-over-year — it used to be asserted
       whenever a county increase existed. And u.total includes the stormwater fee
       rise, so attributing all of it to "water and sewer" put a number on the page
       ($10.21) that the town's own rate-impact table (3.72 + 5.24) does not show. */
    const box = $('#calloutBox', sec);
    const wr = val('water_rate_increase_pct'), sr = val('sewer_rate_increase_pct');
    const townFlat = rc != null && rc.delta === 0;
    if (cInc && u.total > 0 && wr && townFlat) {
      box.className = 'callout warn';
      box.innerHTML = `<strong>The town's rate held steady — the rest of your bill did not.</strong>
        Orange County's rate rose ${cents(cInc)} cents, which adds
        <strong>${usd(addedTax)} a year</strong> for a home like yours, and water, sewer and the
        stormwater fee together add about ${usd2(u.total)} a month. "No town tax increase" is true
        and is not the same as "your bill is flat".`;
    } else if (u.total > 0 && wr && sr && townFlat) {
      box.className = 'callout warn';
      box.innerHTML = `<strong>Your property tax rate did not go up — but your bill still does.</strong>
        Water and sewer rates each rise ${pctPlain(wr)} in FY2027, and with the stormwater fee
        that adds about <strong>${usd2(u.total)} a month</strong> for a household like yours. A
        flat tax rate is not the same as a flat bill, and that distinction is easy to miss.`;
    } else if (townFlat) {
      box.className = 'callout';
      box.innerHTML = `The property tax rate is unchanged for FY${rateF.fiscal_year}.`;
    } else if (rc != null && rc.delta !== 0) {
      box.className = 'callout warn';
      box.innerHTML = `The town's rate ${rc.delta > 0 ? 'rises' : 'falls'} by
        <strong>${cents(Math.abs(rc.delta))} cents</strong> for FY${rateF.fiscal_year} against
        FY${rc.prev.fiscal_year}'s published rate.`;
    } else {
      box.className = 'callout';
      box.innerHTML = `The FY${rateF.fiscal_year} rate is ${cents(rateF.value)} cents per $100
        of assessed value.`;
    }

    // snapshot
    const s = $('#snapshot', sec);
    s.innerHTML = `<h3>Your snapshot</h3>
      <div class="big">${usd(total)}<span style="font-size:var(--t-md);font-weight:500;
        letter-spacing:0;margin-left:.35em">in property tax this year</span></div>
      <p class="cap">${county != null
        ? `${usd(annualR)} to the town, ${usd(countyR)} to Orange County. `
        : ''}Plus about ${usd(u.total * 12)} more over the year as water, sewer and stormwater
        rates rise.
        Based on a home assessed at ${usd(state.homeValue)},
        ${state.location === 'intown' ? 'inside' : 'outside'} town limits.</p>
      <div class="acts">
        <button type="button" id="printSnap">Print a one-page summary</button>
        <button type="button" id="copySnap">Copy these figures</button>
        <button type="button" id="linkSnap">Copy a link to them</button>
      </div>
      <p class="reassure" style="margin-top:var(--s4)"><span class="ic" aria-hidden="true">✓</span>
        <span>Estimated from the assessed value you entered and the town's published rates. Your
        actual bill depends on your county assessment.</span></p>`;
    $('#printSnap', s).addEventListener('click', printTakeaway);
    $('#copySnap', s).addEventListener('click', ev => {
      /* The copied text leaves the page, so it must carry its own provenance: a
         reader who arrived on a stranger's link used to copy "my share ...
         $999,999,999" in the first person with the site's citation under it. */
      const sender = senderFields().length > 0;
      const docNames = [rateF.source_doc, cRate && cRate.source_doc,
        u.exact && state.data.utility ? docIdForFilename(state.data.utility.source_doc)
          || state.data.utility.source_doc : null]
        .filter(Boolean)
        .map(id => (docsById().get(id) || {}).filename || id);
      const text = `Town of Hillsborough — ${sender
          ? 'figures from a link someone shared (not this household’s own)'
          : 'my share'}, FY${rateF.fiscal_year}\n` +
        `Home assessed at ${usd(state.homeValue)} (${state.location === 'intown'
          ? 'in town' : 'out of town'})\n` +
        `Town property tax: ${usd(annualR)}/yr\n` +
        (county != null ? `Orange County property tax: ${usd(countyR)}/yr\n` +
          `Total property tax: ${usd(total)}/yr (${usd(total / 12)}/mo)\n` : '') +
        `Water/sewer/stormwater increase: +${usd2(u.total)}/mo (about ${usd(u.total * 12)}/yr)\n` +
        `Tax rate: ${cents(rateF.value)} cents per $100${rc && rc.delta === 0
          ? ` — unchanged for FY${rateF.fiscal_year}` : ''}\n` +
        `Sources: ${[...new Set(docNames)].join('; ')}\n` +
        `Check it yourself: ${shareUrl()}`;
      offerCopy(ev.currentTarget, text, 'Copy these figures');
    });
    $('#linkSnap', s).addEventListener('click', async ev => {
      const url = shareUrl();
      // On a phone the OS share sheet is what people actually use to send a link.
      if (navigator.share) {
        try {
          await navigator.share({ title: 'What the town and county cost this household', url });
          return;
        } catch (e) { /* dismissed, or unsupported for this payload — fall through */ }
      }
      offerCopy(ev.currentTarget, url, 'Copy a link to them');
    });
    /* A shared link must not quietly replace the visitor's own saved figures.
       saveHome() itself keeps link-supplied, untouched fields out of storage, so
       saving here is safe even mid-link: only what the reader edited persists. */
    saveHome();
  }

  const rerender = field => { if (field) state.touched[field] = true; draw(false); refreshDependents(); };
  num.addEventListener('input', () => { rng.value = num.value; rerender('home'); });
  rng.addEventListener('input', () => { num.value = rng.value; rerender('home'); });
  $$('.seg button', sec).forEach(b => b.addEventListener('click', () => {
    state.location = b.dataset.loc;
    $$('[data-loc]', sec).forEach(o => o.setAttribute('aria-pressed', String(o === b)));
    rerender('where');
  }));

  // Water use: the dropdown and the number box are two views of one value.
  const galSel = $('#galSel', sec), galNum = $('#galNum', sec);
  if (galSel && galNum) {
    galSel.addEventListener('change', () => {
      if (galSel.value === 'custom') { galNum.focus(); galNum.select(); return; }
      state.gallons = Number(galSel.value);
      galNum.value = state.gallons;
      rerender('gal');
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
      rerender('gal');
    });
  }
  draw(!REDUCED && !state.returning);
}

/** Copy to the clipboard, and if that is refused, show the text so it can be copied.
 *
 * The clipboard needs a secure context and a permission that some browsers and most
 * privacy modes decline. The old handler reported "Copy blocked" and stopped there,
 * which leaves the reader with no way to get the thing they asked for.
 */
async function offerCopy(btn, text, restoreLabel) {
  try {
    await navigator.clipboard.writeText(text);
    btn.textContent = 'Copied';
    setTimeout(() => { btn.textContent = restoreLabel; }, 1800);
    return;
  } catch (e) { /* fall through to the manual route */ }
  const box = document.createElement('textarea');
  box.className = 'copy-fallback';
  box.readOnly = true;
  box.rows = Math.min(8, text.split('\n').length + 1);
  box.value = text;
  box.setAttribute('aria-label', 'Select and copy this text');
  /* after(), not replaceWith(): swallowing the button meant one clipboard refusal
     removed the control for the rest of the session. */
  btn.textContent = 'Select and copy below';
  btn.after(box);
  box.focus();
  box.select();
}

/* ==================== the one-page takeaway ====================
 *
 * "Print or save as PDF" used to call window.print() on the whole document — about
 * twenty pages of charts, tables and source lists. What a resident going to a board
 * meeting actually wants is one sheet: their own figures, the handful of facts that
 * explain them, and the documents each came from so anyone can check it there and
 * then.
 *
 * It is built into a hidden element and revealed only for that one print, so a plain
 * Ctrl+P still prints the page the reader is looking at. Nothing here is computed
 * differently from the screen — same helpers, same sources — because a printout that
 * disagreed with the site would be worse than no printout.
 */
function takeawayHTML() {
  const rateF = one('property_tax_rate'), cRate = one('county_property_tax_rate');
  if (!rateF) return '';
  const annual = townTax(), county = countyTax();
  /* Headline = sum of the rounded rows below it. The sheet invites checking with a
     calculator, and rounding the exact total separately handed over a $1
     self-inconsistency at many home values. */
  const annualR = Math.round(annual);
  const countyR = county != null ? Math.round(county) : null;
  const total = annualR + (countyR || 0);
  const u = utilMonthly();
  const oneCent = MFAS.oneCentOnValue(state.homeValue);
  const idx = state.data.index || {};
  const rc = townRateChange();

  const row = (k, v, note) => `<tr><th>${k}${note ? `<small>${note}</small>` : ''}</th>
    <td>${v}</td></tr>`;
  /* The printout must match the screen exactly. When the town row is suppressed on
     screen and kept here, the sheet a reader carries into a meeting is the wrong one —
     which is worse than no sheet. */
  const rows = state.location === 'intown'
    ? [row('Town of Hillsborough', usd(annualR) + ' / yr',
        `${cents(rateF.value)} cents per $100 of assessed value, FY${rateF.fiscal_year}`)]
    : [];
  if (county != null) rows.push(row('Orange County', usd(countyR) + ' / yr',
    `${cents(cRate.value)} cents per $100, FY${cRate.fiscal_year}`));
  if (u.exact) {
    /* Annual, like the rows above it — a sheet that mixes /yr and /mo down one column
       invites the reader to add them together and get a wrong number. The two are
       still kept apart from the tax rows and never summed: water and sewer are paid
       by users of the service, not out of taxes, and the site says so throughout. */
    rows.push(row('Water, sewer and stormwater', usd(u.billTotal * 12) + ' / yr',
      `${usd2(u.billTotal)} a month at ${u.gallons.toLocaleString('en-US')} gallons, `
      + `${state.location === 'intown' ? 'inside' : 'outside'} town limits — `
      + `charged for the service, not out of property tax`));
  }
  rows.push(row('One cent on the town tax rate', usd(oneCent) + ' / yr',
    'what a single cent of rate costs a home assessed at this value'));

  /* Only facts that are on the page already, each with its document and page. */
  const facts = [];
  const wr = val('water_rate_increase_pct');
  const cInc = val('county_tax_rate_increase_cents');
  if (cInc && rc && rc.delta === 0) {
    facts.push(`The town's rate is unchanged for FY${rateF.fiscal_year}; Orange County's
      rose ${cents(cInc)} cents.`);
  } else if (cInc) {
    facts.push(`Orange County's rate rose ${cents(cInc)} cents for FY${cRate.fiscal_year}.`);
  }
  if (wr) facts.push(`Water and sewer rates each rise ${pctPlain(wr)}, and the town recommends the
    same again for the two years after.`);
  const now = forYear('general_fund_balance_pct_of_expenditures', 2027)
    || one('general_fund_balance_pct_of_expenditures');
  const far = latestByYear('general_fund_balance_pct_of_expenditures').slice(-1)[0];
  if (now && far && far.fiscal_year !== now.fiscal_year) {
    facts.push(`The town holds savings worth ${pctPlain(now.value)} of a year's spending in
      FY${now.fiscal_year}, against a floor of 50% it sets for itself, and projects
      ${pctPlain(far.value)} by FY${far.fiscal_year}.`);
  }
  const need = one('tax_rate_increase_needed_cents');
  if (need) facts.push(`Closing the FY${need.fiscal_year} shortfall the town projects would take
    a rise it puts at over ${cents(need.value)} cents — at least ${usd(oneCent * need.value)}
    a year on this home.`);

  /* One line per distinct document behind the figures above — including the fee
     schedule the utility bill is computed from, which the old list omitted: the
     sheet printed a utility figure its own source list could not explain. Pages
     are printed per document, because the sheet is the one artefact a resident
     carries where they cannot click through for the page number. */
  const srcFacts = [rateF, cRate, one('water_rate_increase_pct'), now, far, need].filter(Boolean);
  const srcPages = new Map();
  for (const f of srcFacts) {
    if (!srcPages.has(f.source_doc)) srcPages.set(f.source_doc, new Set());
    if (f.source_page) srcPages.get(f.source_doc).add(f.source_page);
  }
  if (u.exact && state.data.utility && state.data.utility.source_doc) {
    const uid = docIdForFilename(state.data.utility.source_doc) || state.data.utility.source_doc;
    if (!srcPages.has(uid)) srcPages.set(uid, new Set());
    for (const rs of Object.values(state.data.utility.rate_sets || {})) {
      if (rs.source_page) srcPages.get(uid).add(rs.source_page);
    }
    const sw = state.data.utility.stormwater || {};
    if (sw.source_page) srcPages.get(uid).add(sw.source_page);
  }
  const srcs = [...srcPages.entries()].map(([id, pages]) => {
    const d = docsById().get(id) || {};
    const pp = [...pages].sort((a, b) => a - b);
    return `<li>${esc(d.filename || id)}${pp.length
      ? ` <span class="pp">${pp.length === 1 ? 'p.' : 'pp.'}${pp.join(', ')}</span>` : ''}${d.sha256
      ? ` <span class="fp">${esc(d.sha256.slice(0, 10))}</span>` : ''}</li>`;
  }).join('');

  /* The sheet leaves the page, so it carries its own provenance: a reader who
     arrived on a stranger's link used to print a sheet presenting the sender's
     figures as this household's, with nothing on it saying otherwise. */
  const sender = senderFields().length > 0;
  return `
    <h1>What local government costs this household</h1>
    <p class="sub">Estimated for a home assessed at <strong>${usd(state.homeValue)}</strong>,
      ${state.location === 'intown' ? 'inside' : 'outside'} Hillsborough town limits, using the
      published FY${rateF.fiscal_year} rates. Your actual bill depends on your county
      assessment.${sender ? ` <strong>These figures came from a link someone shared — they are
      not this household's own. Enter yours at the site for a sheet that is.</strong>` : ''}</p>
    <p class="headline">${usd(total)}<span> in property tax a year —
      ${usd(total / 12)} a month</span></p>
    <table>${rows.join('')}</table>
    ${facts.length ? `<h2>What the documents say</h2>
      <ul class="facts">${facts.map(f => `<li>${f}</li>`).join('')}</ul>` : ''}
    <h2>Where these numbers came from</h2>
    <ul class="srcs">${srcs}</ul>
    <p class="foot">Built by residents for the Orange County Efficiency &amp; Accountability
      Initiative, not by the town or the county. Every figure on the website names the document
      it came from — and the page, wherever the document has pages — and the whole dataset can
      be rebuilt from those documents.
      ${idx.counts ? `The site's figures trace to ${idx.counts.documents_cited
        || 'a handful of'} source documents, held in an archive of
      ${idx.counts.documents} catalogued files. ` : ''}Check it, and report anything that looks
      wrong, at <span class="site-url">oc-accountability.github.io/MFAS</span></p>`;
}

function refreshTakeaway() {
  let el = document.getElementById('takeaway');
  if (!el) {
    el = document.createElement('div');
    el.id = 'takeaway';
    el.setAttribute('aria-hidden', 'true');
    document.body.appendChild(el);
  }
  el.innerHTML = takeawayHTML();
}

/** Print just the takeaway, then put the page back exactly as it was. */
function printTakeaway() {
  refreshTakeaway();
  document.body.classList.add('printing-takeaway');
  const restore = () => document.body.classList.remove('printing-takeaway');
  // onafterprint is not fired by every browser/print path, so a timer backs it up.
  addEventListener('afterprint', restore, { once: true });
  setTimeout(restore, 4000);
  window.print();
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
let _explorerRepaint = null;
function refreshDependents() {
  const pf = $('#paysforAnswer');
  if (pf) pf.innerHTML = paysForAnswer();
  /* The spending explorer prints a "of yours" share against every department, computed
     from the town tax. Changing the in/out-of-town answer changes that to
     not-applicable, and without this the explorer kept the previous answer's figures
     until the reader happened to touch one of its own controls. */
  if (typeof _explorerRepaint === 'function') _explorerRepaint();
  scheduleScrollableScan();
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
  const annual = townTax();
  if (!gf || !total || annual == null) return '';
  /* Out of town this sentence used to open "Your $2,565 in town property tax", to a
     household that pays the town nothing. */
  if (state.location !== 'intown') {
    return `You pay <strong>no town property tax</strong> — the home is outside the town
      limits. The town's <strong>General Fund</strong> is
      <span class="fig">${compact(gf.value)}</span> of its
      <span class="fig">${compact(total.value)}</span> total budget, funded by the
      households and businesses inside the limits. <span class="soft">Your water, sewer and
      stormwater bills are charged separately and are not tax money.</span>`;
  }
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
    <!-- dt/dd are only valid inside a dl (optionally wrapped in a div). This was a
         plain div, so assistive technology saw orphaned terms with no list semantics. -->
    <dl class="gloss" style="margin-top:var(--s6)">${parts.map(p =>
      `<div><dt>${esc(p.label)}</dt><dd>${esc(p.blurb)}</dd></div>`).join('')}</dl>
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
        <h3 class="block-title">
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
          unclassified rather than forced into a bucket.${(rd.source_docs || []).length
            ? ` Source: ${rd.source_docs.map(id => cite({ source_doc: id })).join('; ')}.` : ''}
          </span></p>`;
      sec.appendChild(p4);
    }
  }

  // The real answer to "where does it go" is the account-level detail. Behind a
  // disclosure so the ~790 KB dataset is only fetched if the reader wants it, and
  // ahead of the transfer schedule because it is the question they actually have.
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
            ${esc(tf.limitation)}${(cur.source_docs || []).length
              /* The table's nine dollar cells named no document at all — the one
                 rule this site has. The schedule now carries its sources. */
              ? ` Source: ${cur.source_docs.map(id => cite({ source_doc: id })).join('; ')}${
                cur.source_pages ? `, pp.${cur.source_pages[0]}–${cur.source_pages[1]}` : ''}.`
              : ''}</span></p>`;
      }));
    }
  }

  revenueBlock(sec);
  whoProvidesWhat(sec);
  structureBlock(sec);
  host.appendChild(sec);
}

/**
 * Where the money comes from — because the site was lopsided.
 *
 * It explained what a resident pays and what the town spends in detail, but treated
 * revenue as one number, which quietly implies property tax funds everything. It funds
 * about two thirds. A reader who believes otherwise will misjudge every tradeoff here.
 *
 * Shares are drawn ONLY for years whose components sum to the stated total. In the actual
 * years they do not — audited statements and budget schedules count transfers and
 * appropriated fund balance differently — so those years are shown as amounts with the
 * variance stated, never as a percentage of a total the parts do not make up.
 */
function revenueBlock(sec) {
  const d = state.data.revenue;
  if (!d || !d.years) return;
  const usable = d.years.filter(y => y.shares_publishable);
  if (!usable.length) return;
  const latest = usable[usable.length - 1];
  const w = d.who_funds_the_town || {};
  const defs = d.component_definitions || {};
  const order = Object.keys(defs).filter(k => latest.components[k] != null);

  const card = document.createElement('div');
  card.className = 'card revenue';
  /* Two corrections here. "The rest arrives from other governments or comes out of
     savings" left out a third of "the rest" — interest earned and transfers between
     the town's own funds are neither. And the card named no source at all while
     the masthead promises one on the spot: these rows are imported from the
     initiative's own trend workbook, which the note now says and cites. */
  card.innerHTML = `
    <h3>Where the money comes from</h3>
    <p>Property tax is the largest single source but not the whole story &mdash;
      <strong>${w.property_tax_share_pct != null ? pctPlain(w.property_tax_share_pct)
        : ''}</strong> of the General Fund in FY${latest.fiscal_year}. About
      <strong>${w.raised_locally_pct != null ? pctPlain(w.raised_locally_pct) : ''}</strong>
      is raised locally; the rest arrives from other governments, moves in from the town's
      own other funds, is interest earned, or comes out of savings.</p>
    <ul class="rows" id="revRows"></ul>
    <p class="note"><span class="ic" aria-hidden="true">✓</span>
      <span>These rows are imported from the initiative's own trend workbook
      ${d.source_doc ? `(${cite({ source_doc: d.source_doc })})` : ''} rather than read from a
      government document, and each year's parts are checked against its stated total.
      ${esc((d.caveats || [])[0] || '')} Shares are shown only for years whose parts add
      up to the published total: the two budget years do, to the dollar, while the audited
      years differ by up to $2.9M because budget schedules and audited statements count
      transfers and savings differently. That difference is a question for the town, not
      something this page resolves.</span></p>`;
  const ul = card.querySelector('#revRows');
  for (const k of order) {
    const v = latest.components[k];
    const share = (latest.share_of_total || {})[k];
    const li = document.createElement('li');
    li.innerHTML = `<span class="k">${esc(k)}<small>${esc(defs[k] || '')}</small></span>
      <span class="v">${compact(v)}<small>${share != null ? pctPlain(share) : ''}</small></span>`;
    ul.appendChild(li);
  }
  sec.appendChild(card);
}

/**
 * The structural question, posed and left open.
 *
 * Amy's own words: "I end up reading 2 budgets, and 2 tax calculations, to figure out why
 * my taxes are going up... I wonder why this government is structured this way. I want
 * this to highlight this insight." And in the same message: "But I don't want my opinion
 * or me to tell anybody what is right or wrong."
 *
 * So this shows the measurable part — the page count, the service that is already shared,
 * the town's administrative share — and then says explicitly what the documents cannot
 * settle. It argues nothing. The one figure a reader would most want, the county's
 * administrative cost beside the town's, is deliberately absent because it has not been
 * extracted, and half a comparison is worse than none.
 */
function structureBlock(sec) {
  const s = state.data.structure;
  if (!s || !s.reading_burden) return;
  const b = s.reading_burden;
  const sh = s.already_shared;
  const sep = s.run_separately || {};
  const a = sep.administration_broad || {}, n = sep.administration_narrow || {};

  const card = document.createElement('div');
  card.className = 'card structure';
  card.innerHTML = `
    <h3>Why does this take two budgets to answer?</h3>
    <p class="lead">To work out why your bill went up, you have to read
      <strong>${b.current_cycle_pages.toLocaleString('en-US')} pages</strong> across
      <strong>${b.current_cycle_documents} documents</strong> from
      <strong>${b.governments_a_resident_must_read} governments</strong>, then combine
      <strong>${b.tax_calculations_to_combine} separate tax calculations</strong> yourself.</p>
    <ul class="rows">
      ${Object.entries(b.by_government).filter(([g]) => g !== 'unstated')
        .sort((x, y) => y[1].pages - x[1].pages)
        .map(([g, v]) => `<li><span class="k">${esc(g)}
          <small>${v.documents} document${v.documents === 1 ? '' : 's'} for this budget
          cycle</small></span>
          <span class="v">${v.pages.toLocaleString('en-US')}<small>pages</small></span></li>`)
        .join('')}
    </ul>
    ${sh ? `<h4>What is already shared</h4>
      <p>${esc(sh.arrangement || '')}</p>
      <p class="soft">So this service is <strong>not</strong> duplicated, and at
        ${sh.current_fee_pct_of_collections}% of collections the town currently pays about a
        third of the ${sh.county_fee_study_peer_average_pct}% average the county's own fee
        study found among its peers.${sh.proposed_increase_declined
          ? ` A proposed increase &mdash; ${usd(sh.proposed_increase_declined.fy2027)} next year,
             ${usd(sh.proposed_increase_declined.three_year)} over three &mdash; was not funded.`
          : ''}${sh.source_doc
          /* These percentages sat with no citation at all — against the one rule. */
          ? ` Source: ${cite({ source_doc: sh.source_doc, source_page: sh.source_page })}.` : ''}</p>`
      : ''}
    ${a.total ? `<h4>What each government runs for itself</h4>
      <p>The town's own administrative departments &mdash; accounting, administration, human
        resources, IT, communications, risk, facilities and the governing body &mdash; come to
        <strong>${compact(a.total)}</strong>, or ${pctPlain(a.share_of_general_fund_pct)} of its
        General Fund. Counted more narrowly, excluding
        ${esc((n.excludes || []).join(' and '))}, it is <strong>${compact(n.total)}</strong>
        (${pctPlain(n.share_of_general_fund_pct)}). Both figures are given because the boundary
        is genuinely arguable.${(sep.source_docs || []).length
          ? ` Source: ${sep.source_docs.map(id => cite({ source_doc: id })).join('; ')},
             FY${sep.fiscal_year} ${esc(sep.basis || '')} line items.` : ''}</p>
      <p class="soft"><strong>${esc(sep.county_note || '')}</strong></p>` : ''}
    <h4>What these documents cannot tell you</h4>
    <ul class="plain">${(s.what_the_documents_cannot_answer || [])
      .map(x => `<li>${esc(x)}</li>`).join('')}</ul>
    <p class="note"><span class="ic" aria-hidden="true">✓</span>
      <span>This page does not take a position on how local government should be organised.
      It counts what can be counted, describes what the documents say, and leaves the
      question with you.</span></p>`;
  sec.appendChild(card);
}

/**
 * Why the county's share of the bill is the bigger one.
 *
 * The page can already show that Orange County charges more per $100 than the town does,
 * which surprises most people. It could not show *why*. The answer is simply that the two
 * governments buy different things, and the county buys the expensive ones — schools, the
 * sheriff, social services, public health, EMS.
 *
 * Everything here is a service name from the initiative's own project scope, not a
 * spending figure, so there is nothing to reconcile and nothing is implied about value.
 */
function whoProvidesWhat(sec) {
  const c = state.data.context;
  if (!c || !c.who_provides_what) return;
  const w = c.who_provides_what;
  const county = w['Orange County'] || [], town = w['Town of Hillsborough'] || [];
  if (!county.length || !town.length) return;

  const tRate = val('property_tax_rate'), cRate = val('county_property_tax_rate');
  const card = document.createElement('div');
  card.className = 'card split';
  card.innerHTML = `
    <h3>Two governments, one bill</h3>
    <p>Your property tax funds two separate governments, and they buy different things.
      ${cRate && tRate ? `Orange County charges <strong>${cents(cRate)} cents</strong> per $100
        and the town <strong>${cents(tRate)} cents</strong> — the county's is the larger share,
        which surprises most people until you see what each one pays for.` : ''}</p>
    <div class="split-cols">
      <div>
        <h4>Orange County provides</h4>
        <ul>${county.map(s => `<li>${esc(s)}</li>`).join('')}</ul>
      </div>
      <div>
        <h4>The Town of Hillsborough provides</h4>
        <ul>${town.map(s => `<li>${esc(s)}</li>`).join('')}</ul>
      </div>
    </div>
    <p class="note"><span class="ic" aria-hidden="true">✓</span>
      <span>${esc(c.why_two_governments_matter || '')} These are service names from the
      initiative's project scope, not spending figures &mdash; the split shows what each
      government is responsible for, not how well it does it.</span></p>`;
  sec.appendChild(card);
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
    const yourTax = townTax() || 0;
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
      ${verified == null && _liv ? `<div class="callout" style="margin:0 0 var(--s5)">
        No reconciliation checks exist for the ${esc(st.fund)} in this build, so these figures
        carry no verification either way — unlike the checked funds, where every slice is
        either proven against a published total or flagged.</div>` : ''}
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
        /* yourTax is 0 outside the town limits; without the guard every department
           row rendered "$0 of yours", which reads as a measurement rather than as
           not-applicable. */
        const yours = taxFunded && total && yourTax ? yourTax * (e.total / total) : null;
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
                ${(() => {
                  /* The full page RANGE: half these department groups span two
                     pages, and citing only the largest row's page made the
                     printed cite wrong for every row on the other page. */
                  const pp = [...new Set(accounts.map(r => r[C.page]).filter(Boolean))]
                    .sort((x, y) => x - y);
                  const d = docsById().get(accounts[0][C.source_doc]);
                  const name = d ? d.filename : accounts[0][C.source_doc];
                  const label = pp.length > 1 ? `${name}, pp.${pp[0]}–${pp[pp.length - 1]}`
                    : pp.length ? `${name}, p.${pp[0]}` : name;
                  return `<span class="src-link" title="Source file and SHA-256 recorded in
                    data/datasets/documents.json">${esc(label)}</span>`;
                })()}
              </span></li></ul>` : ''}
        </li>`;
      }).join('')}</ul>
      <p class="reassure"><span class="ic" aria-hidden="true">✓</span><span>
        ${verified ? (() => {
          /* "Add up ... checked automatically" was flatly false for the General
             Fund, whose accounts sum $10,000 below the published total in a
             disclosed, explained way. The exception renders WITH the claim,
             derived from the same validation rows that grant the green flag. */
          const kv = (_liv.checks || []).filter(c => c.fund === st.fund
            && c.fiscal_year === st.fy && c.basis === st.basis
            && c.status === 'known source variance' && c.difference);
          const base = `These figures add up to the town's own published total for
            FY${st.fy} ${esc(st.basis)} — checked automatically, not assumed`;
          if (!kv.length) return base + '. ';
          return base + `, with ${kv.length === 1 ? 'one disclosed exception' :
            kv.length + ' disclosed exceptions'}: the ${esc(kv.map(c => c.category)
              .join(' and '))} accounts sum ${kv.map(c =>
              `${usd(Math.abs(c.difference))} ${c.difference < 0 ? 'below' : 'above'}`).join(' and ')}
            the published figure — recorded in the validation data as a known source variance,
            with its reason, rather than as an unexplained one. `;
        })() : ''}
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
  _explorerRepaint = draw;
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
  /* "Coming years" must mean coming years: FY2026 ended a month ago and its figure
     is an estimate, not a plan, so it is excluded here rather than counted. */
  const headlineFy = (state.data.index || {}).headline_fiscal_year || 2027;
  const defs = latestByYear('general_fund_surplus_deficit')
    .filter(f => f.value < 0 && f.fiscal_year >= headlineFy);
  if (defs.length) {
    const worst = defs.reduce((a, b) => (b.value < a.value ? b : a));
    items.push(['watch', '~', `A planned shortfall in ${defs.length} of the coming years`,
      `The largest is <span class="fig">${usdSigned(worst.value)}</span> in FY${worst.fiscal_year}.
       Shortfalls are covered from savings, which is why the savings line matters.`]);
  }
  /* Measured against the prior year's published rate — never asserted. If the two
     years are not both in the data the item is withheld; if the rate moved, the
     item says so instead of celebrating. */
  const rate = one('property_tax_rate');
  const rcH = townRateChange();
  if (rate && rcH && rcH.delta === 0) {
    items.push(['ok', '✓', 'Your property tax rate is not going up this year',
      `It stays at <span class="fig">${cents(rate.value)} cents</span> per $100 of value in
       FY${rate.fiscal_year}, the same as FY${rcH.prev.fiscal_year}.`]);
  } else if (rate && rcH) {
    items.push([rcH.delta > 0 ? 'watch' : 'ok', rcH.delta > 0 ? '~' : '✓',
      `Your property tax rate ${rcH.delta > 0 ? 'rises' : 'falls'} this year`,
      `From <span class="fig">${cents(rcH.prev.value)}</span> to
       <span class="fig">${cents(rate.value)} cents</span> per $100 of value in
       FY${rate.fiscal_year}.`]);
  }
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
        <h3 class="block-title">
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
          not a plan.${aud.cross_document_check && aud.cross_document_check.agree
            /* The alignment sentence renders ONLY when the check passed — the old
               fallback still asserted "lines up to within a dollar" and merely
               appended a parenthetical when it did not. And the adjustment is
               stated, because a resident who opens the budget document sees
               $15.7M against this panel's $14.1M: the $1.58M the budget counts as
               transfers between town funds explains the whole gap. */
            ? ` It also lines up with the budget document's own figures for the same year to
               within a dollar, across two separate documents — once the
               ${compact(aud.cross_document_check.less_interfund_transfers || 0)} the budget
               document counts as transfers between town funds is set aside, as the audited
               statement classifies it.`
            : ''}
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
      /* A blank cell is a column that failed its own arithmetic check and was withheld.
         Counting them here rather than writing a number into the prose means the
         sentence cannot drift away from the table it sits above. */
      const blanks = yrs.reduce((n, y) =>
        n + (y.revenues == null ? 1 : 0) + (y.expenditures == null ? 1 : 0), 0);
      p3.innerHTML = `
        <h3 class="block-title">
          The audited record, year by year</h3>
        <p style="margin:0 0 var(--s4);font-size:var(--t-sm);color:var(--text-secondary)">
          What the town actually took in and actually spent, from its audited annual reports.
          ${nDigital} of these ${yrs.length} years came from a digital file;
          the rest were recovered from scanned pages by character recognition and then checked —
          each figure shown here is the total that its own page's individual lines add up to
          exactly.${blanks ? ` ${blanks === 1 ? 'One cell is' : blanks + ' cells are'} blank:
          ${blanks === 1 ? 'that column' : 'those columns'} did not add up when re-read, so the
          figure is withheld rather than guessed.` : ''}
        </p>
        <div class="tablewrap"><table>
          <caption>Audited General Fund actuals. "Read from" shows whether the figures came from a
            digital document or from a verified reading of a scan, and names the report.</caption>
          <thead><tr><th>Year</th><th class="num">Revenue (actual)</th>
            <th class="num">Spending (actual)</th><th>Read from</th></tr></thead>
          <tbody>${yrs.map(y => `<tr>
            <td>FY${y.fy}</td>
            <td class="num">${y.revenues != null ? usd(y.revenues) : '—'}</td>
            <td class="num">${y.expenditures != null ? usd(y.expenditures) : '—'}</td>
            <td>${y.how === 'digital'
              ? '<span class="badge ok">digital original</span>'
              : '<span class="badge">scan, arithmetic-verified</span>'}${y.doc
              ? `<span class="src-link" style="display:block">${
                  esc((docsById().get(y.doc) || {}).filename || y.doc)}${y.page
                  ? `, p.${esc(String(y.page))}` : ''}</span>` : ''}</td>
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
        let cellsChecked = 0, cellsUnchecked = 0;
        for (const r of wc.rows) {
          if (!String(r.table || '').startsWith('2.0')) continue;
          const cat = String(r.Category || '').toLowerCase();
          if (!r.Actual_Amount) continue;
          if (cat === 'total revenues' || cat === 'total expenditures') {
            if (r.verification === 'every figure found on the cited page') cellsChecked += 1;
            else cellsUnchecked += 1;
          }
          const e = byYear.get(r.Fiscal_Year_ID) || {};
          if (cat === 'total revenues') e.rev = r.Actual_Amount;
          if (cat === 'total expenditures') e.exp = r.Actual_Amount;
          byYear.set(r.Fiscal_Year_ID, e);
        }
        const cy = [...byYear.entries()].filter(([, v]) => v.rev || v.exp)
          .sort((a, b) => a[0].localeCompare(b[0]));
        if (cy.length >= 2) {
          const v = wc.verification || {};
          /* The per-value record s81 writes after reading all eight county ACFRs
             directly. The sentence below used to be driven by the OLDER page-citation
             check, which could only test rows whose workbook Source_ID resolved to a
             held file — so it reported 2 of 16 verified and blamed unresolvable
             citations, when 13 of the 16 are in fact printed in the audits we hold.
             Understating your own evidence is its own kind of inaccuracy. */
          const dr = v.direct_reader;
          const cw = document.createElement('div');
          cw.style.marginTop = 'var(--s6)';
          /* Counted from the rows this table actually renders, not asserted: the
             old sentence said "every row carries the county report and page ...
             and this build re-checks them", when most of these rows cite reports
             the workbook's own Source_Register does not resolve to a held file —
             so only some cells can be re-checked at all. Saying which is the
             difference between a verified figure and a trusted one. */
          cw.innerHTML = `
            <h4 style="margin:0 0 var(--s3);font-size:var(--t-sm);font-weight:640">
              Orange County, the same years</h4>
            <p style="margin:0 0 var(--s4);font-size:var(--t-sm);color:var(--text-secondary)">
              The county is a much larger government than the town, and this is its audited General
              Fund. These figures come from a curated research workbook rather than from this site's
              own extraction, and are published as the workbook's own.
              ${v.every_figure_found ? `Across the workbook, every row this build could match to a
              held county report checked out exactly (<strong>${v.every_figure_found} of
              ${v.rows_checked_against_source_pdf}</strong> checkable rows).` : ''}
              ${dr ? `Of the ${dr.values_checked} summary figures shown here,
              <strong>${dr.values_found}</strong> ${dr.values_found === 1 ? 'has' : 'have'} been
              found in the county's own annual report, read directly by this pipeline —
              ${dr.values_not_found === 0 ? 'all of them' :
                `the remaining ${dr.values_not_found} did not appear as a printed total for that
                 year and section, so ${dr.values_not_found === 1 ? 'it is' : 'they are'} shown
                 unconfirmed`}.
              <span style="opacity:.8">That check is value-level: it confirms the amount is
              printed in the audit, not that the workbook's label and attribution are
              right.</span>` : ''}
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
          // Document NAMES, not internal ids — residents saw "fy26-budget-message".
          src: rs.map(r => esc((docsById().get(r.source_doc) || {}).filename
            || r.source_doc)).join(' → ') };
      });
      const c2 = chartDumbbell(items2, 'What was projected vs what was later reported',
        'Each row is one year.', compact, ['Earlier document', 'Later document']);
      if (c2) inner.appendChild(c2);
    }
  }));

  host.appendChild(sec);
}

/* ==================== 04 — what's coming ==================== */
/**
 * The capital projects the town plans, one decision at a time.
 *
 * This is what Amy's Project dimension is for. A resident cannot see a decision by
 * reading a spending category — "Capital, $1.07M" says nothing about what was decided.
 * A project has a name, a reason, a cost across years, a way of being paid for, and
 * sometimes an ongoing cost it leaves behind. Each is shown with the page it came from.
 */
function projectsBlock(sec) {
  const d = state.data.projects;
  if (!d || !d.projects || !d.projects.length) return;
  const s = d.summary;

  /* This block used to open with the paragraph alone. Immediately above it sits the
     "A trade the town spelled out" card, so an unheaded paragraph about capital
     projects read as that card's continuation — 27 projects filed under someone
     else's heading. */
  const head = document.createElement('h3');
  head.className = 'sub-head';
  head.textContent = 'What the town plans to build';
  sec.appendChild(head);

  /* The tables' first column is the CURRENT project budget — money already
     appropriated — and the seven that follow are FY2027-FY2033. A fifth of the
     headline total sits in that first column, so "worth $72.59M across
     FY2027-FY2033" misattributed $14.5M of already-committed budget to the coming
     window. Split from the EXPENDITURE rows, the same basis as the headline
     total: the funding tables differ from it by $54,520 (the Dam Repairs
     question in the register), and a split whose parts do not sum to the total
     beside it would be this page's own small lie. */
  const already = d.projects.reduce((a, p) =>
    a + p.expenditures_by_account.reduce((x, r) => x + (r.amounts[0] || 0), 0), 0);
  const window7 = d.projects.reduce((a, p) =>
    a + p.expenditures_by_account.reduce((x, r) =>
      x + r.amounts.slice(1).reduce((y, v) => y + (v || 0), 0), 0), 0);
  const h = document.createElement('p');
  h.className = 'answer';
  h.innerHTML = `The town has <span class="fig">${d.projects.length}</span> capital projects
    planned, together worth <span class="fig">${compact(s.total_planned_cost)}</span> through
    FY2033 — <span class="fig">${compact(already)}</span> of that already in current project
    budgets, and <span class="fig">${compact(window7)}</span> planned across
    FY2027&ndash;FY2033. <span class="soft">Each one below is a decision, with what it costs, how
    it gets paid for, and the page it came from. Capital plans change; these are the town's
    current figures, not commitments.</span>`;
  sec.appendChild(h);

  const wrap = document.createElement('div');
  wrap.className = 'proj-list';
  const sorted = [...d.projects].sort((a, b) =>
    (b.total_planned_cost || 0) - (a.total_planned_cost || 0));

  for (const p of sorted) {
    const det = document.createElement('details');
    det.className = 'proj';
    const debt = p.funding_by_source.some(f => /DEBT/i.test(f.source));
    const unnamed = p.funding_by_source.some(f => f.unnamed_in_source);
    const q = p.operating_budget_impact_quantified;
    const tags = [];
    if (debt) tags.push('<span class="tag tag-debt">Borrowing</span>');
    if (p.creates_recurring_cost) tags.push('<span class="tag tag-ongoing">Ongoing cost</span>');
    // Worth a resident's attention: the town's document leaves this funding unlabelled.
    if (unnamed) tags.push('<span class="tag tag-gap">Funding not named</span>');

    det.innerHTML = `
      <summary>
        <span class="proj-main">
          <span class="proj-name">${esc(p.project_name)}</span>
          <span class="proj-meta">${esc(p.department || '')} &middot; ${esc(p.fund || '')}
            &middot; priority ${p.priority_rank ?? '—'}</span>
        </span>
        <span class="proj-right">
          <span class="proj-cost">${compact(p.total_planned_cost || 0)}</span>
          ${tags.join('')}
        </span>
      </summary>
      <div class="proj-body">
        ${p.description ? `<p>${esc(p.description)}</p>` : ''}
        ${p.justification ? `<p class="soft"><strong>Why:</strong> ${esc(p.justification)}</p>` : ''}
        <ul class="rows">
          ${p.funding_by_source.filter(f => f.amounts.some(v => v))
            .map(f => `<li><span class="k">${esc(f.source)}</span>
              <span class="v">${compact(f.amounts.reduce((a, b) => a + b, 0))}</span></li>`).join('')}
        </ul>
        ${q ? `<p class="soft">The town states a FY2027&ndash;29 budget impact of
            <strong>${compact(q.total)}</strong>${q.recurring_portion
              ? `, of which <strong>${compact(q.recurring_portion)}</strong> keeps recurring
                 afterwards — ${esc(Object.keys(q.by_kind)
                   .filter(k => /debt|maintenance/.test(k)).join(' and '))}`
              : ', all of it further one-time spending rather than an ongoing obligation'}.</p>`
          : p.operating_budget_impact
            ? `<p class="soft">${esc(p.operating_budget_impact)}</p>` : ''}
        <p class="src">Source: ${cite({ source_doc: p.source_doc,
                                        source_page: p.source_pages[0] })}
          ${flagButton(`Capital project: ${p.project_name}`,
                       `${p.source_doc} p.${p.source_pages[0]}`).outerHTML}</p>
      </div>`;
    wrap.appendChild(det);
  }
  sec.appendChild(wrap);
}

function renderComing(host) {
  const sec = section('coming', '04', 'What’s coming for you', '');
  const need = one('tax_rate_increase_needed_cents');
  const scenario = one('fy29_scenario_increase_on_400k_home');
  const capCents = one('capital_projects_tax_rate_equivalent_cents');
  const houseCents = one('affordable_housing_tax_rate_equivalent_cents');
  const oneCent = MFAS.oneCentOnValue(state.homeValue);

  const ans = document.createElement('p');
  ans.className = 'answer';
  /* The year's own figure, fetched BY year. val()/one() pick one row per metric by
     document recency and returned FY2026's estimate (−$748,667) here, which the
     sentence then attributed to FY2029 — understating the town's own projected
     FY2029 shortfall (−$2,534,674) 3.4x, two paragraphs above a timeline stating
     the right number. "At least", because the town states "over N cents". */
  const needYearDef = need ? forYear('general_fund_surplus_deficit', need.fiscal_year) : null;
  const rcC = townRateChange();
  ans.innerHTML = need && needYearDef
    ? `${rcC && rcC.delta === 0
        ? 'The town does not propose a tax increase this year, but it'
        : 'The town'} projects a shortfall of
       <span class="fig">${usd(Math.abs(needYearDef.value))}</span> by
       FY${need.fiscal_year} that would need a rise of over
       <span class="fig">${cents(need.value)} cents</span> to close —
       at least <span class="fig">${usd(oneCent * need.value)} a year</span> for a home like
       yours. <span class="soft">These are projections and will change.</span>`
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
        on a $400,000 home, and at least <span class="fig">${usd(oneCent * need.value)}</span>
        on yours.`;
    }
    /* "Already adopted" was false — no adopted FY2027 budget exists in the archive;
       the rate facts carry basis "recommended" and the tradeoffs caveat two cards
       down says these are the manager's recommendations, not final. */
    const hFy = (state.data.index || {}).headline_fiscal_year || 2027;
    // h3, not h4: these sit directly under the section h2, and the jump from
    // h2 to h4 was the page's one heading-level skip.
    return `<li class="${bad ? 'bad' : ''}"><span class="node" aria-hidden="true"></span>
      <span class="yr">FY${f.fiscal_year} · ${esc(f.basis)}</span>
      <h3>${f.fiscal_year === hFy ? 'This year’s plan' : 'Projected'}</h3>
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
      <span class="yr">Already promised</span><h3>Commitments on top of the above</h3>
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
  driversBlock(sec);
  tradeoffBlock(sec);
  projectsBlock(sec);
  host.appendChild(sec);
}

/**
 * What was asked for, what was funded, and what was not.
 *
 * Amy's point, and it is the right one: a budget document answers "what did we fund?"
 * and a site that only totals approved spending adopts that framing without noticing.
 * The question a resident actually has is what the choice cost — what was given up.
 *
 * Hillsborough publishes both sides, so nothing here is inferred: the town's own
 * Funded and Unfunded lists, and its own stated consequence of declining each request.
 */
/**
 * What is driving the increase, in one comparable unit.
 *
 * This is the other half of the tradeoff question: not just what was declined, but what
 * the new commitments cost. Every driver is shown in dollars AND in cents on the tax
 * rate, because that is the only unit in which a pay rise, a housing commitment and a
 * debt payment can be compared to each other — and to what a resident pays.
 *
 * The rows come from the initiative's own analysis workbook, not from this pipeline, and
 * the page says so. Each carries the source the analyst cited and their own confidence
 * rating, and where a figure could be checked against this pipeline's independent
 * reading of the same documents, it was.
 */
function driversBlock(sec) {
  const d = state.data.workbook_b;
  if (!d || !d.material_change_drivers || !d.material_change_drivers.length) return;
  // Negative rows are the resulting budget GAP, not a driver of it, and rendering one
  // here printed "−$2.53M … $-422/yr on your home" — which reads as money coming back to
  // the reader when closing that gap would in fact cost them. The gap has its own card.
  const rows = d.material_change_drivers
    .filter(r => r.amount > 0 && r.driver)
    .sort((a, b) => b.amount - a.amount);
  const gaps = d.material_change_drivers.filter(r => r.amount < 0 && r.driver);
  if (!rows.length) return;
  const v = d.verification || {};
  const agreed = (v.cross_checks_against_this_pipeline || []).filter(c => c.agrees).length;
  const checks = (v.cross_checks_against_this_pipeline || []).length;
  const oneCent = MFAS.oneCentOnValue(state.homeValue);

  const card = document.createElement('div');
  card.className = 'card drivers';
  card.innerHTML = `
    <h3>What is driving the increase</h3>
    <p>Each commitment below is shown twice: in dollars, and in <strong>cents on the tax
      rate</strong>. The second is the only unit in which a pay rise, a housing commitment and
      a debt payment can be compared &mdash; and it converts straight into what you pay.</p>
    <ul class="rows" id="driverRows"></ul>
    <p class="note"><span class="ic" aria-hidden="true">✓</span>
      <span>These rows come from the initiative's own analysis workbook rather than from this
      page's own reading of the documents, and each carries the source and confidence its
      author recorded.${checks ? ` Where the two could be compared, ${agreed} of ${checks}
      figures matched this page's independent reading of the same documents exactly.` : ''}
      The conversion uses the town's own published figure of
      ${v.her_penny_assumption ? usd(v.her_penny_assumption) : 'n/a'} raised by one cent.
      ${gaps.length ? `The projected budget gap these commitments contribute to is shown
      separately below, since it is the result rather than a cause.` : ''}</span></p>`;
  const ul = card.querySelector('#driverRows');
  for (const r of rows) {
    const li = document.createElement('li');
    const onYours = r.cents_equivalent ? oneCent * r.cents_equivalent : null;
    li.innerHTML = `<span class="k">${esc(r.driver)}
        <small>${esc(r.period || '')}${r.budget_category ? ' · ' + esc(r.budget_category) : ''}
          ${r.confidence ? `· confidence: ${esc(String(r.confidence).toLowerCase())}` : ''}</small>
        ${r.commentary ? `<small class="why">${esc(clip(r.commentary, 200))}</small>` : ''}</span>
      <span class="v">${compact(r.amount)}<small>${r.cents_equivalent
        ? `${cents(r.cents_equivalent)} cents${onYours ? ` · ${usd(onYours)}/yr on your home` : ''}`
        : ''}</small></span>`;
    ul.appendChild(li);
  }
  sec.appendChild(card);

  // The cliff is the point of the exercise: the commitments land in one year.
  if (d.fy29_fiscal_cliff && d.fy29_fiscal_cliff.length && v.fy29_cliff_total_reconciles) {
    const q = d.fy29_fiscal_cliff.filter(c => c.annual_amount);
    const box = document.createElement('div');
    box.className = 'card tradeoff-named';
    box.innerHTML = `
      <h3>Why FY2029 is the year to watch</h3>
      <p>Several of those commitments start paying out at once. The initiative's workbook adds
        the quantifiable ones to <strong>${usd(v.fy29_cliff_parts_sum)}</strong> in that single
        year &mdash; about <strong>${cents(v.fy29_cliff_parts_sum
          / (v.her_penny_assumption || 240000))} cents</strong> on the tax rate, or roughly
        <strong>${usd(oneCent * v.fy29_cliff_parts_sum / (v.her_penny_assumption || 240000))}
        a year</strong> on a home like yours.</p>
      <ul class="rows">${q.map(c => `<li><span class="k">${esc(c.component)}
        <small>${esc(String(c.status || '').toLowerCase())}</small></span>
        <span class="v">${compact(c.annual_amount)}</span></li>`).join('')}</ul>
      <p class="note"><span class="ic" aria-hidden="true">✓</span>
        <span>The workbook deliberately leaves out exposures it cannot yet quantify, so this is
        a floor rather than a forecast. Its parts were checked against its own stated total.</span></p>`;
    sec.appendChild(box);
  }
}

/** Trim to the last sentence that fits, so an excerpt never ends mid-word. */
function clip(s, n) {
  if (!s || s.length <= n) return s || '';
  const cut = s.slice(0, n);
  const stop = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('? '), cut.lastIndexOf('! '));
  return stop > n * 0.5 ? cut.slice(0, stop + 1) : cut.slice(0, cut.lastIndexOf(' ')) + '…';
}

function tradeoffBlock(sec) {
  const d = state.data.tradeoffs;
  if (!d || !d.declined) return;
  const s = d.summary;
  const rt = s.declined_in_resident_terms || {};
  const oneCent = MFAS.oneCentOnValue(state.homeValue);
  // The town's published figure is for a $400,000 home; scale it to the reader's.
  const onYours = rt.cents_on_the_tax_rate ? oneCent * rt.cents_on_the_tax_rate : null;

  const h = document.createElement('div');
  h.className = 'card tradeoff';
  h.innerHTML = `
    <h3>What didn’t get funded</h3>
    <p>Departments asked for <span class="fig">${usd(s.fy2027_total_asked)}</span> of new
      spending next year. The town funded <span class="fig">${usd(s.fy2027_funded)}</span> of it
      and <strong>declined ${usd(s.fy2027_declined)}</strong> &mdash;
      <span class="fig">${s.requests_declined}</span> requests.</p>
    ${rt.cents_on_the_tax_rate ? `<p class="soft">Funding all of it would have taken about
      <strong>${cents(rt.cents_on_the_tax_rate)} cents</strong> on the tax rate${onYours
        ? `, or about <strong>${usd(onYours)} a year</strong> on a home like yours` : ''}.
      ${esc(rt.basis || '')}</p>` : ''}
    <ul class="rows" id="declinedRows"></ul>
    <p class="note"><span class="ic" aria-hidden="true">✓</span>
      <span>These are the town's own Funded and Unfunded lists, and its own words on what
      declining each request would mean. This page does not judge the decisions.
      ${esc(d.caveats[0])}</span></p>`;
  const ul = h.querySelector('#declinedRows');
  for (const r of d.declined) {
    const li = document.createElement('li');
    // Three distinct cases, and conflating them would put a false claim on the page:
    // the town stated a consequence; the town's form states none; or no form was found.
    // Only the middle one is a statement about the town.
    const consequence = r.impact_if_not_funded
      // The match basis stays in the dataset for auditing, NOT on screen. Printing it
      // put "(name variant (100% of words shared))" under a declined request, which reads
      // as debug output leaking into resident-facing copy — caught while filming the site.
      ? esc(clip(r.impact_if_not_funded, 210))
      : r.justification_matched
        ? 'The town’s form for this request states no consequence.'
        : 'No justification form was found for this request, so the town may have stated '
          + 'a consequence this page has not located.';
    li.innerHTML = `<span class="k">${esc(r.request)}<small>${consequence}</small></span>
      <span class="v">${usd(r.fy2027 || 0)}<small>${r.total_three_year !== r.fy2027
        ? usd(r.total_three_year) + ' over three years' : 'one year only'}</small></span>`;
    ul.appendChild(li);
  }
  sec.appendChild(h);

  // The clearest tradeoff in the document: one request the town says could be funded
  // only by cutting another. Worth surfacing on its own — it is the concept made real.
  const named = d.justification_forms.filter(f => f.states_a_fundable_alternative);
  if (named.length) {
    const box = document.createElement('div');
    box.className = 'card tradeoff-named';
    box.innerHTML = `
      <h3>A trade the town spelled out</h3>
      ${named.map(f => `<p>On <strong>${esc(f.request)}</strong>, the town writes that the
        request <em>&ldquo;could be funded by reducing the allocation&rdquo;</em> to the very
        programme it sits inside. ${f.description
          ? `<span class="soft">${esc(clip(f.description, 340))}</span>` : ''}</p>
        <p class="src">Source: ${cite({ source_doc: f.source_doc,
                                        source_page: f.source_page })}</p>`).join('')}`;
    sec.appendChild(box);
  }
}

/* ==================== 05 — speak up ==================== */
function renderVoice(host) {
  const sec = section('voice', '05', 'How to be heard', '');
  const part = (state.data.household && state.data.household.civic_participation) || [];
  const r = state.data.requests, s = r.summary;

  const ans = document.createElement('p');
  ans.className = 'answer';
  /* Settled by Amy's research (register Q044, 2026-07-29): Hillsborough's Board of
     Commissioners is officially the mayor plus five commissioners, with the mayor
     voting only to break a tie on adoption — so naming the Board is precise and
     includes the mayor by definition. */
  ans.innerHTML = `The budget is adopted by the town's Board of Commissioners, and the process
    includes public hearings you can attend. <span class="soft">Below are the dates the FY2027
    budget message names, and the questions residents have already put to the town.</span>`;
  sec.appendChild(ans);

  if (part.length) {
    const p = document.createElement('div');
    p.className = 'panel panel-pad';
    p.innerHTML = `<h3 class="block-title" style="margin-bottom:var(--s4)">
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
  q.innerHTML = `<h3 class="block-title">
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
  ['Audited', 'Checked by an outside accountant after the year ends, which makes audited figures the most reliable kind. The audited record on this page runs from FY2018 to FY2025, and each year says whether it was read from a digital file or recovered from a scanned page and checked.'],
];

function renderReceipts(host) {
  const docs = state.data.documents.documents, sum = state.data.documents.summary;
  const sec = section('receipts', '06', 'Where every number came from', '');
  const ans = document.createElement('p');
  ans.className = 'answer';
  /* Two numbers, two jobs. This sentence used to say every figure "traces to one
     of 84 documents in the archive" — defensible as worded, and still misleading:
     84 is the size of the archive, and 65 of those documents are cited by nothing
     the site publishes. A resident read 84 as the depth of the evidence base. The
     evidence base and the archive are different numbers, both computed at build
     time (data/index.json) and pinned by tests, so neither can drift.
     This paragraph also once said the scanned reports contributed nothing — false
     since the audited record was recovered from them — so the scan clause names
     exactly which cited documents are scans rather than sweeping. */
  const idx = state.data.index || {};
  const citedIds = new Set(idx.cited_documents || []);
  const nCited = idx.counts && idx.counts.documents_cited || citedIds.size;
  const scansCited = docs.filter(d => d.text_layer === 'scan' && citedIds.has(d.id)).length;
  ans.innerHTML = `Every figure on this page traces to a document named where the figure
    appears. All of the published figures come from
    <span class="fig">${nCited}</span> source documents — the two governments' budgets and
    financial reports, and the initiative's own workbooks, each labelled as such where it is
    used. They are held in an archive of <span class="fig">${sum.unique_documents}</span>
    catalogued files, listed below; the rest of the archive is context — earlier years'
    editions, working papers and correspondence that no published figure is taken from.
    <span class="soft">${sum.pdf_scanned_ocr} of the archive's documents are scanned images
    (${scansCited} of them among the cited sources). The text hidden inside a scan scrambles
    digits — a page that plainly reads
    <span class="mono">4,610,003</span> comes back as <span class="mono">460,100,3</span> — so
    <strong>nothing here is ever read from it</strong>. Where a scanned page is used at all it is
    re-read from the image, and published only if that page's own column still adds up to the
    total printed beside it.</span>`;
  sec.appendChild(ans);

  // ---- best effort, and how to tell us we got it wrong -----------------------
  const effort = document.createElement('div');
  effort.className = 'panel panel-pad';
  effort.style.marginBottom = 'var(--s5)';
  effort.innerHTML = `
    <h3 class="block-title">
      This is a best-effort project — please tell us if something looks wrong</h3>
    <p style="margin:0 0 var(--s4);font-size:var(--t-sm);color:var(--text-secondary)">
      This site is built and maintained by residents, not by the town. Every figure is traced to a
      document and a page, and checked by machine wherever the document makes that possible, but
      the source material runs to thousands of pages and <strong>we do not claim it is
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
    <h3 class="block-title">
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
    /* Cited sources sort first and are marked, so the archive list itself shows
       which files carry the site's figures and which are context. */
    const rows = docs.slice().sort((a, b) =>
      (citedIds.has(b.id) - citedIds.has(a.id))
      || (a.category || '').localeCompare(b.category) || a.filename.localeCompare(b.filename))
      .map(d => {
        const badge = d.format !== 'pdf' ? `<span class="badge">${esc(d.format)}</span>`
          : d.values_extractable ? `<span class="badge ok">readable</span>`
            : `<span class="badge warn">scanned — text layer never used</span>`;
        const used = citedIds.has(d.id)
          ? `<span class="badge ok">cited</span>` : `<span class="badge">context</span>`;
        return `<tr><td>${esc(d.filename)}</td><td class="num">${d.fiscal_year || '—'}</td>
          <td class="num">${d.pages || '—'}</td>
          <td class="num">${(d.bytes / 1048576).toFixed(1)} MB</td><td>${used}</td><td>${badge}</td>
          <td class="mono" title="${esc(d.sha256 || '')}">${esc((d.sha256 || '').slice(0, 10))}</td></tr>`;
      }).join('');
    inner.innerHTML = `<div class="tablewrap"><table>
      <caption>The ${sum.unique_documents} files catalogued behind this project —
        ${nCited} cited by the published figures, the rest context. The code after each is the
        first part of its SHA-256 fingerprint, so you can prove your copy is the same file.</caption>
      <thead><tr><th>Document</th><th class="num">Year</th><th class="num">Pages</th>
        <th class="num">Size</th><th>Used for figures?</th><th>Can we read it?</th>
        <th>Fingerprint</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  }));

  const g = document.createElement('div');
  g.className = 'panel panel-pad';
  g.style.marginTop = 'var(--s5)';
  g.innerHTML = `<h3 class="block-title" style="margin-bottom:var(--s5)">
      Budget words, in plain English</h3>
    <dl class="gloss">${GLOSSARY.map(([t, d]) =>
      `<div><dt>${esc(t)}</dt><dd>${esc(d)}</dd></div>`).join('')}</dl>`;
  sec.appendChild(g);
  host.appendChild(sec);
}

/* ==================== the masthead's right column ==================== */
/**
 * The film, swapped in only when asked.
 *
 * The card is a still image; pressing it builds the real <video> and plays it.
 * Autoplay is legitimate here precisely because it follows a press — the reader
 * asked for it — and it is the only way the film ever starts. Captions are on by
 * default: the narration is the whole content, and plenty of people watch a page
 * like this muted or cannot hear it at all.
 */
function setupFilm() {
  const wrap = $('#film'), btn = $('#filmPlay');
  if (!wrap || !btn) return;
  btn.addEventListener('click', () => {
    const v = document.createElement('video');
    v.controls = true;
    v.autoplay = true;
    v.playsInline = true;
    v.preload = 'metadata';
    v.setAttribute('poster', 'docs/media/mfas-commercial-card.jpg');
    v.innerHTML = `
      <source src="docs/media/mfas-commercial.mp4" type="video/mp4">
      <track kind="captions" src="docs/media/mfas-commercial.vtt" srclang="en"
             label="English" default>`;
    const alt = document.createElement('p');
    alt.className = 'film-alt';
    alt.innerHTML = `62 seconds · narration and captions ·
      <a href="docs/media/mfas-commercial.mp4">open the file directly</a> if it will not play.`;
    /* Failures must say so. A 404'd mp4 used to leave a live-looking dead player
       whose "open the file directly" rescue pointed at the same missing file; a
       404'd caption track played silently while the card still promised captions. */
    const srcEl = v.querySelector('source'), trkEl = v.querySelector('track');
    if (srcEl) srcEl.addEventListener('error', () => {
      alt.innerHTML = `The film could not be loaded — the video file did not arrive. This is
        usually temporary; reloading the page tries again.`;
    });
    if (trkEl) trkEl.addEventListener('error', () => {
      alt.innerHTML += ` <strong>Captions failed to load this time</strong> — the narration
        is still spoken.`;
    });
    btn.replaceWith(v);
    wrap.querySelector('.film-cap').replaceWith(alt);
    /* A blocked autoplay must not look like a broken player. */
    const p = v.play();
    if (p && p.catch) p.catch(() => { v.controls = true; });
    v.focus({ preventScroll: true });
  });
}

/**
 * How you can check this — the masthead's credibility column.
 *
 * Every row is measured rather than typed into the markup, including the zero.
 * The zero is the build's own count across EVERY published dataset — headline
 * facts, line items, the audited series, projects, tradeoffs, the imported
 * workbooks — not just the 83 core facts, which is what an earlier version
 * measured while claiming to cover the page. If a figure anywhere in the
 * published data were read from a scan's text layer, the build would count it
 * and this card would say so.
 */
function renderVerify() {
  const slot = $('#verifySlot');
  if (!slot) return;
  const idx = state.data.index || {};
  const c = idx.counts || {};
  const docs = docsById();
  const all = state.data.facts.facts;
  // Fallback for an index.json predating the page-wide count: facts-only scope.
  const factsFromScanText = all.filter(f => {
    const d = docs.get(f.source_doc);
    return d && d.values_extractable === false && f.extraction !== 'transcribed';
  }).length;
  const fromScanText = c.figures_read_from_scan_text != null
    ? c.figures_read_from_scan_text : factsFromScanText;
  const traced = all.filter(f => f.source_doc).length;
  // The audited-record cells two sections down that were recovered from scanned
  // pages and proven by their own arithmetic — counted the same way that table
  // builds itself, so the two cannot disagree.
  const recovered = ((state.data.ocr_statements || {}).published || [])
    .filter(p => p.column_role === 'actual' && p.fiscal_year && p.total != null).length;

  const rows = [
    ['Core figures, each traced to a document', `${traced} of ${all.length}`,
     traced < all.length],
    ['Account-level observations', (c.line_item_observations || 0).toLocaleString('en-US')],
    ['Read from a scan’s hidden text, anywhere', String(fromScanText), fromScanText > 0],
    ['Recovered from scans, arithmetic-proven', String(recovered)],
    ['Documents the published figures cite', String(c.documents_cited || '—')],
    ['In the archive, catalogued', (c.documents || 0).toLocaleString('en-US')],
  ];
  const el = document.createElement('div');
  el.className = 'verify';
  el.innerHTML = `<h2>How you can check this</h2>
    <dl>${rows.map(([k, v, warn]) => `<div class="vr"><dt>${esc(k)}</dt>
      <dd${warn ? ' class="warn"' : ''}>${esc(v)}</dd></div>`).join('')}</dl>
    <p class="foot-note">Every figure names its document, and its page wherever the document has
      pages — a spreadsheet cell does not. The whole dataset is rebuilt from those documents by an
      open pipeline, and rebuilding it reproduces this page.
      <a href="#receipts">See the documents</a>.</p>`;
  slot.replaceWith(el);
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
  if (firstPaint) {
    renderVerify(); setupScrollSpy();
    firstPaint = false;
  }
}

function setupScrollSpy() {
  const links = $$('#navLinks a');
  const byId = new Map(links.map(a => [a.getAttribute('href').slice(1), a]));
  const here = $('#navHere');
  const obs = new IntersectionObserver(entries => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      links.forEach(a => a.removeAttribute('aria-current'));
      const a = byId.get(e.target.id);
      if (a) {
        a.setAttribute('aria-current', 'true');
        // The phone button doubles as a "you are here" marker on a page this long.
        if (here) here.textContent = a.textContent;
      }
    }
  }, { rootMargin: '-45% 0px -50% 0px' });
  byId.forEach((_, id) => {
    const el = document.getElementById(id);
    if (el) obs.observe(el);
  });
}

/** The phone section menu.
 *
 * A plain button and a class, not <details>: browsers have moved the internals of
 * <details> around (the closed state is hidden by a UA rule that has changed shape
 * more than once), and this page has to keep working untouched for years.
 */
function setupNavMenu() {
  const btn = $('#navToggle'), list = $('#navLinks');
  if (!btn || !list) return;
  const close = () => { list.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); };
  btn.addEventListener('click', e => {
    e.stopPropagation();
    const open = list.classList.toggle('open');
    btn.setAttribute('aria-expanded', String(open));
  });
  list.addEventListener('click', e => { if (e.target.closest('a')) close(); });
  document.addEventListener('click', e => {
    if (list.classList.contains('open') && !list.contains(e.target)) close();
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && list.classList.contains('open')) { close(); btn.focus(); }
  });
}

/* ================================= boot ================================ */

/** fetch + JSON with the status actually checked, and a message that names the file.
 *
 *  `(await fetch(u)).json()` treats a 404 as success and then fails on the HTML error
 *  page with "Unexpected token <", which tells a maintainer nothing about WHICH of
 *  twenty datasets is missing. */
async function getJSON(url, name) {
  let res;
  try {
    res = await fetch(url);
  } catch (e) {
    throw new Error(`${name || url}: network error (${e.message})`);
  }
  if (!res.ok) throw new Error(`${name || url}: HTTP ${res.status} ${res.statusText} — ${url}`);
  try {
    return await res.json();
  } catch (e) {
    throw new Error(`${name || url}: served ${res.headers.get('content-type') || 'unknown type'}, not JSON`);
  }
}

async function boot() {
  try {
    loadHome();
    loadShared();   // an explicit link wins over a remembered setting
    const idx = await getJSON('data/index.json');
    const names = ['facts', 'metrics', 'documents', 'projections', 'requests', 'issues',
                   'household', 'audited', 'ocr_statements', 'warehouse_county', 'mfas',
                   'transfers', 'utility', 'cost_of_ownership', 'projects', 'tradeoffs', 'workbook_b', 'context', 'revenue', 'structure'];
    // CORE must load or the page is meaningless; everything else may fail on its own
    // without taking the calculator down with it. Previously one missing or non-JSON
    // dataset rejected the whole Promise.all and produced a generic "could not load"
    // for the entire site, with no indication of which file or what status.
    const CORE = new Set(['facts', 'metrics', 'documents']);
    const loaded = await Promise.all(names.map(n => {
      if (!idx.datasets[n]) return Promise.resolve(null);
      return getJSON('data/' + idx.datasets[n], n).catch(err => {
        if (CORE.has(n)) throw err;
        console.error('[MFAS] optional dataset failed:', n, err.message);
        return null;
      });
    }));
    state.data = Object.fromEntries(names.map((n, i) => [n, loaded[i]]));
    state.data.index = idx;

    const ys = state.data.facts.facts.map(f => f.fiscal_year).filter(v => v != null);
    state.yearMin = Math.min(...ys);
    state.yearMax = Math.max(...ys);

    $('#loading').remove();
    render();

    /* The browser's own fragment jump fires before these sections exist — every
       deep link (including the share feature's own #you) landed at the top of a
       19,000px page. Re-apply it once the target is real. Instant, because this
       replaces the navigation jump, not a smooth in-page scroll. */
    if (location.hash.length > 1) {
      const target = document.getElementById(location.hash.slice(1));
      if (target) target.scrollIntoView({ behavior: 'auto', block: 'start' });
    }

    /* The chip's count must say what it counts: "83 figures" was facts.json's row
       count on a page rendering thousands of sourced values. And the old footer
       line ("84 source documents · 46 readable · 10 scanned and excluded") could
       not be reconciled on screen — 46+10 is the PDFs only, 28 other files sat in
       neither bucket, 65 of the 84 are sources of nothing, and "excluded" repeated
       the exact sweeping claim the receipts section already had to walk back. */
    $('#chipCount').textContent =
      `${idx.counts.facts} core figures · every figure sourced`;
    const nOther = idx.counts.documents
      - idx.counts.documents_with_trustworthy_text
      - idx.counts.documents_scanned_needing_transcription;
    $('#footMeta').textContent =
      `${idx.counts.facts} core figures · ${idx.counts.line_item_observations
        ? idx.counts.line_item_observations.toLocaleString('en-US') + ' line items · ' : ''}` +
      `${idx.counts.documents_cited || '—'} documents cited, from an archive of ` +
      `${idx.counts.documents} (${idx.counts.documents_with_trustworthy_text} digital PDFs, ` +
      `${idx.counts.documents_scanned_needing_transcription} scans whose hidden text is never ` +
      `used, ${nOther} spreadsheets and other files).`;
    scheduleScrollableScan();
  } catch (err) {
    /* The old text asserted the cause — "you probably opened the file directly" —
       which is wrong for a deployment or a partial release, and sends the reader
       to fix something that is not broken. Describe the symptom, give both real
       causes, and say what to do. */
    $('#loading').innerHTML =
      'Could not load the town’s figures. Either the data files did not load from the ' +
      'server, or this page was opened straight from a folder rather than a web address ' +
      '— browsers block the data load in that case. ' +
      '<a href="https://oc-accountability.github.io/MFAS/">Open the published site</a>, ' +
      'and if it still fails there, that is a fault worth reporting.';
    console.error(err);
  }
}


/* ---------------------------------------------------------------------------
 * Keyboard access to the horizontally scrolling regions.
 *
 * Six table wrappers and the chart strip can overflow sideways on a phone. A
 * region a mouse can scroll but a keyboard cannot reach is a WCAG failure
 * (`scrollable-region-focusable`), and an audit found two SERIOUS instances at
 * 390px and 320px. It is easy to miss because the DOCUMENT does not overflow —
 * only these inner boxes do — so a page-width test says everything is fine.
 *
 * The tab stop is added ONLY where the content actually overflows. Marking every
 * wrapper focusable would sprinkle dead tab stops through the page for keyboard
 * users on a wide screen, which trades one accessibility problem for another, so
 * this re-measures on resize.
 *
 * The name comes from the region's own caption or nearest heading. A focusable
 * region with no accessible name is only half a fix — a screen-reader user is
 * told "scrollable region" with no idea which one.
 * ------------------------------------------------------------------------- */
function markScrollableRegions() {
  $$('.tablewrap, .chart-scroll').forEach(el => {
    const overflows = el.scrollWidth > el.clientWidth + 1;
    if (!overflows) {
      el.removeAttribute('tabindex');
      el.removeAttribute('role');
      el.removeAttribute('aria-label');
      return;
    }
    el.setAttribute('tabindex', '0');
    el.setAttribute('role', 'region');
    if (!el.getAttribute('aria-label')) {
      const cap = el.querySelector('caption, th[scope="col"]');
      let name = cap ? cap.textContent.trim() : '';
      if (!name) {
        const h = el.closest('section')?.querySelector('h2, h3');
        name = h ? h.textContent.trim() : '';
      }
      el.setAttribute('aria-label',
        (name ? name.replace(/\s+/g, ' ').slice(0, 80) + ' — ' : '') + 'scrollable table');
    }
  });
}

let _scrollScanTimer = null;
function scheduleScrollableScan() {
  clearTimeout(_scrollScanTimer);
  _scrollScanTimer = setTimeout(markScrollableRegions, 150);
}
window.addEventListener('resize', scheduleScrollableScan);

$('#themeToggle').addEventListener('click', () => {
  const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('hoa-theme', next); } catch (e) {}
});

/* Wired here, not inside render(): these are static-HTML affordances. When the
   data fetch failed they used to be visible but dead — a play button that did
   nothing, a phone menu that would not open. */
setupFilm();
setupNavMenu();

boot();
