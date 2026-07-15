/* eslint-disable no-console */
const fs = require('fs');
const path = require('path');

const OFFICE = 'US PRESIDENT';
const CONTEST_TYPE = 'president';
const YEAR = 2024;

const NON_GEO_FLAGS = [
  'ABS',
  'ABSENTEE',
  'ABSEN',
  'ABS-SUPPLEMENTAL',
  'BOE',
  'CV',
  'EARLYVOTE',
  'PROVISIONAL',
  'PROVI',
  'PROV',
  'PROVSIONAL',
  'TRANS',
  'CURBSIDE',
  'ONE STOP',
  'ONE-STOP',
  'EARLY VOT',
  'TRANSFER',
  'MAIL',
  'VOTE CENTER',
  'VOTECENTER',
  'ELECTIONS ANNEX',
];

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

function parseCsv(text) {
  const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/).filter(Boolean);
  if (!lines.length) return [];
  const headers = parseCsvLine(lines[0]);
  return lines.slice(1).map((line) => {
    const values = parseCsvLine(line);
    const row = {};
    headers.forEach((header, index) => {
      row[header] = values[index] ?? '';
    });
    return row;
  });
}

function norm(value) {
  return String(value || '').trim().toUpperCase();
}

function splitPrecinctKey(key) {
  const value = norm(key);
  const parts = value.split(/ - (.+)/, 2);
  return parts.length === 2 ? { county: parts[0], precinct: parts[1] } : { county: value, precinct: '' };
}

function isDefinitelyNonGeo(precinct) {
  const token = norm(precinct);
  if (!token) return true;
  if (token === 'EV' || token.startsWith('EV') || token.startsWith('OS-')) return true;
  if (token.endsWith(' EV') || token.includes(' EV ')) return true;
  if (/^(ABSEN|PROVI|TRANS)\s+\d+/i.test(token)) return true;
  return NON_GEO_FLAGS.some((flag) => token === flag || token.includes(flag));
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

function numericVote(value) {
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) ? n : 0;
}

