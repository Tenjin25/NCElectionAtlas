/* eslint-disable no-console */
// Carry over unchanged NC State House district geometries from 2022 lines into
// the 2024 lines GeoJSON, based on precinct crosswalk stability.
//
// Why: some districts did not change between the 2022 and 2024 plans, but the
// 2024 geometry source may differ slightly (simplification / processing drift).
// For unchanged districts, reuse the 2022 geometry exactly for perfect visual
// alignment and stable hover/outline behavior.
//
// Usage (from repo root):
//   node tools/carry_over_state_house_2022_lines_to_2024.js
//
// Inputs:
//   data/crosswalks/precinct_to_2022_state_house.csv
//   data/crosswalks/precinct_to_2024_state_house.csv
//   data/tileset/nc_state_house_2022_lines_tileset.geojson
//   data/tileset/nc_state_house_2024_lines_tileset.geojson
//
// Output (in-place):
//   data/tileset/nc_state_house_2024_lines_tileset.geojson
//
// Note: This script treats a precinct's "primary" district as the one with the
// largest `area_weight` in the crosswalk.

const fs = require('fs');
const path = require('path');

function readText(filePath) {
  return fs.readFileSync(filePath, 'utf8');
}

function writeText(filePath, text) {
  fs.writeFileSync(filePath, text, 'utf8');
}

function parseSimpleCSV(text) {
  // This dataset is "simple" CSV: no embedded newlines; commas can exist only
  // as separators. `district_name` contains spaces but no commas in our files.
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
  // Keep leading zeros for matching DISTRICT like "012".
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

function main() {
  const root = path.resolve(__dirname, '..');
  const crosswalk2022 = path.join(root, 'data', 'crosswalks', 'precinct_to_2022_state_house.csv');
  const crosswalk2024 = path.join(root, 'data', 'crosswalks', 'precinct_to_2024_state_house.csv');
  const lines2022Path = path.join(root, 'data', 'tileset', 'nc_state_house_2022_lines_tileset.geojson');
  const lines2024Path = path.join(root, 'data', 'tileset', 'nc_state_house_2024_lines_tileset.geojson');

  const primary2022 = buildPrimaryDistrictByPrecinct(crosswalk2022);
  const primary2024 = buildPrimaryDistrictByPrecinct(crosswalk2024);

  const precinctsByD2022 = invertPrecinctMap(primary2022);
  const precinctsByD2024 = invertPrecinctMap(primary2024);

  const unchanged = [];
  precinctsByD2022.forEach((set2022, district) => {
    const set2024 = precinctsByD2024.get(district);
    if (!set2024) return;
    if (setsEqual(set2022, set2024)) unchanged.push(district);
  });

  unchanged.sort((a, b) => Number(a) - Number(b));
  console.log(`[carry-over] Unchanged districts detected: ${unchanged.length}`);
  if (unchanged.includes('012')) console.log('[carry-over] Includes HD-012');

  const gj2022 = loadGeoJSON(lines2022Path);
  const gj2024 = loadGeoJSON(lines2024Path);
  const f2022 = buildFeatureByDistrict(gj2022);

  let replaced = 0;
  const feats2024 = Array.isArray(gj2024?.features) ? gj2024.features : [];
  for (const f of feats2024) {
    const district = normalizeDistrictKey(f?.properties?.DISTRICT ?? f?.properties?.SLDLST ?? '');
    if (!district) continue;
    if (!unchanged.includes(district)) continue;
    const donor = f2022.get(district);
    if (!donor?.geometry) continue;
    f.geometry = donor.geometry;
    replaced++;
  }

  console.log(`[carry-over] Replaced geometries: ${replaced}`);
  if (!replaced) {
    console.log('[carry-over] No changes made.');
    return;
  }

  writeText(lines2024Path, JSON.stringify(gj2024));
  console.log(`[carry-over] Wrote ${path.relative(root, lines2024Path)}`);
}

main();

