#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const OUTPUT = path.join(ROOT, 'data', 'reports', '2020_to_2026_us_senate_shift_scale_breakers.md');
const SCALE_CEILING = 25;
const FULL_COUNTY_THRESHOLD = 0.999;
const MATERIAL_PARTIAL_THRESHOLD = 0.001;
const CANDIDATES = {
  2020: { dem: 'Cunningham', rep: 'Tillis' },
  2026: { dem: 'Cooper', rep: 'Whatley' }
};

const views = [
  { title: 'Counties', kind: 'county' },
  { title: 'Congressional districts — 2022 lines', dir: 'district_contests', scope: 'congressional', prefix: 'CD', crosswalk: 'precinct_to_cd118.csv' },
  { title: 'Congressional districts — 2024 lines', dir: 'district_contests_2024_lines', scope: 'congressional', prefix: 'CD', crosswalk: 'precinct_to_cd119.csv' },
  { title: 'Congressional districts — 2026 lines', dir: 'district_contests_2026_lines', scope: 'congressional', prefix: 'CD', crosswalk: 'precinct_to_cd2026_sl2025_95.csv' },
  { title: 'State House districts — 2022 lines', dir: 'district_contests', scope: 'state_house', prefix: 'HD', crosswalk: 'precinct_to_2022_state_house.csv', componentPlan: '2022_state_house' },
  { title: 'State House districts — 2024 lines', dir: 'district_contests_2024_lines', scope: 'state_house', prefix: 'HD', crosswalk: 'precinct_to_2024_state_house.csv', componentPlan: '2024_state_house' },
  { title: 'State Senate districts — 2022 lines', dir: 'district_contests', scope: 'state_senate', prefix: 'SD', crosswalk: 'precinct_to_2022_state_senate.csv', componentPlan: '2022_state_senate' },
  { title: 'State Senate districts — 2024 lines', dir: 'district_contests_2024_lines', scope: 'state_senate', prefix: 'SD', crosswalk: 'precinct_to_2024_state_senate.csv', componentPlan: '2024_state_senate' }
];

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

const HUMAN_LOCATIONS = readJson(
  path.join(ROOT, 'data', 'mappings', 'district_location_labels.json')
).plans;

function resultMap(view, year) {
  if (view.kind === 'county') {
    return readJson(path.join(ROOT, 'data', 'contests', `us_senate_${year}.json`)).county_totals;
  }
  const file = path.join(ROOT, 'data', view.dir, `${view.scope}_us_senate_${year}.json`);
  return readJson(file).general.results;
}

function labelArea(view, key) {
  if (view.kind === 'county') {
    return key.toLowerCase().replace(/\b\w/g, char => char.toUpperCase());
  }
  return `${view.prefix}-${key}`;
}

function formatCandidateMargin(value, year) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  if (Math.abs(n) < 0.005) return 'Even';
  const candidate = n > 0 ? CANDIDATES[year].rep : CANDIDATES[year].dem;
  return `${candidate} +${Math.abs(n).toFixed(2)}`;
}

function formatShift(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `${n > 0 ? 'R' : 'D'}+${Math.abs(n).toFixed(2)}`;
}

function numericKey(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : Number.MAX_SAFE_INTEGER;
}

function parseCsvLine(line) {
  const cells = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === '"') {
      if (quoted && line[i + 1] === '"') {
        cell += '"';
        i += 1;
      } else {
        quoted = !quoted;
      }
    } else if (char === ',' && !quoted) {
      cells.push(cell);
      cell = '';
    } else {
      cell += char;
    }
  }
  cells.push(cell);
  return cells;
}

function normalizeDistrict(value) {
  const n = Number(value);
  return Number.isFinite(n) ? String(Math.trunc(n)) : String(value || '').trim();
}

function titleCounty(value) {
  return value.toLowerCase().replace(/\b\w/g, char => char.toUpperCase());
}

