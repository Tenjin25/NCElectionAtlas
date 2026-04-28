/* eslint-disable no-console */
// Carry over unchanged NC legislative district geometries from 2022 lines into
// the 2024 lines GeoJSON (State House and/or State Senate).
//
// Goal: if a district did not change between plans, reuse the 2022 geometry
// exactly (helps avoid subtle processing/simplification diffs across sources).
//
// "Unchanged" detection: compares the set of precinct keys whose PRIMARY
// assignment (max area_weight) maps to that district in:
//   - data/crosswalks/precinct_to_2022_state_house.csv vs precinct_to_2024_state_house.csv
//   - data/crosswalks/precinct_to_2022_state_senate.csv vs precinct_to_2024_state_senate.csv
//
// Usage:
//   node tools/carry_over_unchanged_legislative_lines_2022_to_2024.js
//   node tools/carry_over_unchanged_legislative_lines_2022_to_2024.js --scope house
//   node tools/carry_over_unchanged_legislative_lines_2022_to_2024.js --scope senate
//   node tools/carry_over_unchanged_legislative_lines_2022_to_2024.js --exclude house:012,070 senate:026
//
// Output (in-place):
//   data/tileset/nc_state_house_2024_lines_tileset.geojson
//   data/tileset/nc_state_senate_2024_lines_tileset.geojson
//
// Notes:
// - This never touches districts flagged as changed by the crosswalk set compare.
// - Uses string district keys with leading zeros (e.g. "012").

const fs = require('fs');
const path = require('path');

function readText(filePath) {
  return fs.readFileSync(filePath, 'utf8');
}

function writeText(filePath, text) {
  fs.writeFileSync(filePath, text, 'utf8');
}

function parseSimpleCSV(text) {
  const lines = text.split(/\r?\n/).filter(Boolean);
  if (!lines.length) return { header: [], rows: [] };
  const header = lines[0].split(',').map(s => s.trim());
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(',');
    if (cols.length < header.length) continue;
    const row = {};
    for (let j = 0; j < header.length; j++) row[header[j]] = cols[j];
    rows.push(row);
  }
  return { header, rows };
}

function normalizeDistrictKey(v) {
  const s = String(v ?? '').trim();
  if (!s) return '';
  if (/^\d+$/.test(s)) return s.padStart(3, '0');
  return s;
}

function buildPrimaryDistrictByPrecinct(crosswalkCsvPath) {
  const csv = parseSimpleCSV(readText(crosswalkCsvPath));
  const precinctKeyCol = csv.header.includes('precinct_key') ? 'precinct_key' : null;
  const districtCol = csv.header.includes('district') ? 'district' : (csv.header.includes('district_code') ? 'district_code' : null);
  const weightCol = csv.header.includes('area_weight') ? 'area_weight' : null;
  if (!precinctKeyCol || !districtCol) {
    throw new Error(`Unexpected crosswalk schema in ${crosswalkCsvPath}`);
  }

  const best = new Map(); // precinct_key -> { district, weight }
  for (const row of csv.rows) {
    const precinctKey = String(row[precinctKeyCol] || '').trim();
    if (!precinctKey) continue;
    const district = normalizeDistrictKey(row[districtCol]);
    if (!district) continue;
    const weight = weightCol ? Number(row[weightCol]) : 1;
    const prev = best.get(precinctKey);
    if (!prev || (Number.isFinite(weight) && weight > prev.weight)) {
      best.set(precinctKey, { district, weight: Number.isFinite(weight) ? weight : 0 });
    }
  }
  return best;
}

function invertPrecinctMap(precinctToDistrict) {
  const byDistrict = new Map(); // district -> Set(precinct_key)
  precinctToDistrict.forEach((v, precinctKey) => {
    const d = v?.district;
    if (!d) return;
    if (!byDistrict.has(d)) byDistrict.set(d, new Set());
    byDistrict.get(d).add(precinctKey);
  });
  return byDistrict;
}

function setsEqual(a, b) {
  if (!a || !b) return false;
  if (a.size !== b.size) return false;
  for (const v of a) if (!b.has(v)) return false;
  return true;
}

function loadGeoJSON(filePath) {
  return JSON.parse(readText(filePath));
}

function buildFeatureByDistrict(geojson) {
  const map = new Map();
  const feats = Array.isArray(geojson?.features) ? geojson.features : [];
  for (const f of feats) {
    const d = normalizeDistrictKey(f?.properties?.DISTRICT ?? f?.properties?.SLDLST ?? '');
    if (!d) continue;
    map.set(d, f);
  }
  return map;
}

