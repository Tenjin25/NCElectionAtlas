/* eslint-disable no-console */
const fs = require('fs');
const path = require('path');

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

function buildCanonicalKeySet(repoRoot) {
  const payload = JSON.parse(fs.readFileSync(path.join(repoRoot, 'data', 'Voting_Precincts.geojson'), 'utf8'));
  const out = new Set();
  for (const feature of (payload.features || [])) {
    const props = feature.properties || {};
    const county = norm(props.county_nam);
    const prec = norm(props.prec_id);
    if (county && prec) out.add(`${county} - ${prec}`);
  }
  return out;
}

function baseKeyIfMergeable(key, canonical) {
  if (canonical.has(key)) return null;
  const parts = key.split(/ - (.+)/, 2);
  if (parts.length !== 2) return null;
  const county = parts[0];
  const precinct = parts[1];
  const match = precinct.match(/^(.+?)([A-Z])$/);
  if (!match) return null;
  const baseKey = `${county} - ${match[1]}`;
  if (!canonical.has(baseKey)) return null;
  return baseKey;
}

function main() {
  const repoRoot = path.resolve(__dirname, '..');
  const canonical = buildCanonicalKeySet(repoRoot);
  const contestDir = path.join(repoRoot, 'data', 'contests');
  const summary = {};

  for (const fileName of fs.readdirSync(contestDir).filter((name) => name.endsWith('_2024.json')).sort()) {
    const filePath = path.join(contestDir, fileName);
    const payload = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    const rows = payload.rows || [];
    const rowMap = new Map();
    const order = [];
    const merged = [];

    for (const row of rows) {
      const key = norm(row.county);
      const baseKey = baseKeyIfMergeable(key, canonical);
      const targetKey = baseKey || key;
      if (!rowMap.has(targetKey)) {
        rowMap.set(targetKey, recalcDerived({ ...row, county: targetKey }));
        order.push(targetKey);
      } else {
        const existing = rowMap.get(targetKey);
        rowMap.set(targetKey, recalcDerived({
          ...existing,
          county: targetKey,
          dem_votes: numericVote(existing.dem_votes) + numericVote(row.dem_votes),
          rep_votes: numericVote(existing.rep_votes) + numericVote(row.rep_votes),
          other_votes: numericVote(existing.other_votes) + numericVote(row.other_votes),
        }));
      }
      if (baseKey) merged.push(`${key}=>${baseKey}`);
    }

    if (merged.length > 0) {
      payload.rows = order.map((key) => rowMap.get(key));
      fs.writeFileSync(filePath, JSON.stringify(payload));
      summary[fileName] = Array.from(new Set(merged)).sort();
    }
  }

  console.log(JSON.stringify(summary, null, 2));
}

main();