function districtLocations(view) {
  if (!view.crosswalk) return {};
  const file = path.join(ROOT, 'data', 'crosswalks', view.crosswalk);
  const lines = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '').split(/\r?\n/).filter(Boolean);
  const header = parseCsvLine(lines.shift());
  const precinctIndex = header.indexOf('precinct_key');
  const districtIndex = header.indexOf('district');
  const weightIndex = header.indexOf('area_weight');
  if (precinctIndex < 0 || districtIndex < 0 || weightIndex < 0) {
    throw new Error(`Missing location columns in ${view.crosswalk}`);
  }

  const precinctsByCounty = new Map();
  const massByCountyDistrict = new Map();
  for (const line of lines) {
    const cells = parseCsvLine(line);
    const precinct = String(cells[precinctIndex] || '').trim().toUpperCase();
    if (!precinct.includes(' - ')) continue;
    const county = precinct.split(' - ', 1)[0];
    const district = normalizeDistrict(cells[districtIndex]);
    const weight = Number(cells[weightIndex]);
    if (!district || !Number.isFinite(weight)) continue;
    if (!precinctsByCounty.has(county)) precinctsByCounty.set(county, new Set());
    precinctsByCounty.get(county).add(precinct);
    const massKey = `${county}\t${district}`;
    massByCountyDistrict.set(massKey, (massByCountyDistrict.get(massKey) || 0) + weight);
  }

  const components = {};
  for (const [massKey, mass] of massByCountyDistrict) {
    const [county, district] = massKey.split('\t');
    const denominator = precinctsByCounty.get(county)?.size || 0;
    const share = denominator ? mass / denominator : 0;
    if (share <= MATERIAL_PARTIAL_THRESHOLD) continue;
    if (!components[district]) components[district] = { whole: [], partial: [] };
    const bucket = share >= FULL_COUNTY_THRESHOLD ? 'whole' : 'partial';
    components[district][bucket].push(county);
  }

  for (const component of Object.values(components)) {
    component.whole.sort();
    component.partial.sort();
  }
  return components;
}

function validateLegislativeComponents(view, components) {
  if (!view.componentPlan) return;
  const catalog = readJson(path.join(ROOT, 'data', 'mappings', 'mixed_county_components.json'));
  const expected = catalog.plans?.[view.componentPlan];
  if (!expected) throw new Error(`Missing component catalog plan ${view.componentPlan}`);
  for (const [district, whole] of Object.entries(expected.exact_components || {})) {
    const partial = expected.allocated_components?.[district] || [];
    const actual = components[district] || { whole: [], partial: [] };
    if (JSON.stringify(actual.whole) !== JSON.stringify(whole) || JSON.stringify(actual.partial) !== JSON.stringify(partial)) {
      throw new Error(`BEF component mismatch for ${view.componentPlan} district ${district}`);
    }
  }
}

function joinPlaces(values) {
  if (values.length < 2) return values[0] || '';
  if (values.length === 2) return `${values[0]} and ${values[1]}`;
  return `${values.slice(0, -1).join(', ')}, and ${values.at(-1)}`;
}

function formatLocation(view, district, component) {
  const humanLabel = HUMAN_LOCATIONS?.[view.crosswalk]?.[district];
  if (humanLabel) return humanLabel;
  if (!component) return '—';
  const whole = component.whole.map(titleCounty);
  const partial = component.partial.map(titleCounty);
  if (!whole.length) return joinPlaces(partial) || '—';
  if (!partial.length) return joinPlaces(whole) || '—';
  return `${joinPlaces(whole)}; parts of ${joinPlaces(partial)}`;
}

const analyzed = views.map(view => {
  const prior = resultMap(view, 2020);
  const current = resultMap(view, 2026);
  const locations = districtLocations(view);
  validateLegislativeComponents(view, locations);
  const keys = [...new Set([...Object.keys(prior || {}), ...Object.keys(current || {})])];
  const rows = keys.map(key => {
    const margin2020 = Number(prior?.[key]?.margin_pct);
    const margin2026 = Number(current?.[key]?.margin_pct);
    const shift = margin2026 - margin2020;
    return { key, area: labelArea(view, key), location: formatLocation(view, key, locations[key]), margin2020, margin2026, shift };
  }).filter(row => Number.isFinite(row.shift) && Math.abs(row.shift) >= SCALE_CEILING);

  rows.sort((a, b) => view.kind === 'county'
    ? a.area.localeCompare(b.area)
    : numericKey(a.key) - numericKey(b.key));

  return { ...view, rows };
});

