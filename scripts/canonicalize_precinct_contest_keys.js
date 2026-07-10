const fs = require('fs');
const path = require('path');

const COMMON_PRECINCT_WORDS = ['PRECINCT', 'PCT', 'PRCT', 'VTD', 'WARD'];
const NON_GEO_FLAGS = [
  'ABSENTEE',
  'ABSEN',
  'PROVISIONAL',
  'CURBSIDE',
  'ONE STOP',
  'ONE-STOP',
  'EARLY VOT',
  'TRANSFER',
  'MAIL',
  'STOP ',
  'EARLY ',
];

function norm(value) {
  return String(value || '').trim().toUpperCase();
}

function compact(value) {
  return norm(value).replace(/[^A-Z0-9]/g, '');
}

function normalizePrecinctToken(value) {
  let token = norm(value);
  for (const word of COMMON_PRECINCT_WORDS) {
    token = token.replaceAll(word, ' ');
  }
  token = token.replace(/[-_.]/g, ' ').replace(/\s+/g, ' ').trim();
  return token;
}

function normalizeDisplayName(value) {
  const token = norm(value).replace(/[_]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!token) return '';
  return token.replace(/[.]/g, '').replace(/\s+/g, ' ').trim();
}

function isNonGeographicPrecinct(token) {
  const t = norm(token);
  if (!t) return true;
  if (t === 'PROVIDENCE') return false;
  if (t === 'PROVI') return false;
  if (NON_GEO_FLAGS.some(flag => t.includes(flag))) return true;
  return (
    t.startsWith('OS-') ||
    t.startsWith('EV ') ||
    t.startsWith('EV-') ||
    t.startsWith('EV_') ||
    t.includes(' EV ') ||
    t.includes('-EV ') ||
    t.includes('_EV ')
  );
}

function aliasCandidates(rawToken) {
  const token = norm(rawToken);
  const normalized = normalizePrecinctToken(token);
  const out = new Set([token, normalized, compact(token), compact(normalized)]);
  const firstRaw = token.split(/\s+/, 1)[0]?.trim();
  const firstNormalized = normalized.split(/\s+/, 1)[0]?.trim();

  if (firstRaw) {
    out.add(firstRaw);
    out.add(compact(firstRaw));
    out.add(normalizePrecinctToken(firstRaw));
    out.add(compact(normalizePrecinctToken(firstRaw)));
  }
  if (firstNormalized) {
    out.add(firstNormalized);
    out.add(compact(firstNormalized));
  }

  if (token.includes('_')) {
    const [left, right] = token.split(/_(.+)/, 2);
    if (left) out.add(left.trim());
    if (right) {
      out.add(right.trim());
      out.add(compact(right));
    }
  }

  const parts = normalized.split(/\s+/).filter(Boolean);
  if (parts.length > 1) {
    const rest = parts.slice(1).join(' ').trim();
    if (rest) {
      out.add(rest);
      out.add(compact(rest));
    }
    for (let i = 1; i < parts.length; i += 1) {
      const suffix = parts.slice(i).join(' ').trim();
      if (!suffix) continue;
      out.add(suffix);
      out.add(compact(suffix));
    }
  }

  const numeric = token.match(/^0*([0-9]{1,4})([A-Z]?)$/);
  if (numeric) {
    const n = Number(numeric[1]);
    const suffix = numeric[2] || '';
    if (Number.isFinite(n)) {
      out.add(`${n}${suffix}`);
      out.add(`${String(n).padStart(2, '0')}${suffix}`);
      out.add(`${String(n).padStart(3, '0')}${suffix}`);
      out.add(`${String(n).padStart(4, '0')}${suffix}`);
    }
  }

  return Array.from(out).filter(Boolean);
}

