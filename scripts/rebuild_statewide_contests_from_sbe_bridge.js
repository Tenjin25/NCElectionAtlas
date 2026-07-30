/* eslint-disable no-console */
/**
 * Rebuild statewide contest JSON slices from OpenElections CSVs through the
 * SBE -> OneMap VAP bridge. Expects bridges already clamped to source county
 * (see scripts/clamp_precinct_bridge_to_source_county.py).
 *
 * Usage:
 *   node scripts/rebuild_statewide_contests_from_sbe_bridge.js
 *   node scripts/rebuild_statewide_contests_from_sbe_bridge.js --years 2000,2002,2004,2008,2010,2012,2014
 *   node scripts/rebuild_statewide_contests_from_sbe_bridge.js --year 2024 president_2024.json
 */
const fs = require('fs');
const path = require('path');

const YEAR_CONFIG = {
  2000: {
    csv: 'data/2000/20001107__nc__general__precinct.csv',
    bridge: 'data/crosswalks/precinct_vtd00_to_onemap_2025_vap.csv',
    source: 'vtd00_to_onemap2025_vap_bridge',
  },
  2002: {
    csv: 'data/2002/20021105__nc__general__precinct.csv',
    bridge: 'data/crosswalks/precinct_vtd00_to_onemap_2025_vap.csv',
    source: 'vtd00_to_onemap2025_vap_bridge',
  },
  2004: {
    csv: 'data/2004/20041102__nc__general__precinct.csv',
    bridge: 'data/crosswalks/precinct_vtd00_to_onemap_2025_vap.csv',
    source: 'vtd00_to_onemap2025_vap_bridge',
  },
  2006: {
    // No dedicated 2006 VAP bridge; OE keys match the 2000/2004 style and pass through
    // like other early statewide slices when unmapped.
    csv: 'data/2006/20061107__nc__general__precinct.csv',
    bridge: 'data/crosswalks/precinct_vtd00_to_onemap_2025_vap.csv',
    source: 'vtd00_to_onemap2025_vap_bridge',
  },
  2008: {
    csv: 'data/2008/20081104__nc__general__precinct.csv',
    bridge: 'data/crosswalks/precinct_vtd10_to_onemap_2025_vap.csv',
    source: 'vtd10_to_onemap2025_vap_bridge',
  },
  2010: {
    csv: 'data/2010/20101102__nc__general__precinct.csv',
    bridge: 'data/crosswalks/precinct_vtd10_to_onemap_2025_vap.csv',
    source: 'vtd10_to_onemap2025_vap_bridge',
  },
  2012: {
    csv: 'data/2012/20121106__nc__general__precinct.csv',
    bridge: 'data/crosswalks/precinct_sbe_2012_to_onemap_2025_vap.csv',
    source: 'sbe2012_to_onemap2025_vap_bridge',
  },
  2014: {
    csv: 'data/2014/20141104__nc__general__precinct.csv',
    bridge: 'data/crosswalks/precinct_sbe_2014_to_onemap_2025_vap.csv',
    source: 'sbe2014_to_onemap2025_vap_bridge',
  },
  2016: {
    csv: 'data/2016/20161108__nc__general__precinct.csv',
    bridge: 'data/crosswalks/precinct_sbe_2016_to_onemap_2025_vap.csv',
    source: 'sbe2016_to_onemap2025_vap_bridge',
  },
  2018: {
    // 2018 has no dedicated SBE bridge; 2020 Dec-2025 bridge is the closest modern match.
    csv: 'data/2018/20181106__nc__general__precinct.csv',
    bridge: 'data/crosswalks/precinct_sbe_2020_to_onemap_2025_12_vap.csv',
    source: 'sbe2020_to_onemap2025_12_vap_bridge',
  },
  2020: {
    csv: 'data/2020/20201103__nc__general__precinct.csv',
    bridge: 'data/crosswalks/precinct_sbe_2020_to_onemap_2025_12_vap.csv',
    source: 'sbe2020_to_onemap2025_12_vap_bridge',
  },
  2022: {
    csv: 'data/2022/20221108__nc__general__precinct.csv',
    bridge: 'data/crosswalks/precinct_sbe_2022_to_onemap_2025_12_vap.csv',
    source: 'sbe2022_to_onemap2025_12_vap_bridge',
  },
  2024: {
    csv: 'data/2024/20241105__nc__general__precinct.csv',
    bridge: 'data/crosswalks/precinct_sbe_2024_to_onemap_2025_12_vap.csv',
    source: 'sbe2024_to_onemap2025_12_vap_bridge',
  },
};