function recalcDerived(row) {
  const demVotes = numericVote(row.dem_votes);
  const repVotes = numericVote(row.rep_votes);
  const otherVotes = numericVote(row.other_votes);
  const totalVotes = demVotes + repVotes + otherVotes;
  const margin = repVotes - demVotes;
  const marginPct = totalVotes ? Number(((margin / totalVotes) * 100).toFixed(4)) : 0;
  const winner = repVotes > demVotes ? 'REP' : demVotes > repVotes ? 'DEM' : 'TIE';
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

function allocateIntegerShares(total, weights) {
  const safeTotal = numericVote(total);
  if (safeTotal <= 0 || !weights.length) return weights.map(() => 0);
  const weightSum = weights.reduce((sum, weight) => sum + Number(weight || 0), 0);
  if (!(weightSum > 0)) return weights.map(() => 0);
  const raw = weights.map((weight) => (safeTotal * Number(weight || 0)) / weightSum);
  const floors = raw.map((value) => Math.floor(value));
  let remainder = safeTotal - floors.reduce((sum, value) => sum + value, 0);
  const order = raw
    .map((value, index) => ({ index, frac: value - floors[index] }))
    .sort((a, b) => b.frac - a.frac || a.index - b.index);
  for (let i = 0; i < order.length && remainder > 0; i += 1) {
    floors[order[i].index] += 1;
    remainder -= 1;
  }
  return floors;
}

function emptyBucket(county, precinct) {
  return {
    year: YEAR,
    county: `${county} - ${precinct}`,
    dem_votes: 0,
    rep_votes: 0,
    other_votes: 0,
    dem_candidate: '',
    rep_candidate: '',
  };
}

function addVotes(bucket, party, votes, candidate = '') {
  const v = numericVote(votes);
  if (party === 'DEM') {
    bucket.dem_votes += v;
    if (!bucket.dem_candidate) bucket.dem_candidate = candidate;
  } else if (party === 'REP') {
    bucket.rep_votes += v;
    if (!bucket.rep_candidate) bucket.rep_candidate = candidate;
  } else {
    bucket.other_votes += v;
  }
}

function loadBridge(repoRoot) {
  const bridgePath = path.join(repoRoot, 'data', 'crosswalks', 'precinct_sbe_2024_to_onemap_2025_12_vap.csv');
  const rows = parseCsv(fs.readFileSync(bridgePath, 'utf8'));
  const bridge = new Map();
  for (const row of rows) {
    const source = norm(row.sbe_precinct_id);
    const target = norm(row.onemap_precinct_id);
    const share = Number.parseFloat(row.share || '0');
    if (!source || !target || !(share > 0)) continue;
    if (!bridge.has(source)) bridge.set(source, []);
    bridge.get(source).push({ target, share });
  }
  for (const [source, entries] of bridge.entries()) {
    const total = entries.reduce((sum, entry) => sum + entry.share, 0);
    if (!(total > 0)) {
      bridge.delete(source);
      continue;
    }
    bridge.set(source, entries.map((entry) => ({ ...entry, share: entry.share / total })));
  }
  return bridge;
}

function buildSbeRows(rawRows, bridge) {
  const geoByCounty = new Map();
  const nonGeoByCounty = new Map();

  for (const row of rawRows) {
    if (norm(row.office) !== OFFICE) continue;
    const county = norm(row.county);
    const precinct = norm(row.precinct);
    if (!county || !precinct) continue;

    const sourceKey = `${county} - ${precinct}`;
    const isGeo = bridge.has(sourceKey) || !isDefinitelyNonGeo(precinct);
    const targetMap = isGeo ? geoByCounty : nonGeoByCounty;
    if (!targetMap.has(county)) targetMap.set(county, new Map());
    const countyMap = targetMap.get(county);
    if (!countyMap.has(precinct)) countyMap.set(precinct, emptyBucket(county, precinct));
    addVotes(countyMap.get(precinct), norm(row.party), row.votes, String(row.candidate || '').trim());
  }

  for (const [county, nonGeoRows] of nonGeoByCounty.entries()) {
    const geoRows = Array.from((geoByCounty.get(county) || new Map()).values());
    if (!geoRows.length) continue;
    const partySpecs = [
      ['DEM', 'dem_votes'],
      ['REP', 'rep_votes'],
      ['OTHER', 'other_votes'],
    ];
    for (const [, voteField] of partySpecs) {
      const weights = geoRows.map((row) => numericVote(row[voteField]));
      const fallbackWeights = geoRows.map((row) => numericVote(row.dem_votes) + numericVote(row.rep_votes) + numericVote(row.other_votes));
      for (const nonGeo of nonGeoRows.values()) {
        const votes = numericVote(nonGeo[voteField]);
        if (votes <= 0) continue;
        const alloc = allocateIntegerShares(votes, weights.some((weight) => weight > 0) ? weights : fallbackWeights);
        alloc.forEach((shareVotes, index) => {
          geoRows[index][voteField] += shareVotes;
        });
      }
    }
  }

  return Array.from(geoByCounty.values()).flatMap((countyMap) => Array.from(countyMap.values()).map(recalcDerived));
}

function bridgeRowsToOneMap(sbeRows, bridge) {
  const expanded = [];
  for (const row of sbeRows) {
    const sourceKey = norm(row.county);
    const entries = bridge.get(sourceKey);
    if (!entries || !entries.length) {
      expanded.push(row);
      continue;
    }
    const demAlloc = allocateIntegerShares(row.dem_votes, entries.map((entry) => entry.share));
    const repAlloc = allocateIntegerShares(row.rep_votes, entries.map((entry) => entry.share));
    const otherAlloc = allocateIntegerShares(row.other_votes, entries.map((entry) => entry.share));
    entries.forEach((entry, index) => {
      expanded.push(recalcDerived({
        ...row,
        county: entry.target,
        dem_votes: demAlloc[index],
        rep_votes: repAlloc[index],
        other_votes: otherAlloc[index],
      }));
    });
  }
  return expanded;
}

function aggregateRows(rows) {
  const byKey = new Map();
  const order = [];
  for (const row of rows) {
    const key = norm(row.county);
    if (!byKey.has(key)) {
      byKey.set(key, { ...row, county: key });
      order.push(key);
      continue;
    }
    const existing = byKey.get(key);
    existing.dem_votes += numericVote(row.dem_votes);
    existing.rep_votes += numericVote(row.rep_votes);
    existing.other_votes += numericVote(row.other_votes);
    if (!existing.dem_candidate) existing.dem_candidate = row.dem_candidate || '';
    if (!existing.rep_candidate) existing.rep_candidate = row.rep_candidate || '';
    byKey.set(key, recalcDerived(existing));
  }
  return order.map((key) => recalcDerived(byKey.get(key))).sort((a, b) => a.county.localeCompare(b.county));
}

function updateManifest(repoRoot, fileName, rowCount) {
  const manifestPath = path.join(repoRoot, 'data', 'contests', 'manifest.json');
  if (!fs.existsSync(manifestPath)) return;
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const files = Array.isArray(manifest.files) ? manifest.files : [];
  const entry = files.find((row) => row && row.file === fileName);
  if (entry) {
    entry.rows = rowCount;
  } else {
    files.push({ year: YEAR, contest_type: CONTEST_TYPE, file: fileName, rows: rowCount });
    manifest.files = files;
  }
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
}

function main() {
  const repoRoot = path.resolve(__dirname, '..');
  const rawPath = path.join(repoRoot, 'data', '2024', '20241105__nc__general__precinct.csv');
  const outFile = 'president_2024.json';
  const outPath = path.join(repoRoot, 'data', 'contests', outFile);

  const rawRows = parseCsv(fs.readFileSync(rawPath, 'utf8'));
  const bridge = loadBridge(repoRoot);
  const sbeRows = buildSbeRows(rawRows, bridge);
  const oneMapRows = aggregateRows(bridgeRowsToOneMap(sbeRows, bridge));
  const rawTotals = rawRows
    .filter((row) => norm(row.office) === OFFICE)
    .reduce((acc, row) => {
      const party = norm(row.party);
      const votes = numericVote(row.votes);
      if (party === 'DEM') acc.dem += votes;
      else if (party === 'REP') acc.rep += votes;
      else acc.other += votes;
      acc.total += votes;
      return acc;
    }, { dem: 0, rep: 0, other: 0, total: 0 });

  const payload = {
    year: YEAR,
    contest_type: CONTEST_TYPE,
    meta: {
      source: 'sbe2024_to_onemap2025_12_vap_bridge',
      office: OFFICE,
      nongeo_allocation_mode: 'county_party_geographic_share',
      bridge: 'data/crosswalks/precinct_sbe_2024_to_onemap_2025_12_vap.csv',
      modern_target_precincts: 'data/census/SBE_PRECINCTS_20251212/SBE_PRECINCTS_20251212.shp',
      display_geojson: 'data/2025Voting_Precincts.geojson',
      dem_total: rawTotals.dem,
      rep_total: rawTotals.rep,
      other_total: rawTotals.other,
      total_votes: rawTotals.total,
      major_party_contested: true,
    },
    rows: oneMapRows,
  };

  fs.writeFileSync(outPath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  updateManifest(repoRoot, outFile, oneMapRows.length);
  console.log(JSON.stringify({
    file: outFile,
    rows: oneMapRows.length,
    sbe_rows: sbeRows.length,
    bridge_keys: bridge.size,
    totals: rawTotals,
  }, null, 2));
}

main();
