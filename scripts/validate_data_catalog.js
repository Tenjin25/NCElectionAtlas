#!/usr/bin/env node
// Read-only validation of every published contest slice referenced by a manifest.
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const catalogs = [
  ['data/contests', 'precinct'],
  ['data/district_contests', 'district'],
  ['data/district_contests_2024_lines', 'district'],
  ['data/district_contests_2026_lines', 'district']
];
const errors = [];
let files = 0;
let rows = 0;

function fail(file, message) {
  errors.push(`${file}: ${message}`);
}

function parseJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch (error) { fail(path.relative(root, file), `invalid JSON: ${error.message}`); return null; }
}

function validateVotes(file, label, row) {
  if (!row || typeof row !== 'object') {
    fail(file, `${label} is not an object`);
    return;
  }
  const values = ['dem_votes', 'rep_votes', 'other_votes', 'total_votes'].map(key => Number(row[key]));
  if (values.some(value => !Number.isSafeInteger(value) || value < 0)) {
    fail(file, `${label} has missing, negative, or noninteger votes`);
    return;
  }
  if (values[0] + values[1] + values[2] !== values[3]) {
    fail(file, `${label} votes do not sum to total_votes`);
  }
  rows += 1;
}

for (const [relativeDir, kind] of catalogs) {
  const dir = path.join(root, relativeDir);
  const manifestPath = path.join(dir, 'manifest.json');
  if (!fs.existsSync(manifestPath)) continue;
  const manifest = parseJson(manifestPath);
  if (!manifest) continue;
  const entries = manifest.files;
  if (!Array.isArray(entries)) { fail(relativeDir, 'manifest.files is missing'); continue; }
  const seen = new Set();
  for (const entry of entries) {
    const name = String(entry?.file || '');
    if (!name || path.basename(name) !== name || !name.endsWith('.json')) {
      fail(relativeDir, `unsafe or invalid manifest file: ${name}`);
      continue;
    }
    if (seen.has(name)) { fail(relativeDir, `duplicate manifest entry: ${name}`); continue; }
    seen.add(name);
    const file = path.join(dir, name);
    const rel = path.relative(root, file);
    if (!fs.existsSync(file)) { fail(rel, 'manifest target missing'); continue; }
    const payload = parseJson(file);
    if (!payload) continue;
    files += 1;
    if (Number(payload.year) !== Number(entry.year)) fail(rel, 'year differs from manifest');
    if (String(payload.contest_type || '') !== String(entry.contest_type || '')) fail(rel, 'contest type differs from manifest');
    if (kind === 'district') {
      if (String(payload.scope || '') !== String(entry.scope || '')) fail(rel, 'scope differs from manifest');
      const results = payload?.general?.results;
      if (!results || typeof results !== 'object' || Array.isArray(results)) {
        fail(rel, 'general.results missing');
        continue;
      }
      for (const [district, row] of Object.entries(results)) validateVotes(rel, `district ${district}`, row);
    } else {
      if (!Array.isArray(payload.rows)) { fail(rel, 'rows missing'); continue; }
      for (const [index, row] of payload.rows.entries()) validateVotes(rel, `row ${index}`, row);
      const totals = payload.county_totals;
      if (totals && typeof totals === 'object') {
        for (const [county, row] of Object.entries(totals)) validateVotes(rel, `county ${county}`, row);
      }
    }
  }
}

console.log(`Checked ${files} published contest slices and ${rows} vote rows.`);
if (errors.length) {
  errors.slice(0, 40).forEach(error => console.error(error));
  if (errors.length > 40) console.error(`...and ${errors.length - 40} more errors`);
  process.exitCode = 1;
} else {
  console.log('All manifest targets and vote-row arithmetic passed.');
}
