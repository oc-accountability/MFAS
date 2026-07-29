#!/usr/bin/env node
/* Contrast check for the site's chart and status colours — no dependencies.
 *
 * Why this exists: the stylesheet used to CLAIM its palette was validated while
 * one chart colour (--step-early, 2.06:1) and all four light-theme status
 * colours (down to 1.79:1) had never been measured. A claim of validation that
 * cannot be re-run is not one. This script reads assets/style.css itself, so it
 * checks the colours that actually ship, not a list pasted into a comment.
 *
 * Usage:  node scripts/validate_palette.js            # both themes
 *         node scripts/validate_palette.js --mode light
 * Exit 1 if any check fails.
 *
 * Floors (WCAG 2.x): 3:1 for graphical marks (chart series, dumbbell steps),
 * 4.5:1 for colours that ever carry text or a glyph (the status set, accent-text).
 */
'use strict';
const fs = require('fs');
const path = require('path');

const css = fs.readFileSync(path.join(__dirname, '..', 'assets', 'style.css'), 'utf8');

function block(startMarker) {
  const i = css.indexOf(startMarker);
  if (i < 0) throw new Error('cannot find ' + startMarker);
  return css.slice(i, css.indexOf('}', i));
}
function vars(blockText) {
  const out = {};
  for (const m of blockText.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)) out[m[1]] = m[2];
  return out;
}
function lum(hex) {
  const c = hex.replace('#', '');
  const f = v => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(parseInt(c.slice(0, 2), 16))
       + 0.7152 * f(parseInt(c.slice(2, 4), 16))
       + 0.0722 * f(parseInt(c.slice(4, 6), 16));
}
function ratio(a, b) {
  const la = lum(a), lb = lum(b), hi = Math.max(la, lb), lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

const MARKS = ['series-1', 'series-2', 'series-3', 'pos', 'neg', 'step-early', 'step-late'];
const TEXTY = ['good', 'warning', 'serious', 'critical', 'accent-text', 'success-text'];

const themes = {
  dark: vars(block(':root {')),
  light: vars(block(':root[data-theme="light"]')),
};
// The light block only carries overrides; anything absent inherits the dark value.
themes.light = { ...themes.dark, ...themes.light };

const modeArg = process.argv.includes('--mode')
  ? process.argv[process.argv.indexOf('--mode') + 1] : null;

let failed = 0;
for (const [mode, t] of Object.entries(themes)) {
  if (modeArg && mode !== modeArg) continue;
  const surfaces = { card: t['surface-1'], page: t.page };
  console.log(`\n${mode.toUpperCase()}  (card ${surfaces.card}, page ${surfaces.page})`);
  for (const [kind, names, floor] of [['mark', MARKS, 3], ['text', TEXTY, 4.5]]) {
    for (const name of names) {
      if (!t[name]) continue;
      for (const [sname, s] of Object.entries(surfaces)) {
        const r = ratio(t[name], s);
        const ok = r >= floor;
        if (!ok) failed += 1;
        console.log(`  ${ok ? 'ok  ' : 'FAIL'} --${name} ${t[name]} vs ${sname}: `
          + `${r.toFixed(2)}:1 (needs ${floor}:1 as ${kind})`);
      }
    }
  }
}
if (failed) { console.error(`\n${failed} check(s) FAILED`); process.exit(1); }
console.log('\nall checks pass');
