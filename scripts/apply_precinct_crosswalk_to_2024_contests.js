/* eslint-disable no-console */
const fs = require('fs');
const path = require('path');

function parseCsv(text) {
  const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/).filter(Boolean);
  if (lines.length === 0) return [];
  const headers = parseCsvLine(lines[0]);
  return lines.slice(1).map((line) => {
    const values = parseCsvLine(line);
    const row = {};
    for (let i = 0; i < headers.length; i += 1) {
      row[headers[i]] = values[i] ?? '';
    }
    return row;
  });
}

function parseCsvLine(line) {
  const out = [];
  let current = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === ',' && !inQuotes) {
      out.push(current);
      current = '';
    } else {
      current += ch;
    }
  }
  out.push(current);
  return out;
}

function norm(value) {
  return String(value || '').trim().toUpperCase();
}

function numericVote(value) {
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) ? n : 0;
}

function buildCountyTotals(rows) {
  const totals = {};
  for (const row of rows || []) {
    const county = norm(row.county).split(' - ')[0].trim();
    if (!county) continue;
    if (!totals[county]) {
      totals[county] = {
        dem_votes: 0,
        rep_votes: 0,
        other_votes: 0,
        total_votes: 0,
        dem_candidate: String(row.dem_candidate || ''),
        rep_candidate: String(row.rep_candidate || ''),
      };
    }
    totals[county].dem_votes += numericVote(row.dem_votes);
    totals[county].rep_votes += numericVote(row.rep_votes);
    totals[county].other_votes += numericVote(row.other_votes);
    totals[county].total_votes += numericVote(row.total_votes);
  }
  return totals;
}

function buildCanonicalKeySet(repoRoot) {
  const payload = JSON.parse(fs.readFileSync(path.join(repoRoot, 'data', '2025Voting_Precincts.geojson'), 'utf8'));
  const out = new Set();
  for (const feature of (payload.features || [])) {
    const props = feature.properties || {};
    const county = norm(props.county_nam);
    const prec = norm(props.prec_id);
    if (county && prec) out.add(`${county} - ${prec}`);
  }
  return out;
}

function isDefinitelyNonGeo(key) {
  const t = norm(key.split(/ - (.+)/, 2)[1] || key);
  return [
    'ABSENTEE',
    'ABS ',
    'ABS-',
    'ABS_',
    'ONE STOP',
    'PROVISIONAL',
    'PROVI',
    'EARLY',
    'TRANSFER',
    'CURBSIDE',
    'EV ',
    'EV-',
    'EV_',
    ' BOE',
  ].some((flag) => t.includes(flag)) || t.startsWith('OS-') || t.startsWith('EV');
}

function buildSafeRemapTable(repoRoot) {
  const detailPath = path.join(repoRoot, 'data', 'crosswalks', 'precinct_stable_to_nconemap_2026_07_detail.csv');
  const rows = parseCsv(fs.readFileSync(detailPath, 'utf8'));
  const canonical = buildCanonicalKeySet(repoRoot);
  const oldTargetsByNew = new Map();
  const newSourcesByOld = new Map();

  for (const row of rows) {
    const oldKey = norm(row.old_precinct_key);
    const newKey = norm(row.new_precinct_key);
    if (!oldTargetsByNew.has(newKey)) oldTargetsByNew.set(newKey, new Set());
    oldTargetsByNew.get(newKey).add(oldKey);
    if (!newSourcesByOld.has(oldKey)) newSourcesByOld.set(oldKey, new Set());
    newSourcesByOld.get(oldKey).add(newKey);
  }

  const remaps = new Map();
  const diagnostics = [];
  for (const row of rows) {
    const sourceKey = norm(row.old_precinct_key);
    const targetKey = norm(row.new_precinct_key);
    if (!sourceKey || !targetKey || sourceKey === targetKey) continue;
    if (canonical.has(sourceKey)) continue;
    if (!canonical.has(targetKey)) continue;
    if (isDefinitelyNonGeo(sourceKey)) continue;

    const newCount = (oldTargetsByNew.get(targetKey) || new Set()).size;
    const oldCount = (newSourcesByOld.get(sourceKey) || new Set()).size;
    const oldShare = Number.parseFloat(row.old_share || '0');
    const newShare = Number.parseFloat(row.new_share || '0');
    const jaccard = Number.parseFloat(row.jaccard || '0');
    const safe = newCount === 1 && oldCount === 1 && oldShare >= 0.98 && newShare >= 0.98 && jaccard >= 0.98;

    diagnostics.push({
      county: row.county,
      from: sourceKey,
      to: targetKey,
      newCount,
      oldCount,
      oldShare,
      newShare,
      jaccard,
      safe,
    });
    if (safe) remaps.set(sourceKey, targetKey);
  }

  return { remaps, diagnostics };
}

function applyRemapsToFile(filePath, remaps) {
  const payload = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  // Preserve canonical source-CSV county sums separately from remapped precinct rows.
  if (!payload.county_totals || Object.keys(payload.county_totals).length === 0) {
    payload.county_totals = buildCountyTotals(payload.rows);
  }
  let changed = 0;
  const keys = new Set();
  for (const row of (payload.rows || [])) {
    const current = norm(row.county);
    const next = remaps.get(current);
    if (!next) continue;
    row.county = next;
    changed += 1;
    keys.add(`${current}=>${next}`);
  }
  if (changed > 0) {
    fs.writeFileSync(filePath, JSON.stringify(payload));
  }
  return { changed, keys: Array.from(keys).sort() };
}

function main() {
  const repoRoot = path.resolve(__dirname, '..');
  const contestDir = path.join(repoRoot, 'data', 'contests');
  const requestedFiles = new Set(process.argv.slice(2).map((name) => path.basename(name)));
  const { remaps, diagnostics } = buildSafeRemapTable(repoRoot);

  const fileSummaries = {};
  let totalRowsChanged = 0;
  for (const fileName of fs.readdirSync(contestDir).filter((name) => name.endsWith('_2024.json')).sort()) {
    if (requestedFiles.size > 0 && !requestedFiles.has(fileName)) continue;
    const filePath = path.join(contestDir, fileName);
    const result = applyRemapsToFile(filePath, remaps);
    if (result.changed > 0) {
      fileSummaries[fileName] = result;
      totalRowsChanged += result.changed;
    }
  }

  const safeByCounty = {};
  const skippedByCounty = {};
  for (const row of diagnostics) {
    const bucket = row.safe ? safeByCounty : skippedByCounty;
    if (!bucket[row.county]) bucket[row.county] = [];
    bucket[row.county].push({
      from: row.from,
      to: row.to,
      newCount: row.newCount,
      oldCount: row.oldCount,
      oldShare: row.oldShare,
      newShare: row.newShare,
      jaccard: row.jaccard,
    });
  }

  console.log(JSON.stringify({
    safe_remap_count: remaps.size,
    total_rows_changed: totalRowsChanged,
    changed_files: fileSummaries,
    gaston_safe_examples: (safeByCounty.GASTON || []).slice(0, 20),
    gaston_skipped_examples: (skippedByCounty.GASTON || []).slice(0, 20),
  }, null, 2));
}

main();