const out = [];
out.push('# 2020→2026 U.S. Senate shift-scale breakers');
out.push('');
out.push('These are the areas where the NCSBE-reported 2026 U.S. Senate R−D margin moved **25.00 points or more** from the 2020 U.S. Senate margin. That is the ceiling of the atlas shift legend’s “Extreme — 25+ pts” bucket. Election margins use candidate surnames: Cunningham/Tillis in 2020 and Cooper/Whatley in 2026. The shift itself uses partisan notation, so `D+26.26` means the margin moved 26.26 points toward the Democratic candidate. Other-party votes remain in each margin’s denominator, matching the atlas.');
out.push('');
out.push('The 2026 figures use the complete 100-county NCSBE precinct posting from November 11, 2026, 4:00:44 p.m. ET. All counties had reported provisional votes, but the results remained unofficial pending the statewide canvass.');
out.push('');
out.push('The report covers counties; congressional districts under the 2022, 2024, and 2026 line sets; and State House and State Senate districts under the 2022 and 2024 line sets.');
out.push('');
out.push('District locations are plain-language descriptions derived from the official BEF precinct crosswalks used by the election aggregation. County membership follows the project’s ≥99.9% whole-county and >0.1% material-component rules; “most” means at least 55% of county area. Directional descriptions use the district’s position within each county. The generator validates legislative mixed districts against `data/mappings/mixed_county_components.json` before writing the report.');
out.push('');
out.push('## Summary');
out.push('');
out.push('| Geography | Areas beyond the shift scale | Toward Democrats | Toward Republicans |');
out.push('|---|---:|---:|---:|');
for (const view of analyzed) {
  const dem = view.rows.filter(row => row.shift < 0).length;
  const rep = view.rows.filter(row => row.shift > 0).length;
  out.push(`| ${view.title} | ${view.rows.length} | ${dem} | ${rep} |`);
}

for (const view of analyzed) {
  out.push('');
  out.push(`## ${view.title}`);
  out.push('');
  if (!view.rows.length) {
    out.push('_No areas moved 25 points or more._');
    continue;
  }
  const districtView = view.kind !== 'county';
  out.push(districtView
    ? '| Area | Location | 2020 margin | 2026 margin | Shift |'
    : '| Area | 2020 margin | 2026 margin | Shift |');
  out.push(districtView ? '|---|---|---:|---:|---:|' : '|---|---:|---:|---:|');
  for (const row of view.rows) {
    out.push(districtView
      ? `| ${row.area} | ${row.location} | ${formatCandidateMargin(row.margin2020, 2020)} | ${formatCandidateMargin(row.margin2026, 2026)} | ${formatShift(row.shift)} |`
      : `| ${row.area} | ${formatCandidateMargin(row.margin2020, 2020)} | ${formatCandidateMargin(row.margin2026, 2026)} | ${formatShift(row.shift)} |`);
  }
}

out.push('');
out.push('## Source');
out.push('');
out.push('Generated from `data/contests/us_senate_2020.json`, the complete-county provisional `data/contests/us_senate_2026.json`, the matching district aggregations, the BEF-derived `data/crosswalks/precinct_to_*.csv` files, and `data/mappings/district_location_labels.json`. Legislative component labels are checked against `data/mappings/mixed_county_components.json`.');
out.push('');
out.push('The underlying official assignments are `37_NC_CD118.txt`, `37_NC_CD119.txt`, `CD120_37.txt`, `37_NC_SLDL22.txt`, `37_NC_SLDL24.txt`, `37_NC_SLDU22.txt`, and `37_NC_SLDU24.txt`.');
out.push('');

fs.writeFileSync(OUTPUT, out.join('\n'), 'utf8');
console.log(`Wrote ${path.relative(ROOT, OUTPUT)} with ${analyzed.reduce((sum, view) => sum + view.rows.length, 0)} geography rows.`);