const CONTEST_TYPE_TO_OFFICE_ALIASES = {
  president: [
    'US PRESIDENT',
    'PRESIDENT',
    'PRESIDENT-VICE PRESIDENT',
    'PRESIDENT AND VICE PRESIDENT OF THE UNITED STATES',
  ],
  governor: ['NC GOVERNOR', 'GOVERNOR'],
  lieutenant_governor: ['NC LIEUTENANT GOVERNOR', 'LIEUTENANT GOVERNOR'],
  attorney_general: ['NC ATTORNEY GENERAL', 'ATTORNEY GENERAL'],
  auditor: ['NC AUDITOR', 'AUDITOR'],
  agriculture_commissioner: ['NC COMMISSIONER OF AGRICULTURE', 'COMMISSIONER OF AGRICULTURE'],
  insurance_commissioner: ['NC COMMISSIONER OF INSURANCE', 'COMMISSIONER OF INSURANCE'],
  labor_commissioner: ['NC COMMISSIONER OF LABOR', 'COMMISSIONER OF LABOR'],
  secretary_of_state: ['NC SECRETARY OF STATE', 'SECRETARY OF STATE'],
  superintendent: ['NC SUPERINTENDENT OF PUBLIC INSTRUCTION', 'SUPERINTENDENT OF PUBLIC INSTRUCTION'],
  treasurer: ['NC TREASURER', 'TREASURER'],
  us_senate: ['US SENATE', 'U.S. SENATE', 'UNITED STATES SENATE'],
  nc_supreme_court_chief_justice_seat_01: [
    'NC SUPREME COURT CHIEF JUSTICE SEAT 01',
    'NC SUPREME COURT CHIEF JUSTICE (PARKER)',
    'SUPREME COURT CHIEF JUSTICE',
    'CHIEF JUSTICE NC SUPREME COURT',
  ],
  nc_supreme_court_associate_justice_seat_01: [
    'NC SUPREME COURT ASSOCIATE JUSTICE SEAT 1',
    'NC SUPREME COURT ASSOCIATE JUSTICE SEAT 01',
    'SUPREME COURT (BUTTERFIELD)',
  ],
  nc_supreme_court_associate_justice_seat_02: [
    'NC SUPREME COURT ASSOCIATE JUSTICE SEAT 02',
    'SUPREME COURT (ORR)',
    'SUPREME COURT ASSOCIATE JUSTICE (ORR)',
  ],
  nc_supreme_court_associate_justice_seat_03: [
    'NC SUPREME COURT ASSOCIATE JUSTICE SEAT 03',
    'SUPREME COURT ASSOCIATE JUSTICE (WAINWRIGHT)',
  ],
  nc_supreme_court_associate_justice_seat_04: [
    'NC SUPREME COURT ASSOCIATE JUSTICE SEAT 04',
    'SUPREME COURT ASSOCIATE JUSTICE (PARKER)',
    'SUPREME COURT ASSOCIATE JUSTICE (TIMMONS-GOODSON)',
  ],
  nc_supreme_court_associate_justice_seat_05: [
    'NC SUPREME COURT ASSOCIATE JUSTICE SEAT 05',
    'SUPREME COURT ASSOCIATE JUSTICE (MARTIN)',
  ],
  nc_supreme_court_associate_justice_seat_06: [
    'NC SUPREME COURT ASSOCIATE JUSTICE SEAT 06',
    'ASSOC JUSTICE NC SUPREME COURT',
  ],
  nc_court_of_appeals_judge_seat_01: [
    'NC COURT OF APPEALS JUDGE SEAT 1',
    'NC COURT OF APPEALS JUDGE SEAT 01',
    'CT OF APPEALS JUDGE (WYNN)',
  ],
  nc_court_of_appeals_judge_seat_02: [
    'NC COURT OF APPEALS JUDGE SEAT 2',
    'NC COURT OF APPEALS JUDGE SEAT 02',
    'CT OF APPEALS JUDGE (BRYANT)',
  ],
  nc_court_of_appeals_judge_seat_03: [
    'NC COURT OF APPEALS JUDGE SEAT 3',
    'NC COURT OF APPEALS JUDGE SEAT 03',
    'CT OF APPEALS JUDGE (WALKER)',
  ],
  nc_court_of_appeals_judge_seat_04: [
    'NC COURT OF APPEALS JUDGE SEAT 04',
    'COURT OF APPEALS JUDGE (MCGEE)',
  ],
  nc_court_of_appeals_judge_seat_05: [
    'NC COURT OF APPEALS JUDGE SEAT 05',
    'COURT OF APPEALS JUDGE (BRYANT)',
  ],
  nc_court_of_appeals_judge_seat_06: [
    'NC COURT OF APPEALS JUDGE SEAT 06',
    'COURT OF APPEALS JUDGE (THORNBURG)',
  ],
  nc_court_of_appeals_judge_seat_07: [
    'NC COURT OF APPEALS JUDGE SEAT 07',
    'CT OF APPEALS JUDGE (HORTON)',
  ],
  nc_court_of_appeals_judge_seat_08: [
    'NC COURT OF APPEALS JUDGE SEAT 08',
    'COURT OF APPEALS JUDGE (HUNTER)',
  ],
  nc_court_of_appeals_judge_seat_09: [
    'NC COURT OF APPEALS JUDGE SEAT 09',
    'COURT OF APPEALS JUDGE (STEPHENS)',
  ],
  nc_court_of_appeals_judge_seat_10: [
    'NC COURT OF APPEALS JUDGE SEAT 10',
    'CT OF APPEALS JUDGE (MARTIN)',
  ],
  nc_court_of_appeals_judge_seat_11: [
    'NC COURT OF APPEALS JUDGE SEAT 11',
    'CT OF APPEALS JUDGE (LEWIS)',
  ],
  nc_court_of_appeals_judge_seat_12: [
    'NC COURT OF APPEALS JUDGE SEAT 12',
    'CT OF APPEALS JUDGE (CAMPBELL)',
  ],
  nc_court_of_appeals_judge_seat_13: [
    'NC COURT OF APPEALS JUDGE SEAT 13',
    'CT OF APPEALS JUDGE (JOHN)',
  ],
  nc_court_of_appeals_judge_seat_14: [
    'NC COURT OF APPEALS JUDGE SEAT 14',
    'CT OF APPEALS JUDGE (BIGGS)',
  ],
  nc_court_of_appeals_judge_seat_15: [
    'NC COURT OF APPEALS JUDGE SEAT 15',
    'CT OF APPEALS JUDGE (THOMAS)',
  ],
  // Existing named-seat slices (pre-2018 files); keep aliases for rebuild compatibility.
  nc_supreme_court_associate_justice_edmunds_seat: [
    'NC SUPREME COURT ASSOCIATE JUSTICE',
    'SUPREME COURT ASSOCIATE JUSTICE (EDMUNDS SEAT)',
    'NC SUPREME COURT ASSOCIATE JUSTICE - EDMUNDS SEAT',
    'ASSOC JUSTICE NC SUPREME COURT',
  ],
  nc_supreme_court_associate_justice_brady_seat: [
    'SUPREME COURT ASSOCIATE JUSTICE - BRADY SEAT',
    'NC SUPREME COURT ASSOCIATE JUSTICE - BRADY SEAT',
  ],
  nc_supreme_court_associate_justice_newby_seat: [
    'NC SUPREME COURT ASSOCIATE JUSTICE - NEWBY SEAT',
  ],
  nc_supreme_court_associate_justice_beasley_seat: ['NC SUPREME COURT ASSOCIATE JUSTICE (BEASLEY)'],
  nc_supreme_court_associate_justice_hudson_seat: ['NC SUPREME COURT ASSOCIATE JUSTICE (HUDSON)'],
  nc_supreme_court_associate_justice_martin_seat: [
    'NC SUPREME COURT ASSOCIATE JUSTICE (MARTIN)',
    'SUPREME COURT ASSOCIATE JUSTICE (MARTIN)',
  ],
  nc_supreme_court_chief_justice_parker_seat: [
    'NC SUPREME COURT CHIEF JUSTICE (PARKER)',
    'SUPREME COURT CHIEF JUSTICE',
  ],
  nc_court_of_appeals_judge_dietz_seat: ['NC COURT OF APPEALS JUDGE (DIETZ)'],
  nc_court_of_appeals_judge_geer_seat: [
    'NC COURT OF APPEALS JUDGE (GEER)',
    'COURT OF APPEALS JUDGE - GEER SEAT',
  ],
  nc_court_of_appeals_judge_hunter_seat: [
    'NC COURT OF APPEALS JUDGE (HUNTER)',
    'COURT OF APPEALS JUDGE (HUNTER)',
  ],
  nc_court_of_appeals_judge_stephens_seat: [
    'NC COURT OF APPEALS JUDGE (STEPHENS)',
    'COURT OF APPEALS JUDGE (STEPHENS SEAT)',
  ],
  nc_court_of_appeals_judge_zachary_seat: ['NC COURT OF APPEALS JUDGE (ZACHARY)'],
  nc_court_of_appeals_judge_calabria_seat: [
    'COURT OF APPEALS JUDGE - CALABRIA SEAT',
    'CT OF APPEALS JUDGE (BRYANT)',
  ],
  nc_court_of_appeals_judge_arrowood_seat: ['COURT OF APPEALS JUDGE (ARROWOOD SEAT)'],
  nc_court_of_appeals_judge_mccullough_seat: ['COURT OF APPEALS JUDGE (MCCULLOUGH SEAT)'],
  nc_court_of_appeals_judge_wynn_seat: [
    'COURT OF APPEALS JUDGE (WYNN SEAT)',
    'CT OF APPEALS JUDGE (WYNN)',
  ],
  nc_court_of_appeals_judge_bryant_seat: [
    'NC COURT OF APPEALS JUDGE - BRYANT SEAT',
    'COURT OF APPEALS JUDGE (BRYANT)',
  ],
  nc_court_of_appeals_judge_mcgee_seat: [
    'NC COURT OF APPEALS JUDGE - MCGEE SEAT',
    'COURT OF APPEALS JUDGE (MCGEE)',
  ],
  nc_court_of_appeals_judge_thigpen_seat: ['NC COURT OF APPEALS JUDGE - THIGPEN SEAT'],
  nc_court_of_appeals_judge_davis_seat: ['NC COURT OF APPEALS JUDGE (DAVIS)'],
  nc_court_of_appeals_judge_martin_seat: ['NC COURT OF APPEALS JUDGE (MARTIN)'],
};