function parseExcludeArg(tokens) {
  // tokens like: ["house:012,070", "senate:026"]
  const out = { house: new Set(), senate: new Set() };
  for (const t of tokens) {
    const raw = String(t || '').trim();
    if (!raw) continue;
    const [scopeRaw, listRaw] = raw.includes(':') ? raw.split(':', 2) : ['', raw];
    const scope = scopeRaw.trim().toLowerCase();
    const list = (listRaw || '').split(',').map(s => normalizeDistrictKey(s)).filter(Boolean);
    if (scope === 'house') list.forEach(d => out.house.add(d));
    else if (scope === 'senate') list.forEach(d => out.senate.add(d));
    else list.forEach(d => { out.house.add(d); out.senate.add(d); });
  }
  return out;
}

function carryOverScope(root, scopeKey, excludes) {
  const cfg = scopeKey === 'house'
    ? {
        label: 'State House',
        cross22: path.join(root, 'data', 'crosswalks', 'precinct_to_2022_state_house.csv'),
        cross24: path.join(root, 'data', 'crosswalks', 'precinct_to_2024_state_house.csv'),
        lines22: path.join(root, 'data', 'tileset', 'nc_state_house_2022_lines_tileset.geojson'),
        lines24: path.join(root, 'data', 'tileset', 'nc_state_house_2024_lines_tileset.geojson'),
      }
    : {
        label: 'State Senate',
        cross22: path.join(root, 'data', 'crosswalks', 'precinct_to_2022_state_senate.csv'),
        cross24: path.join(root, 'data', 'crosswalks', 'precinct_to_2024_state_senate.csv'),
        lines22: path.join(root, 'data', 'tileset', 'nc_state_senate_2022_lines_tileset.geojson'),
        lines24: path.join(root, 'data', 'tileset', 'nc_state_senate_2024_lines_tileset.geojson'),
      };

  const primary22 = buildPrimaryDistrictByPrecinct(cfg.cross22);
  const primary24 = buildPrimaryDistrictByPrecinct(cfg.cross24);
  const precinctsByD22 = invertPrecinctMap(primary22);
  const precinctsByD24 = invertPrecinctMap(primary24);

  const unchanged = [];
  precinctsByD22.forEach((set22, district) => {
    const set24 = precinctsByD24.get(district);
    if (!set24) return;
    if (!setsEqual(set22, set24)) return;
    if (excludes.has(district)) return;
    unchanged.push(district);
  });
  unchanged.sort((a, b) => Number(a) - Number(b));

  console.log(`[carry-over] ${cfg.label}: unchanged districts detected: ${unchanged.length}`);

  const gj22 = loadGeoJSON(cfg.lines22);
  const gj24 = loadGeoJSON(cfg.lines24);
  const by22 = buildFeatureByDistrict(gj22);
  const by24 = buildFeatureByDistrict(gj24);

  let replaced = 0;
  for (const d of unchanged) {
    const donor = by22.get(d);
    const target = by24.get(d);
    if (!donor?.geometry || !target) continue;
    target.geometry = donor.geometry;
    replaced++;
  }

  writeText(cfg.lines24, JSON.stringify(gj24));
  console.log(`[carry-over] ${cfg.label}: geometries replaced: ${replaced}/${unchanged.length}`);
  console.log(`[carry-over] Wrote ${path.relative(root, cfg.lines24)}`);
}

function main() {
  const root = path.resolve(__dirname, '..');
  const args = process.argv.slice(2);
  const scopeIdx = args.indexOf('--scope');
  const scope = scopeIdx >= 0 ? String(args[scopeIdx + 1] || '').trim().toLowerCase() : 'both';
  const excludeIdx = args.indexOf('--exclude');
  const excludeTokens = excludeIdx >= 0 ? args.slice(excludeIdx + 1).filter(t => !String(t).startsWith('--')) : [];
  const excludes = parseExcludeArg(excludeTokens);

  const doHouse = scope === 'both' || scope === 'house';
  const doSenate = scope === 'both' || scope === 'senate';
  if (!doHouse && !doSenate) {
    console.error('Invalid --scope. Use: house | senate | both');
    process.exit(2);
  }

  if (doHouse) carryOverScope(root, 'house', excludes.house);
  if (doSenate) carryOverScope(root, 'senate', excludes.senate);
}

main();