function buildFriendlyReverseIndex(payload) {
  const out = new Map();
  const counties = payload?.counties || {};
  for (const [countyRaw, codes] of Object.entries(counties)) {
    const county = norm(countyRaw);
    if (!county || !codes || typeof codes !== 'object') continue;
    const reverse = new Map();
    for (const [codeRaw, nameRaw] of Object.entries(codes)) {
      const code = norm(codeRaw);
      const name = normalizeDisplayName(nameRaw);
      if (!code || !name) continue;
      const aliases = new Set([name, compact(name)]);
      const parts = name.split(/\s+/).filter(Boolean);
      for (let i = 1; i < parts.length; i += 1) {
        const suffix = parts.slice(i).join(' ');
        aliases.add(suffix);
        aliases.add(compact(suffix));
      }
      for (const alias of aliases) {
        if (!alias) continue;
        if (!reverse.has(alias)) {
          reverse.set(alias, code);
        } else if (reverse.get(alias) !== code) {
          reverse.set(alias, null);
        }
      }
    }
    out.set(county, reverse);
  }
  return out;
}

function resolveCanonicalCode(county, rawToken, aliasIndex, friendlyReverse) {
  const countyAliases = aliasIndex.get(county);
  const countyFriendly = friendlyReverse.get(county);
  const token = norm(rawToken);
  if (!county || !token) return '';

  if (countyAliases) {
    for (const candidate of aliasCandidates(token)) {
      const hit = countyAliases.get(candidate);
      if (Array.isArray(hit) && hit.length === 1) return norm(hit[0]);
    }
  }

  if (countyFriendly) {
    for (const candidate of aliasCandidates(token)) {
      const pretty = normalizeDisplayName(candidate);
      if (!pretty) continue;
      const direct = countyFriendly.get(pretty);
      if (direct) return norm(direct);
      const directCompact = countyFriendly.get(compact(pretty));
      if (directCompact) return norm(directCompact);
    }
  }

  return '';
}

function main() {
  const repoRoot = path.resolve(__dirname, '..');
  const contestsDir = path.join(repoRoot, 'data', 'contests');
  const aliasPath = path.join(repoRoot, 'data', 'precinct_alias_index.json');
  const friendlyPath = path.join(repoRoot, 'data', 'precinct_friendly_names.json');

  const aliasPayload = JSON.parse(fs.readFileSync(aliasPath, 'utf8'));
  const aliasIndex = new Map();
  for (const [countyRaw, aliases] of Object.entries(aliasPayload?.counties || {})) {
    aliasIndex.set(norm(countyRaw), new Map(Object.entries(aliases || {}).map(([k, v]) => [norm(k), v])));
  }
  const friendlyReverse = buildFriendlyReverseIndex(JSON.parse(fs.readFileSync(friendlyPath, 'utf8')));

  const files = fs.readdirSync(contestsDir).filter(name => name.endsWith('.json') && name !== 'manifest.json').sort();
  const summary = [];
  let totalChanged = 0;

  for (const fileName of files) {
    const filePath = path.join(contestsDir, fileName);
    const payload = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    const rows = Array.isArray(payload?.rows) ? payload.rows : [];
    let changed = 0;

    for (const row of rows) {
      const rawKey = String(row?.county || '').trim();
      if (!rawKey.includes(' - ')) continue;
      const splitAt = rawKey.indexOf(' - ');
      const county = norm(rawKey.slice(0, splitAt));
      const token = norm(rawKey.slice(splitAt + 3));
      if (!county || !token || isNonGeographicPrecinct(token)) continue;

      const canonical = resolveCanonicalCode(county, token, aliasIndex, friendlyReverse);
      if (!canonical || canonical === token) continue;
      row.county = `${county} - ${canonical}`;
      changed += 1;
    }

    if (changed > 0) {
      rows.sort((a, b) => String(a?.county || '').localeCompare(String(b?.county || '')));
      fs.writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
      totalChanged += changed;
      summary.push({ file: fileName, changed });
    }
  }

  console.log(JSON.stringify({ files_changed: summary.length, rows_changed: totalChanged, updated: summary.slice(0, 40) }, null, 2));
}

main();
