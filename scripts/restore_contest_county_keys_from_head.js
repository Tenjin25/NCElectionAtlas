/* eslint-disable no-console */
const fs = require('fs');
const path = require('path');
const cp = require('child_process');

function normalizeCountyName(value) {
  return String(value || '').trim().toUpperCase();
}

function countyOf(key) {
  const text = String(key || '');
  const idx = text.indexOf(' - ');
  return idx === -1 ? '' : normalizeCountyName(text.slice(0, idx));
}

function signature(row) {
  const clone = { ...row };
  delete clone.county;
  return JSON.stringify(clone);
}

function buildIndex(rows, targetCounties) {
  const index = new Map();
  for (const row of rows) {
    const county = countyOf(row.county);
    if (!targetCounties.has(county)) continue;
    const key = `${county}|||${signature(row)}`;
    if (!index.has(key)) index.set(key, []);
    index.get(key).push(row.county);
  }
  return index;
}

function main() {
  const counties = new Set(process.argv.slice(2).map(normalizeCountyName).filter(Boolean));
  if (!counties.size) {
    console.error('Usage: node scripts/restore_contest_county_keys_from_head.js COUNTY [COUNTY ...]');
    process.exit(1);
  }

  const repoRoot = path.resolve(__dirname, '..');
  const contestDir = path.join(repoRoot, 'data', 'contests');
  const results = {};

  for (const fileName of fs.readdirSync(contestDir).filter((name) => name.endsWith('.json')).sort()) {
    const filePath = path.join(contestDir, fileName);
    const current = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    const headRaw = cp.execFileSync('git', ['show', `HEAD:data/contests/${fileName}`], {
      cwd: repoRoot,
      encoding: 'utf8',
      maxBuffer: 1024 * 1024 * 50
    });
    const head = JSON.parse(headRaw);

    const headIndex = buildIndex(head.rows || [], counties);
    let changed = 0;
    let skipped = 0;

    for (const row of current.rows || []) {
      const county = countyOf(row.county);
      if (!counties.has(county)) continue;
      const key = `${county}|||${signature(row)}`;
      const matches = headIndex.get(key) || [];
      if (matches.length === 1) {
        if (row.county !== matches[0]) {
          row.county = matches[0];
          changed += 1;
        }
      } else if (matches.length > 1) {
        skipped += 1;
      }
    }

    if (changed > 0) {
      fs.writeFileSync(filePath, JSON.stringify(current));
    }
    if (changed > 0 || skipped > 0) {
      results[fileName] = { changed, skipped };
    }
  }

  console.log(JSON.stringify(results, null, 2));
}

main();
