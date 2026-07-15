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

function calculateCompetitiveness(marginPct) {
  const absMargin = Math.abs(marginPct);
  if (absMargin < 0.5) return '#f7f7f7';
  const repWin = marginPct > 0;
  if (absMargin >= 40) return repWin ? '#67000d' : '#08306b';
  if (absMargin >= 30) return repWin ? '#a50f15' : '#08519c';
  if (absMargin >= 20) return repWin ? '#cb181d' : '#3182bd';
  if (absMargin >= 10) return repWin ? '#ef3b2c' : '#6baed6';
  if (absMargin >= 5.5) return repWin ? '#fb6a4a' : '#9ecae1';
  if (absMargin >= 1) return repWin ? '#fcae91' : '#c6dbef';
  return repWin ? '#fee8c8' : '#e1f5fe';
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

function buildWeightedMapping(repoRoot) {
  const bridgePath = path.join(repoRoot, 'data', 'crosswalks', 'precinct_sbe_2024_to_onemap_2025_12_vap.csv');
  const rows = parseCsv(fs.readFileSync(bridgePath, 'utf8'));
  const grouped = new Map();

  for (const row of rows) {
    const sourceKey = norm(row.sbe_precinct_id);
    const targetKey = norm(row.onemap_precinct_id);
    if (!sourceKey || !targetKey) continue;
    if (isDefinitelyNonGeo(sourceKey)) continue;
    const weight = Number.parseFloat(row.share || '0');
    if (!(weight > 0)) continue;
    if (!grouped.has(sourceKey)) grouped.set(sourceKey, []);
    grouped.get(sourceKey).push({
      sourceKey,
      targetKey,
      county: sourceKey.split(/ - (.+)/, 2)[0] || '',
      weight,
      jaccard: weight,
    });
  }

  const mapping = new Map();
  for (const [sourceKey, candidates] of grouped.entries()) {
    candidates.sort((a, b) => b.weight - a.weight || b.jaccard - a.jaccard || a.targetKey.localeCompare(b.targetKey));
    const uniqueTargets = [];
    const seen = new Set();
    for (const candidate of candidates) {
      if (seen.has(candidate.targetKey)) continue;
      seen.add(candidate.targetKey);
      uniqueTargets.push(candidate);
    }
    const sumWeights = uniqueTargets.reduce((sum, candidate) => sum + candidate.weight, 0);
    if (!(sumWeights > 0.95 && sumWeights < 1.05)) continue;
    mapping.set(sourceKey, uniqueTargets.map((candidate) => ({
      ...candidate,
      normWeight: candidate.weight / sumWeights,
    })));
  }

  return mapping;
}

function updateContestManifest(repoRoot, changedFiles) {
  const manifestPath = path.join(repoRoot, 'data', 'contests', 'manifest.json');
  if (!fs.existsSync(manifestPath)) return;
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const files = Array.isArray(manifest.files) ? manifest.files : [];
  let changed = false;
  for (const [fileName, result] of Object.entries(changedFiles)) {
    const entry = files.find((row) => row && row.file === fileName);
    if (!entry) continue;
    const nextRows = Number(result.expandedRows || 0);
    if (Number.isFinite(nextRows) && nextRows > 0 && Number(entry.rows) !== nextRows) {
      entry.rows = nextRows;
      changed = true;
    }
  }
  if (changed) {
    fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  }
}

function allocateIntegerShares(total, weights) {
  const raw = weights.map((weight) => total * weight);
  const floors = raw.map((value) => Math.floor(value));
  let remainder = total - floors.reduce((sum, value) => sum + value, 0);
  const order = raw
    .map((value, index) => ({ index, frac: value - floors[index] }))
    .sort((a, b) => b.frac - a.frac || a.index - b.index);
  for (let i = 0; i < order.length && remainder > 0; i += 1) {
    floors[order[i].index] += 1;
    remainder -= 1;
  }
  return floors;
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

function recalcDerived(row) {
  const demVotes = numericVote(row.dem_votes);
  const repVotes = numericVote(row.rep_votes);
  const otherVotes = numericVote(row.other_votes);
  const totalVotes = demVotes + repVotes + otherVotes;
  const margin = repVotes - demVotes;
  const marginPct = totalVotes ? Number(((margin / totalVotes) * 100).toFixed(4)) : 0;
  let winner = 'TIE';
  if (repVotes > demVotes) winner = 'REP';
  else if (demVotes > repVotes) winner = 'DEM';
  return {
    ...row,
    dem_votes: demVotes,
    rep_votes: repVotes,
    other_votes: otherVotes,
    total_votes: totalVotes,
    margin,
    margin_pct: marginPct,
    winner,
    color: calculateCompetitiveness(marginPct),
  };
}

function expandRow(row, weightedMapping) {
  const sourceKey = norm(row.county);
  const targets = weightedMapping.get(sourceKey);
  if (!targets) return [row];

  const weights = targets.map((target) => target.normWeight);
  const demAlloc = allocateIntegerShares(numericVote(row.dem_votes), weights);
  const repAlloc = allocateIntegerShares(numericVote(row.rep_votes), weights);
  const otherAlloc = allocateIntegerShares(numericVote(row.other_votes), weights);

  return targets.map((target, index) => recalcDerived({
    ...row,
    county: target.targetKey,
    dem_votes: demAlloc[index],
    rep_votes: repAlloc[index],
    other_votes: otherAlloc[index],
  }));
}

function aggregateRows(rows) {
  const byCounty = new Map();
  const order = [];
  for (const row of rows) {
    const key = norm(row.county);
    if (!byCounty.has(key)) {
      byCounty.set(key, { ...row });
      order.push(key);
      continue;
    }
    const existing = byCounty.get(key);
    existing.dem_votes = numericVote(existing.dem_votes) + numericVote(row.dem_votes);
    existing.rep_votes = numericVote(existing.rep_votes) + numericVote(row.rep_votes);
    existing.other_votes = numericVote(existing.other_votes) + numericVote(row.other_votes);
    byCounty.set(key, recalcDerived(existing));
  }
  return order.map((key) => recalcDerived(byCounty.get(key)));
}

function applyToFile(filePath, weightedMapping) {
  const payload = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  // These rows still reflect the source election CSV here. Preserve their exact
  // county sums before any precinct crosswalk allocation changes the row layer.
  if (!payload.county_totals || Object.keys(payload.county_totals).length === 0) {
    payload.county_totals = buildCountyTotals(payload.rows);
  }
  const expanded = [];
  let replacedRows = 0;
  const touched = new Set();

  for (const row of (payload.rows || [])) {
    const nextRows = expandRow(row, weightedMapping);
    if (nextRows.length !== 1 || norm(nextRows[0].county) !== norm(row.county)) {
      replacedRows += 1;
      touched.add(norm(row.county));
    }
    expanded.push(...nextRows);
  }

  if (replacedRows === 0) return { replacedRows: 0, expandedRows: 0, touched: [] };
  payload.rows = aggregateRows(expanded);
  fs.writeFileSync(filePath, JSON.stringify(payload));
  return {
    replacedRows,
    expandedRows: payload.rows.length,
    touched: Array.from(touched).sort(),
  };
}

function main() {
  const repoRoot = path.resolve(__dirname, '..');
  const contestDir = path.join(repoRoot, 'data', 'contests');
  const requestedFiles = new Set(process.argv.slice(2).map((name) => path.basename(name)));
  const weightedMapping = buildWeightedMapping(repoRoot);
  const changedFiles = {};
  let totalReplacedRows = 0;

  for (const fileName of fs.readdirSync(contestDir).filter((name) => name.endsWith('_2024.json')).sort()) {
    if (requestedFiles.size > 0 && !requestedFiles.has(fileName)) continue;
    const result = applyToFile(path.join(contestDir, fileName), weightedMapping);
    if (result.replacedRows > 0) {
      changedFiles[fileName] = result;
      totalReplacedRows += result.replacedRows;
    }
  }
  updateContestManifest(repoRoot, changedFiles);

  console.log(JSON.stringify({
    weighted_source_key_count: weightedMapping.size,
    total_replaced_rows: totalReplacedRows,
    changed_files: changedFiles,
    gaston_targets: weightedMapping.get('GASTON - 41') || [],
  }, null, 2));
}

main();