// Back-compat single-string map used by older call sites / docs.
const CONTEST_TYPE_TO_OFFICE = Object.fromEntries(
  Object.entries(CONTEST_TYPE_TO_OFFICE_ALIASES).map(([key, aliases]) => [key, aliases[0]])
);

const NON_GEO_FLAGS = [
  'ABS', 'ABSENTEE', 'ABSEN', 'ABS-SUPPLEMENTAL', 'BOE', 'CV', 'EARLYVOTE',
  'PROVISIONAL', 'PROVI', 'PROV', 'PROVSIONAL', 'TRANS', 'CURBSIDE',
  'ONE STOP', 'ONE-STOP', 'EARLY VOT', 'TRANSFER', 'MAIL', 'VOTE CENTER',
  'VOTECENTER', 'ELECTIONS ANNEX',
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
  return String(value || '').trim().toUpperCase().replace(/\s+/g, ' ');
}

function normCandidate(value) {
  return norm(value).replace(/[^A-Z0-9]+/g, ' ').trim();
}

function isDefinitelyNonGeo(precinct) {
  const token = norm(precinct);
  if (!token) return true;
  if (
    token === 'EV' ||
    token.startsWith('EV') ||
    token.startsWith('OS')
  ) return true;
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

function recalcDerived(row, year) {
  const demVotes = numericVote(row.dem_votes);
  const repVotes = numericVote(row.rep_votes);
  const otherVotes = numericVote(row.other_votes);
  const totalVotes = demVotes + repVotes + otherVotes;
  const margin = repVotes - demVotes;
  const marginPct = totalVotes ? Number(((margin / totalVotes) * 100).toFixed(4)) : 0;
  const winner = repVotes > demVotes ? 'REP' : demVotes > repVotes ? 'DEM' : 'TIE';
  return {
    ...row,
    year: Number(year),
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

function emptyBucket(year, county, precinct) {
  return {
    year,
    county: `${county} - ${precinct}`,
    dem_votes: 0,
    rep_votes: 0,
    other_votes: 0,
    dem_candidate: '',
    rep_candidate: '',
  };
}

function partyBucket(party, overrideParty) {
  const p = norm(overrideParty || party);
  if (p.startsWith('DEM')) return 'dem_votes';
  if (p.startsWith('REP')) return 'rep_votes';
  return 'other_votes';
}

function addVotes(bucket, party, votes, candidate, overrideParty) {
  const field = partyBucket(party, overrideParty);
  const v = numericVote(votes);
  bucket[field] += v;
  if (field === 'dem_votes' && !bucket.dem_candidate) bucket.dem_candidate = candidate;
  if (field === 'rep_votes' && !bucket.rep_candidate) bucket.rep_candidate = candidate;
}

function loadBridge(bridgePath) {
  const rows = parseCsv(fs.readFileSync(bridgePath, 'utf8'));
  const bridge = new Map();
  for (const row of rows) {
    const source = norm(row.sbe_precinct_id);
    const target = norm(row.onemap_precinct_id);
    const share = Number.parseFloat(row.share || '0');
    if (!source || !target || !(share > 0)) continue;
    const srcCounty = source.split(' - ')[0];
    const tgtCounty = target.split(' - ')[0];
    if (srcCounty !== tgtCounty) continue; // belt-and-suspenders county clamp
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

function loadJudicialOverrides(repoRoot, year) {
  const csvPath = path.join(repoRoot, 'data', 'mappings', 'judicial_candidate_party_overrides.csv');
  if (!fs.existsSync(csvPath)) return new Map();
  const rows = parseCsv(fs.readFileSync(csvPath, 'utf8'));
  const out = new Map();
  for (const row of rows) {
    if (Number(row.year) !== Number(year)) continue;
    const candidate = normCandidate(row.candidate);
    const party = norm(row.party);
    if (candidate && party) out.set(candidate, party);
  }
  return out;
}

function buildSbeRows(rawRows, office, year, bridge, judicialOverrides) {
  const geoByCounty = new Map();
  const nonGeoByCounty = new Map();

  for (const row of rawRows) {
    if (norm(row.office) !== office) continue;
    const county = norm(row.county);
    const precinct = norm(row.precinct);
    if (!county || !precinct) continue;
    const sourceKey = `${county} - ${precinct}`;
    const isGeo = bridge.has(sourceKey) || !isDefinitelyNonGeo(precinct);
    const targetMap = isGeo ? geoByCounty : nonGeoByCounty;
    if (!targetMap.has(county)) targetMap.set(county, new Map());
    const countyMap = targetMap.get(county);
    if (!countyMap.has(precinct)) countyMap.set(precinct, emptyBucket(year, county, precinct));
    const candidate = String(row.candidate || '').trim();
    const override = judicialOverrides.get(normCandidate(candidate)) || '';
    addVotes(countyMap.get(precinct), norm(row.party), row.votes, candidate, override);
  }

  for (const [county, nonGeoRows] of nonGeoByCounty.entries()) {
    const geoRows = Array.from((geoByCounty.get(county) || new Map()).values());
    if (!geoRows.length) continue;
    for (const voteField of ['dem_votes', 'rep_votes', 'other_votes']) {
      const weights = geoRows.map((row) => numericVote(row[voteField]));
      const fallbackWeights = geoRows.map(
        (row) => numericVote(row.dem_votes) + numericVote(row.rep_votes) + numericVote(row.other_votes)
      );
      for (const nonGeo of nonGeoRows.values()) {
        const votes = numericVote(nonGeo[voteField]);
        if (votes <= 0) continue;
        const alloc = allocateIntegerShares(
          votes,
          weights.some((weight) => weight > 0) ? weights : fallbackWeights
        );
        alloc.forEach((shareVotes, index) => {
          geoRows[index][voteField] += shareVotes;
        });
      }
    }
  }

  return Array.from(geoByCounty.values()).flatMap((countyMap) =>
    Array.from(countyMap.values()).map((row) => recalcDerived(row, year))
  );
}

function bridgeRowsToOneMap(sbeRows, bridge, year) {
  const expanded = [];
  for (const row of sbeRows) {
    const sourceKey = norm(row.county);
    const entries = bridge.get(sourceKey);
    if (!entries || !entries.length) {
      expanded.push(recalcDerived(row, year));
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
      }, year));
    });
  }
  return expanded;
}

function aggregateRows(rows, year) {
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
    byKey.set(key, recalcDerived(existing, year));
  }
  return order.map((key) => recalcDerived(byKey.get(key), year)).sort((a, b) => a.county.localeCompare(b.county));
}

