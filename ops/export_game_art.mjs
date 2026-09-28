#!/usr/bin/env node
// Export each title's GameArt scene (web/gameart.js) as a static, square, self-contained SVG for
// Avrana Party's game library, beside the metadata exporter (ops/export_avrana_catalog.py).
//
//   node ops/export_game_art.mjs DIR            write DIR/<slug>.svg for every exported title
//   node ops/export_game_art.mjs --check DIR    exit 1 if DIR differs (Avrana vendors a copy)
//
// Deterministic and dependency-free. The scene is the same drawing the hub and join screens use,
// frozen (no animation) and cropped to a square; every CSS class becomes a plain presentation
// attribute, so the file needs no <style>, CSS variables, fonts or network, and works as an <img>
// under a strict CSP. Titles come from provider/catalog.json (the registry export).
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const sandbox = { window: {} };
vm.runInNewContext(readFileSync(path.join(root, 'web', 'gameart.js'), 'utf8'), sandbox);
const GameArt = sandbox.window.GameArt;

const hex = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
const toHex = (rgb) => '#' + rgb.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
// CSS color-mix(in srgb, a p%, b): per-channel interpolation of the encoded values.
const mix = (a, p, b) => toHex(hex(a).map((v, i) => v * p + hex(b)[i] * (1 - p)));

// gameart.css, in source order (later rules win, exactly as in the stylesheet).
function rules(ga, ga2) {
  const stroke = { fill: 'none', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' };
  const text = { 'font-family': 'system-ui, sans-serif', 'font-weight': '800', fill: '#07101d' };
  return [
    ['ga-beam', { fill: ga, 'fill-opacity': '.08' }],
    ['ga-grid', { fill: 'none', stroke: '#e2e8ff', 'stroke-opacity': '.08', 'stroke-width': '1' }],
    ['ga-a', { fill: ga }], ['ga-core', { fill: ga }],
    ['ga-b', { fill: ga2 }],
    ['ga-panel', { fill: mix(ga, 0.25, '#11182a'), stroke: ga, 'stroke-opacity': '.46', 'stroke-width': '2' }],
    ['ga-card', { fill: '#eef3ff', stroke: '#ffffff', 'stroke-opacity': '.55', 'stroke-width': '2' }],
    ['ga-card-b', { fill: mix(ga2, 0.17, '#eef3ff') }],
    ['ga-hole', { fill: '#060914' }], ['ga-night', { fill: '#060914' }],
    ['ga-solid', { stroke: 'none' }],
    ['ga-ring', { ...stroke, stroke: ga, 'stroke-width': '12' }],
    ['ga-line', { ...stroke, stroke: '#e2e8ff', 'stroke-opacity': '.17', 'stroke-width': '2' }],
    ['ga-a-stroke', { ...stroke, stroke: ga, 'stroke-width': '25' }],
    ['ga-b-stroke', { ...stroke, stroke: ga2, 'stroke-width': '8' }],
    ['ga-cut-stroke', { ...stroke, stroke: '#07101d', 'stroke-width': '6' }],
    ['ga-cut', { fill: '#07101d' }],
    ['ga-streak', { fill: 'none', stroke: ga2, 'stroke-width': '8', 'stroke-linecap': 'round' }],
    ['ga-label', { ...text, 'font-size': '24' }],
    ['ga-ball-label', { ...text, 'font-size': '38', 'text-anchor': 'middle', 'font-style': 'italic' }],
    ['ga-score', { ...text, 'font-size': '21', fill: '#f5f8ff', 'text-anchor': 'middle' }],
    ['ga-price', { ...text, 'font-size': '62', 'font-style': 'italic', fill: ga, 'text-anchor': 'middle' }],
    ['ga-fallback', { ...text, 'font-size': '72', fill: ga }],
    ['ga-dark', { fill: '#07101d' }],
    ['ga-x', { fill: 'none', stroke: ga2, 'stroke-width': '9', 'stroke-linecap': 'round' }],
  ];
}
// Motion and glow only; a library tile is a still.
const IGNORED = new Set(['ga-float', 'ga-drift', 'ga-spin', 'ga-pulse', 'ga-snake']);

export function exportArt(game) {
  const card = GameArt.html(game);
  const ga = /--ga:(#[0-9a-f]{6})/i.exec(card)[1];
  const ga2 = /--ga2:(#[0-9a-f]{6})/i.exec(card)[1];
  const table = rules(ga, ga2);
  const known = new Set(table.map(([c]) => c));
  const inner = /<svg[^>]*>([\s\S]*)<\/svg>/.exec(card)[1];
  const body = inner.replace(/\sclass="([^"]*)"/g, (_, list) => {
    const classes = list.split(/\s+/).filter(Boolean);
    const unknown = classes.filter((c) => !known.has(c) && !IGNORED.has(c));
    if (unknown.length) throw new Error(`${game.slug}: no export rule for ${unknown.join(', ')}`);
    const attrs = {};
    for (const [cls, props] of table) if (classes.includes(cls)) Object.assign(attrs, props);
    return Object.entries(attrs).map(([k, v]) => ` ${k}="${v}"`).join('');
  }).replace(/\s*\n\s*/g, ' ').replace(/>\s+</g, '><').trim();
  const bg = mix(ga, 0.2, '#060914');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 50 300 300">`
    + `<defs><linearGradient id="b" x1="0" y1="0" x2=".42" y2="1"><stop offset="0" stop-color="${bg}"/>`
    + `<stop offset=".68" stop-color="#080c18"/><stop offset="1" stop-color="#04060c"/></linearGradient>`
    + `<radialGradient id="g1" cx="225" cy="64" r="200" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="${ga}" stop-opacity=".38"/><stop offset=".62" stop-color="${ga}" stop-opacity="0"/></radialGradient>`
    + `<radialGradient id="g2" cx="24" cy="336" r="220" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="${ga2}" stop-opacity=".32"/><stop offset=".65" stop-color="${ga2}" stop-opacity="0"/></radialGradient>`
    + `<linearGradient id="v" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#04060c" stop-opacity=".08"/>`
    + `<stop offset=".35" stop-color="#04060c" stop-opacity=".04"/><stop offset="1" stop-color="#04060c" stop-opacity=".78"/></linearGradient></defs>`
    + `<rect x="0" y="0" width="300" height="400" fill="url(#b)"/><rect x="0" y="0" width="300" height="400" fill="url(#g1)"/>`
    + `<rect x="0" y="0" width="300" height="400" fill="url(#g2)"/>${body}`
    + `<rect x="0" y="0" width="300" height="400" fill="url(#v)"/></svg>\n`;
}

