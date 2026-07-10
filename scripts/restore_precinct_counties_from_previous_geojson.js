/* eslint-disable no-console */
const fs = require('fs');
const path = require('path');
const cp = require('child_process');

function usage() {
  console.error('Usage: node scripts/restore_precinct_counties_from_previous_geojson.js COUNTY [COUNTY ...]');
  process.exit(1);
}

function loadJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function normalizeCounty(value) {
  return String(value || '').trim().toUpperCase();
}

function main() {
  const counties = process.argv.slice(2).map(normalizeCounty).filter(Boolean);
  if (!counties.length) usage();

  const repoRoot = path.resolve(__dirname, '..');
  const geojsonPath = path.join(repoRoot, 'data', 'Voting_Precincts.geojson');
  const current = loadJson(geojsonPath);
  const previousRaw = cp.execFileSync(
    'git',
    ['show', 'HEAD~1:data/Voting_Precincts.geojson'],
    { encoding: 'utf8', maxBuffer: 1024 * 1024 * 200 }
  );
  const previous = JSON.parse(previousRaw);
  const wanted = new Set(counties);

  const currentKeep = [];
  const previousRestore = [];
  const summary = {};

  for (const feature of current.features || []) {
    const county = normalizeCounty(feature?.properties?.county_nam);
    if (wanted.has(county)) continue;
    currentKeep.push(feature);
  }

  for (const county of counties) {
    summary[county] = { removed_current: 0, restored_previous: 0 };
  }

  for (const feature of current.features || []) {
    const county = normalizeCounty(feature?.properties?.county_nam);
    if (!wanted.has(county)) continue;
    summary[county].removed_current += 1;
  }

  for (const feature of previous.features || []) {
    const county = normalizeCounty(feature?.properties?.county_nam);
    if (!wanted.has(county)) continue;
    previousRestore.push(feature);
    summary[county].restored_previous += 1;
  }

  current.features = currentKeep.concat(previousRestore);
  fs.writeFileSync(geojsonPath, JSON.stringify(current));
  console.log(JSON.stringify(summary, null, 2));
}

main();
