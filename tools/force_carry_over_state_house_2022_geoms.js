/* eslint-disable no-console */
// Force-carry 2022 State House district geometries into the 2024 lines GeoJSON
// for a specific list of districts.
//
// Usage:
//   node tools/force_carry_over_state_house_2022_geoms.js 005 012 070 078 067 051 052 024 025 027

const fs = require('fs');
const path = require('path');

function normalizeDistrictKey(v) {
  const s = String(v ?? '').trim();
  if (!s) return '';
  if (/^\d+$/.test(s)) return s.padStart(3, '0');
  return s;
}

function loadJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function writeJson(filePath, obj) {
  fs.writeFileSync(filePath, JSON.stringify(obj), 'utf8');
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
  const districts = process.argv.slice(2).map(normalizeDistrictKey).filter(Boolean);
  if (!districts.length) {
    console.error('Provide one or more district numbers, e.g. 012 070');
    process.exit(2);
  }

  const root = path.resolve(__dirname, '..');
  const lines2022Path = path.join(root, 'data', 'tileset', 'nc_state_house_2022_lines_tileset.geojson');
  const lines2024Path = path.join(root, 'data', 'tileset', 'nc_state_house_2024_lines_tileset.geojson');

  const gj2022 = loadJson(lines2022Path);
  const gj2024 = loadJson(lines2024Path);
  const by2022 = buildFeatureByDistrict(gj2022);
  const by2024 = buildFeatureByDistrict(gj2024);

  let replaced = 0;
  for (const d of districts) {
    const donor = by2022.get(d);
    const target = by2024.get(d);
    if (!target) {
      console.warn(`[force] Missing in 2024: HD-${d}`);
      continue;
    }
    if (!donor?.geometry) {
      console.warn(`[force] Missing in 2022: HD-${d}`);
      continue;
    }
    target.geometry = donor.geometry;
    replaced++;
  }

  writeJson(lines2024Path, gj2024);
  console.log(`[force] Carried over 2022 geometries for ${replaced}/${districts.length} districts -> ${path.relative(root, lines2024Path)}`);
}

main();

