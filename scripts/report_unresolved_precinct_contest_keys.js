const fs = require('fs');
const path = require('path');

function norm(value) {
  return String(value || '').trim().toUpperCase();
}

function buildCanonicalKeySet() {
  const payload = JSON.parse(fs.readFileSync(path.join('data', 'Voting_Precincts.geojson'), 'utf8'));
  const out = new Set();
  for (const feature of (payload.features || [])) {
    const props = feature.properties || {};
    const county = norm(props.county_nam);
    const prec = norm(props.prec_id);
    if (county && prec) out.add(`${county} - ${prec}`);
  }
  return out;
}

function isDefinitelyNonGeo(token) {
  const t = norm(token);
  return [
    'ABSENTEE',
    'ONE STOP',
    'PROVISIONAL',
    'ABSENTEE BY MAIL',
    'TRANSFER',
    'CURBSIDE',
    'EARLY',
    'OS ',
    'EV ',
  ].some(flag => t.includes(flag)) || t.startsWith('OS-') || t.startsWith('EV-') || t.startsWith('EV_');
}

function main() {
  const canonical = buildCanonicalKeySet();
  const contestsDir = path.join('data', 'contests');
  const files = fs.readdirSync(contestsDir).filter(name => name.endsWith('.json') && name !== 'manifest.json').sort();
  const counts = new Map();
  const filesByKey = new Map();

  for (const fileName of files) {
    const payload = JSON.parse(fs.readFileSync(path.join(contestsDir, fileName), 'utf8'));
    for (const row of (payload.rows || [])) {
      const key = norm(row.county);
      if (!key || canonical.has(key) || !key.includes(' - ')) continue;
      const token = key.split(/ - (.+)/, 2)[1] || '';
      if (isDefinitelyNonGeo(token)) continue;
      counts.set(key, (counts.get(key) || 0) + 1);
      if (!filesByKey.has(key)) filesByKey.set(key, new Set());
      filesByKey.get(key).add(fileName);
    }
  }

  const rows = Array.from(counts.entries())
    .map(([key, count]) => ({
      key,
      count,
      files: Array.from(filesByKey.get(key) || []).sort().slice(0, 8),
    }))
    .sort((a, b) => b.count - a.count || a.key.localeCompare(b.key));

  console.log(JSON.stringify({
    unresolved_key_count: rows.length,
    top_unresolved: rows.slice(0, 120),
  }, null, 2));
}

main();
