/* eslint-disable no-console */
/**
 * Create missing early (pre-2018) statewide judicial contest slices keyed by
 * Wikipedia seat numbers. Never overwrites existing contest JSON files.
 *
 * Usage:
 *   node scripts/add_early_comparable_judicial_contests.js
 *   node scripts/add_early_comparable_judicial_contests.js --dry-run
 */
const fs = require('fs');
const path = require('path');

const {
  rebuildYear,
  updateManifest,
} = require('./rebuild_statewide_contests_from_sbe_bridge');

const ROOT = path.resolve(__dirname, '..');
const CONTESTS_DIR = path.join(ROOT, 'data', 'contests');
const CROSSWALK = path.join(ROOT, 'data', 'mappings', 'judicial_seat_crosswalk.csv');

/** First clear batch: same-seat, two-party compare-friendly (skip plurality / held-back). */
const CLEAR_ADD_KEYS = new Set([
  'supreme|CJ|2000',
  'supreme|6|2000',
  'supreme|1|2002',
  'supreme|2|2002',
  'supreme|2|2004',
  'supreme|4|2004',
  'supreme|CJ|2006',
  'supreme|3|2006',
  'supreme|4|2006',
  'supreme|5|2006',
  'coa|1|2000',
  'coa|7|2000',
  'coa|10|2000',
  'coa|11|2000',
  'coa|13|2000',
  'coa|2|2002',
  'coa|3|2002',
  'coa|12|2002',
  'coa|14|2002',
  'coa|15|2002',
  'coa|4|2004',
  'coa|5|2004',
  'coa|6|2004',
  'coa|8|2006',
  'coa|9|2006',
]);

function parseCsv(text) {
  const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/).filter(Boolean);
  if (!lines.length) return [];
  const headers = lines[0].split(',');
  // Crosswalk notes can contain commas; use a simple RFC-ish parse for quoted fields.
  const parseLine = (line) => {
    const out = [];
    let cur = '';
    let q = false;
    for (let i = 0; i < line.length; i += 1) {
      const ch = line[i];
      if (ch === '"') {
        if (q && line[i + 1] === '"') {
          cur += '"';
          i += 1;
        } else {
          q = !q;
        }
      } else if (ch === ',' && !q) {
        out.push(cur);
        cur = '';
      } else {
        cur += ch;
      }
    }
    out.push(cur);
    return out;
  };
  return lines.slice(1).map((line) => {
    const values = parseLine(line);
    const row = {};
    headers.forEach((h, i) => {
      row[h.trim()] = (values[i] || '').trim();
    });
    return row;
  });
}

function loadClearTargets() {
  const rows = parseCsv(fs.readFileSync(CROSSWALK, 'utf8'));
  return rows.filter((row) => {
    const key = `${row.court}|${row.seat}|${row.year}`;
    return CLEAR_ADD_KEYS.has(key);
  });
}

function ensureStub(target) {
  const year = Number(target.year);
  const contestType = String(target.contest_type).trim();
  const fileName = `${contestType}_${year}.json`;
  const outPath = path.join(CONTESTS_DIR, fileName);
  if (fs.existsSync(outPath)) {
    return { fileName, outPath, created: false, skippedExisting: true };
  }
  const stub = {
    year,
    contest_type: contestType,
    meta: {
      office: target.oe_office,
      incumbent_label: target.incumbent_label || '',
      seat: String(target.seat),
      court: String(target.court),
      source: 'pending_rebuild',
    },
    county_totals: {},
    rows: [],
  };
  fs.writeFileSync(outPath, `${JSON.stringify(stub, null, 2)}\n`, 'utf8');
  updateManifest(ROOT, fileName, year, contestType, 0);
  return { fileName, outPath, created: true, skippedExisting: false };
}

function main() {
  const dryRun = process.argv.includes('--dry-run');
  const targets = loadClearTargets();
  if (!targets.length) {
    throw new Error('No clear targets loaded from judicial_seat_crosswalk.csv');
  }

  const byYear = new Map();
  const plan = [];
  for (const target of targets) {
    const year = Number(target.year);
    const contestType = String(target.contest_type).trim();
    const fileName = `${contestType}_${year}.json`;
    const exists = fs.existsSync(path.join(CONTESTS_DIR, fileName));
    plan.push({
      year,
      contestType,
      fileName,
      office: target.oe_office,
      exists,
      action: exists ? 'skip_existing' : 'create',
    });
    if (!exists) {
      if (!byYear.has(year)) byYear.set(year, []);
      byYear.get(year).push(fileName);
    }
  }

  console.log(JSON.stringify({ dry_run: dryRun, plan }, null, 2));
  if (dryRun) return;

  const created = [];
  for (const target of targets) {
    const result = ensureStub(target);
    if (result.created) created.push(result.fileName);
  }

  const summaries = [];
  for (const [year, files] of [...byYear.entries()].sort((a, b) => a[0] - b[0])) {
    summaries.push(rebuildYear(ROOT, year, files));
  }

  console.log(JSON.stringify({
    created,
    rebuilt: summaries.reduce((n, s) => n + ((s.rebuilt && s.rebuilt.length) || 0), 0),
    skipped: summaries.reduce((n, s) => n + ((s.skipped && s.skipped.length) || 0), 0),
    summaries,
  }, null, 2));
}

main();