export function exportAll() {
  const catalog = JSON.parse(readFileSync(path.join(root, 'provider', 'catalog.json'), 'utf8'));
  return new Map(catalog.games.filter((g) => !g.hidden)
    .map((g) => [g.slug + '.svg', exportArt({ slug: g.slug, accent: g.accent, title: g.title })]));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const check = process.argv.includes('--check');
  const dir = process.argv.slice(2).find((a) => !a.startsWith('--'));
  if (!dir) { console.error('usage: export_game_art.mjs [--check] DIR'); process.exit(2); }
  const files = exportAll();
  if (check) {
    let present = [];
    try { present = readdirSync(dir).filter((f) => f.endsWith('.svg')); } catch { /* missing = stale */ }
    const stale = [...files].filter(([f, svg]) => {
      try { return readFileSync(path.join(dir, f), 'utf8') !== svg; } catch { return true; }
    }).map(([f]) => f).concat(present.filter((f) => !files.has(f)));
    if (stale.length) { console.error(`game art in ${dir} is stale: ${stale.join(', ')}`); process.exit(1); }
    console.log(`game art in ${dir} is current (${files.size} titles)`);
  } else {
    mkdirSync(dir, { recursive: true });
    for (const [f, svg] of files) writeFileSync(path.join(dir, f), svg);
    console.log(`wrote ${files.size} titles to ${dir}, ${[...files.values()].reduce((n, s) => n + s.length, 0)} bytes`);
  }
}
