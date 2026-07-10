/* eslint-disable no-console */
const fs = require('fs');
const path = require('path');

const CONTEST_SPECS = [
  { office: 'US PRESIDENT', file: 'president_2024.json' },
  { office: 'NC COMMISSIONER OF AGRICULTURE', file: 'agriculture_commissioner_2024.json' },
  { office: 'NC ATTORNEY GENERAL', file: 'attorney_general_2024.json' },
  { office: 'NC AUDITOR', file: 'auditor_2024.json' },
  { office: 'NC GOVERNOR', file: 'governor_2024.json' },
  { office: 'NC COMMISSIONER OF INSURANCE', file: 'insurance_commissioner_2024.json' },
  { office: 'NC COMMISSIONER OF LABOR', file: 'labor_commissioner_2024.json' },
  { office: 'NC LIEUTENANT GOVERNOR', file: 'lieutenant_governor_2024.json' },
  { office: 'NC COURT OF APPEALS JUDGE SEAT 12', file: 'nc_court_of_appeals_judge_seat_12_2024.json' },
  { office: 'NC COURT OF APPEALS JUDGE SEAT 14', file: 'nc_court_of_appeals_judge_seat_14_2024.json' },
  { office: 'NC COURT OF APPEALS JUDGE SEAT 15', file: 'nc_court_of_appeals_judge_seat_15_2024.json' },
  { office: 'NC SUPREME COURT ASSOCIATE JUSTICE SEAT 06', file: 'nc_supreme_court_associate_justice_seat_06_2024.json' },
  { office: 'NC SECRETARY OF STATE', file: 'secretary_of_state_2024.json' },
  { office: 'NC SUPERINTENDENT OF PUBLIC INSTRUCTION', file: 'superintendent_2024.json' },
  { office: 'NC TREASURER', file: 'treasurer_2024.json' },
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
  const headers = parseCsvLine(lines[0] || '');
  return lines.slice(1).map((line) => {
    const values = parseCsvLine(line);
    const row = {};
    for (let i = 0; i < headers.length; i += 1) {
      row[headers[i]] = values[i] ?? '';
    }
    return row;
  });
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

function buildContestRows(rawRows, county, office) {
  const byPrecinct = new Map();
  for (const row of rawRows) {
    if (norm(row.county) !== county) continue;
    if (norm(row.office) !== office) continue;
    const precinct = norm(row.precinct);
    if (!precinct) continue;
    if (!byPrecinct.has(precinct)) {
      byPrecinct.set(precinct, {
        county: `${county} - ${precinct}`,
        dem_votes: 0,
        rep_votes: 0,
        other_votes: 0,
        dem_candidate: '',
        rep_candidate: '',
      });
    }
    const bucket = byPrecinct.get(precinct);
    const party = norm(row.party_detailed || row.party_simplified || row.party);
    const candidate = String(row.candidate || '').trim();
    const votes = Number.parseInt(row.votes || '0', 10) || 0;
    if (party === 'DEM') {
      bucket.dem_votes += votes;
      if (!bucket.dem_candidate) bucket.dem_candidate = candidate;
    } else if (party === 'REP') {
      bucket.rep_votes += votes;
      if (!bucket.rep_candidate) bucket.rep_candidate = candidate;
    } else {
      bucket.other_votes += votes;
    }
  }

  return Array.from(byPrecinct.values())
    .map((row) => {
      const total_votes = row.dem_votes + row.rep_votes + row.other_votes;
      const margin = row.rep_votes - row.dem_votes;
      const margin_pct = total_votes ? Number(((margin / total_votes) * 100).toFixed(4)) : 0;
      const winner = row.rep_votes > row.dem_votes ? 'REP' : row.dem_votes > row.rep_votes ? 'DEM' : 'TIE';
      return {
        year: 2024,
        county: row.county,
        dem_votes: row.dem_votes,
        rep_votes: row.rep_votes,
        other_votes: row.other_votes,
        total_votes,
        dem_candidate: row.dem_candidate,
        rep_candidate: row.rep_candidate,
        margin,
        margin_pct,
        winner,
        color: calculateCompetitiveness(margin_pct),
      };
    })
    .sort((a, b) => a.county.localeCompare(b.county));
}

function replaceCountyRows(filePath, countyPrefix, replacementRows) {
  const payload = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  const kept = (payload.rows || []).filter((row) => !norm(row.county).startsWith(`${countyPrefix} - `));
  payload.rows = kept.concat(replacementRows);
  fs.writeFileSync(filePath, JSON.stringify(payload));
  return { oldCount: (payload.rows || []).length - replacementRows.length, newCount: replacementRows.length };
}

function main() {
  const repoRoot = path.resolve(__dirname, '..');
  const rawPath = path.join(repoRoot, 'data', '2024', '20241105__nc__general__precinct.csv');
  const rawRows = parseCsv(fs.readFileSync(rawPath, 'utf8'));
  const county = norm(process.argv[2] || 'GASTON');
  const summary = {};

  for (const spec of CONTEST_SPECS) {
    const replacementRows = buildContestRows(rawRows, county, spec.office);
    const filePath = path.join(repoRoot, 'data', 'contests', spec.file);
    const payload = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    const oldCount = (payload.rows || []).filter((row) => norm(row.county).startsWith(`${county} - `)).length;
    replaceCountyRows(filePath, county, replacementRows);
    summary[spec.file] = {
      office: spec.office,
      replaced_rows: oldCount,
      restored_rows: replacementRows.length,
    };
  }

  console.log(JSON.stringify(summary, null, 2));
}

main();