function buildCountyTotals(rawRows, office, judicialOverrides) {
  const totals = new Map();
  let demCandidate = '';
  let repCandidate = '';
  for (const row of rawRows) {
    if (norm(row.office) !== office) continue;
    const county = norm(row.county);
    if (!county) continue;
    if (!totals.has(county)) {
      totals.set(county, {
        dem_votes: 0,
        rep_votes: 0,
        other_votes: 0,
        total_votes: 0,
        dem_candidate: '',
        rep_candidate: '',
      });
    }
    const node = totals.get(county);
    const candidate = String(row.candidate || '').trim();
    const override = judicialOverrides.get(normCandidate(candidate)) || '';
    const field = partyBucket(row.party, override);
    const votes = numericVote(row.votes);
    node[field] += votes;
    node.total_votes += votes;
    if (field === 'dem_votes') {
      if (!node.dem_candidate) node.dem_candidate = candidate;
      if (!demCandidate) demCandidate = candidate;
    }
    if (field === 'rep_votes') {
      if (!node.rep_candidate) node.rep_candidate = candidate;
      if (!repCandidate) repCandidate = candidate;
    }
  }
  const out = {};
  for (const [county, node] of [...totals.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    if (!node.dem_candidate) node.dem_candidate = demCandidate;
    if (!node.rep_candidate) node.rep_candidate = repCandidate;
    const margin = node.rep_votes - node.dem_votes;
    const marginPct = node.total_votes ? Number(((margin / node.total_votes) * 100).toFixed(4)) : 0;
    out[county] = {
      ...node,
      margin,
      margin_pct: marginPct,
      winner: node.rep_votes > node.dem_votes ? 'REP' : node.dem_votes > node.rep_votes ? 'DEM' : 'TIE',
      color: calculateCompetitiveness(marginPct),
    };
  }
  return out;
}

function updateManifestEntry(manifest, fileName, year, contestType, rowCount) {
  const files = Array.isArray(manifest.files) ? manifest.files : [];
  const entry = files.find((row) => row && row.file === fileName);
  if (entry) {
    entry.rows = rowCount;
  } else {
    files.push({ year, contest_type: contestType, file: fileName, rows: rowCount });
    manifest.files = files;
  }
}

function writeTextFileWithRetry(filePath, content, attempts = 12) {
  let lastError = null;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      fs.writeFileSync(filePath, content, 'utf8');
      return;
    } catch (error) {
      lastError = error;
      const retryable = error && ['UNKNOWN', 'EBUSY', 'EPERM', 'EACCES'].includes(error.code);
      if (!retryable || attempt === attempts - 1) throw error;
      const delayMs = 100 * (attempt + 1);
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, delayMs);
    }
  }
  throw lastError;
}

function officeVariants(office) {
  const base = norm(office);
  if (!base) return [];
  const out = new Set([base]);
  // SEAT 01 <-> SEAT 1
  out.add(base.replace(/SEAT 0*(\d+)\b/g, (_, n) => `SEAT ${Number(n)}`));
  out.add(base.replace(/SEAT (\d+)\b/g, (_, n) => `SEAT ${String(Number(n)).padStart(2, '0')}`));
  return [...out];
}

function resolveOfficeName(metaOffice, contestType, rawRows, existingRows = []) {
  const aliasList = CONTEST_TYPE_TO_OFFICE_ALIASES[contestType] || [];
  const candidates = []
    .concat(officeVariants(metaOffice || ''))
    .concat(aliasList.flatMap((alias) => officeVariants(alias)));
  const unique = [...new Set(candidates.filter(Boolean))];
  const present = new Set(rawRows.map((row) => norm(row.office)));
  for (const candidate of unique) {
    if (present.has(candidate)) return candidate;
  }

  // Fall back to candidate-name overlap against OE offices (handles older label drift).
  const wanted = new Set();
  (existingRows || []).forEach((row) => {
    const dem = normCandidate(row?.dem_candidate);
    const rep = normCandidate(row?.rep_candidate);
    if (dem) wanted.add(dem);
    if (rep) wanted.add(rep);
  });
  if (wanted.size) {
    const byOffice = new Map();
    rawRows.forEach((row) => {
      const office = norm(row.office);
      if (!office) return;
      if (!byOffice.has(office)) byOffice.set(office, new Set());
      const cand = normCandidate(row.candidate);
      if (cand) byOffice.get(office).add(cand);
    });
    let best = null;
    byOffice.forEach((names, office) => {
      let overlap = 0;
      wanted.forEach((name) => {
        if (names.has(name)) overlap += 1;
      });
      if (!overlap) return;
      if (!best || overlap > best.overlap || (overlap === best.overlap && names.size < best.size)) {
        best = { office, overlap, size: names.size };
      }
    });
    if (best && best.overlap > 0) return best.office;
  }

  return unique[0] || '';
}

function parseArgs(argv) {
  let years = [];
  const files = [];
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--year') {
      years.push(Number(argv[i + 1]));
      i += 1;
    } else if (arg === '--years') {
      String(argv[i + 1] || '')
        .split(',')
        .map((v) => Number(v.trim()))
        .filter((v) => Number.isFinite(v))
        .forEach((v) => years.push(v));
      i += 1;
    } else if (!arg.startsWith('-')) {
      files.push(path.basename(arg));
    }
  }
  if (!years.length) {
    years = [2000, 2002, 2004, 2008, 2010, 2012, 2014, 2016, 2018, 2020, 2022, 2024];
  }
  return { years: [...new Set(years)], files };
}

function rebuildYear(repoRoot, year, requestedFiles) {
  const yearCfg = YEAR_CONFIG[year];
  if (!yearCfg) {
    throw new Error(`Unsupported year ${year}. Expected one of ${Object.keys(YEAR_CONFIG).join(', ')}`);
  }

  const contestDir = path.join(repoRoot, 'data', 'contests');
  const manifest = JSON.parse(fs.readFileSync(path.join(contestDir, 'manifest.json'), 'utf8'));
  const targets = (manifest.files || []).filter((entry) => (
    entry
    && Number(entry.year) === Number(year)
    && !entry.scope
    && (!requestedFiles.length || requestedFiles.includes(entry.file))
  ));
  // Explicit file arguments may intentionally request a new statewide slice.
  // This keeps the default all-years rebuild conservative while allowing a
  // compact prebuilt payload to replace an expensive browser-side CSV parse.
  if (requestedFiles.length) {
    const existingTargetFiles = new Set(targets.map((entry) => entry.file));
    requestedFiles.forEach((fileName) => {
      const match = /^(.+)_(\d{4})\.json$/i.exec(fileName);
      if (!match || Number(match[2]) !== Number(year) || existingTargetFiles.has(fileName)) return;
      const contestType = match[1];
      if (!CONTEST_TYPE_TO_OFFICE_ALIASES[contestType]) return;
      targets.push({ year, contest_type: contestType, file: fileName });
      existingTargetFiles.add(fileName);
    });
  }

  const csvPath = path.join(repoRoot, yearCfg.csv);
  const bridgePath = path.join(repoRoot, yearCfg.bridge);
  if (!fs.existsSync(csvPath)) {
    return { year, skipped_all: true, reason: `missing_csv:${yearCfg.csv}` };
  }
  if (!fs.existsSync(bridgePath)) {
    return { year, skipped_all: true, reason: `missing_bridge:${yearCfg.bridge}` };
  }

  const rawRows = parseCsv(fs.readFileSync(csvPath, 'utf8'));
  const bridge = loadBridge(bridgePath);
  const judicialOverrides = loadJudicialOverrides(repoRoot, year);
  const summary = {
    year,
    bridge: yearCfg.bridge,
    bridge_keys: bridge.size,
    judicial_override_count: judicialOverrides.size,
    rebuilt: [],
    skipped: [],
  };

  for (const entry of targets) {
    const fileName = entry.file;
    const outPath = path.join(contestDir, fileName);
    const existing = fs.existsSync(outPath)
      ? JSON.parse(fs.readFileSync(outPath, 'utf8'))
      : {
          year,
          contest_type: entry.contest_type,
          meta: {},
          rows: [],
        };
    const contestType = String(existing.contest_type || entry.contest_type || '').trim();
    const office = resolveOfficeName(
      (existing.meta || {}).office,
      contestType,
      rawRows,
      existing.rows || []
    );
    if (!office) {
      summary.skipped.push({ file: fileName, reason: 'missing_meta_office', contest_type: contestType });
      continue;
    }
    const sbeRows = buildSbeRows(rawRows, office, year, bridge, judicialOverrides);
    if (!sbeRows.length) {
      summary.skipped.push({ file: fileName, reason: 'no_office_rows', office });
      continue;
    }
    const oneMapRows = aggregateRows(bridgeRowsToOneMap(sbeRows, bridge, year), year);
    const countyTotals = buildCountyTotals(rawRows, office, judicialOverrides);
    const rawTotals = Object.values(countyTotals).reduce((acc, row) => {
      acc.dem += row.dem_votes;
      acc.rep += row.rep_votes;
      acc.other += row.other_votes;
      acc.total += row.total_votes;
      return acc;
    }, { dem: 0, rep: 0, other: 0, total: 0 });

    const payload = {
      year,
      contest_type: contestType,
      meta: {
        ...(existing.meta || {}),
        source: yearCfg.source,
        office: (existing.meta || {}).office || office,
        nongeo_allocation_mode: 'county_party_geographic_share',
        bridge: yearCfg.bridge,
        bridge_county_clamp: true,
        modern_target_precincts: 'data/census/SBE_PRECINCTS_20251212/SBE_PRECINCTS_20251212.shp',
        display_geojson: 'data/2025Voting_Precincts.geojson',
        dem_total: rawTotals.dem,
        rep_total: rawTotals.rep,
        other_total: rawTotals.other,
        total_votes: rawTotals.total,
        major_party_contested: true,
      },
      county_totals: countyTotals,
      rows: oneMapRows,
    };
    writeTextFileWithRetry(outPath, `${JSON.stringify(payload, null, 2)}\n`);
    updateManifestEntry(manifest, fileName, year, contestType, oneMapRows.length);
    summary.rebuilt.push({
      file: fileName,
      office,
      rows: oneMapRows.length,
      counties: Object.keys(countyTotals).length,
      totals: rawTotals,
    });
  }

  if (summary.rebuilt.length) {
    writeTextFileWithRetry(
      path.join(contestDir, 'manifest.json'),
      `${JSON.stringify(manifest, null, 2)}\n`
    );
  }

  return summary;
}

function main() {
  const repoRoot = path.resolve(__dirname, '..');
  const { years, files: requestedFiles } = parseArgs(process.argv.slice(2));
  const summaries = years.map((year) => rebuildYear(repoRoot, year, requestedFiles));
  console.log(JSON.stringify({
    years,
    totals: {
      rebuilt: summaries.reduce((n, s) => n + ((s.rebuilt && s.rebuilt.length) || 0), 0),
      skipped: summaries.reduce((n, s) => n + ((s.skipped && s.skipped.length) || 0), 0),
    },
    summaries,
  }, null, 2));
}

if (require.main === module) {
  main();
}

module.exports = {
  YEAR_CONFIG,
  CONTEST_TYPE_TO_OFFICE_ALIASES,
  rebuildYear,
  parseArgs,
  updateManifestEntry,
};
