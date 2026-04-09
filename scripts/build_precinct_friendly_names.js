/* eslint-disable no-console */
const fs = require('fs');
const path = require('path');

function toTitleCaseName(raw) {
  const s = String(raw || '').trim().toLowerCase();
  if (!s) return '';
  return s.replace(/\b([a-z])/g, (m, c) => c.toUpperCase());
}

function normalizeAliasNameCandidate(raw) {
  const s = String(raw || '').trim().toUpperCase();
  if (!s) return '';
  const cleaned = s.replace(/[_]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!cleaned) return '';
  if (/VOTING\s*DISTRICT/i.test(cleaned)) return '';
  if (/^\d+$/.test(cleaned)) return '';
  return cleaned;
}

function isCodeLikeToken(raw) {
  const s = String(raw || '').trim().toUpperCase();
  if (!s) return true;
  const compact = s.replace(/[^A-Z0-9]/g, '');
  if (!compact) return true;
  // Alias keys that include digits are almost always codes, not names (EH1, 0001, 00CRDM).
  if (/[0-9]/.test(compact)) return true;
  // Short all-letter tokens are usually precinct codes (CRDM, BCK), not display names.
  if (compact.length <= 4 && /^[A-Z]+$/.test(compact)) return true;
  return false;
}

function scoreNameCandidate(raw) {
  const s = normalizeAliasNameCandidate(raw);
  if (!s) return -1e9;
  const letters = (s.match(/[A-Z]/g) || []).length;
  const digits = (s.match(/[0-9]/g) || []).length;
  const spaces = (s.match(/\s/g) || []).length;
  let score = 0;
  score += letters * 2.2;
  score -= digits * 3.5;
  score += spaces * 1.0;
  score += Math.min(24, s.length);
  if (/VOTING\s*DISTRICT/i.test(s)) score -= 1000;
  if (/^(EARLY|ABSENTEE|PROVISIONAL|ONE\s+STOP|MAIL)/i.test(s)) score -= 20;
  return score;
}

function extractNameFromAlias(aliasRaw, codeRaw) {
  const alias = String(aliasRaw || '').trim().toUpperCase();
  const code = String(codeRaw || '').trim().toUpperCase();
  if (!alias || !code) return '';
  if (alias === code) return '';

  let rest = '';
  if (alias.startsWith(code)) {
    rest = alias.slice(code.length).trim();
    rest = rest.replace(/^[_\s]+/, '').trim();
  }
  if (!rest) return '';
  rest = rest.replace(/[_]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!rest) return '';
  if (/VOTING\s*DISTRICT/i.test(rest)) return '';

  const codeCompact = code.replace(/[^A-Z0-9]/g, '');
  const restCompact = rest.replace(/[^A-Z0-9]/g, '');
  if (restCompact === codeCompact) return '';
  if (restCompact.endsWith(codeCompact) && restCompact.length <= codeCompact.length + 2) return '';

  // Avoid returning another compact code token. Allow digits/spaces in real names (e.g. "LEXINGTON 1 22").
  if (!/\s/.test(rest)) {
    const compactOnly = rest.replace(/[^A-Z0-9]/g, '');
    if (compactOnly.length <= 6 && /^[A-Z0-9]+$/.test(compactOnly)) return '';
  }
  const cleaned = normalizeAliasNameCandidate(rest);
  if (!cleaned) return '';
  return cleaned;
}

function setBestNameForCode(perCounty, code, nameCandidate) {
  if (!perCounty || !code || !nameCandidate) return;
  const cand = normalizeAliasNameCandidate(nameCandidate);
  if (!cand) return;
  const prev = perCounty.get(code) || '';
  if (!prev) {
    perCounty.set(code, cand);
    return;
  }
  const prevScore = scoreNameCandidate(prev);
  const candScore = scoreNameCandidate(cand);
  if (candScore > prevScore + 1e-6) {
    perCounty.set(code, cand);
    return;
  }
  if (Math.abs(candScore - prevScore) < 1e-6 && cand.length > prev.length) {
    perCounty.set(code, cand);
  }
}

function buildFriendlyNamesIndex(aliasIndexPayload) {
  const counties = aliasIndexPayload?.counties || {};
  const out = {};

  for (const [countyRaw, aliasObj] of Object.entries(counties)) {
    if (!aliasObj || typeof aliasObj !== 'object') continue;
    const perCounty = new Map();

    for (const [aliasRaw, codesRaw] of Object.entries(aliasObj)) {
      const alias = String(aliasRaw || '').trim().toUpperCase();
      const codes = Array.isArray(codesRaw)
        ? Array.from(new Set(codesRaw.map(v => String(v || '').trim().toUpperCase()).filter(Boolean)))
        : [];
      if (!alias || !codes.length) continue;

      for (const code of codes) {
        const extracted = extractNameFromAlias(alias, code);
        if (extracted) {
          setBestNameForCode(perCounty, code, extracted);
          continue;
        }
        // Only treat an alias key as a "name-only" label when it *doesn't* start with the code token.
        // This avoids bad picks like "ANTI 00ANTI" becoming a "name" for code "ANTI".
        if (codes.length === 1 && !isCodeLikeToken(alias) && !alias.startsWith(String(code || '').trim().toUpperCase())) {
          setBestNameForCode(perCounty, code, alias);
        }
      }
    }

    if (!perCounty.size) continue;
    const outCounty = {};
    for (const [code, name] of perCounty.entries()) {
      outCounty[code] = toTitleCaseName(name);
    }
    out[countyRaw] = outCounty;
  }

  return out;
}

function main() {
  const repoRoot = path.resolve(__dirname, '..');
  const inputPath = process.argv[2]
    ? path.resolve(process.argv[2])
    : path.join(repoRoot, 'data', 'precinct_alias_index.json');
  const outputPath = process.argv[3]
    ? path.resolve(process.argv[3])
    : path.join(repoRoot, 'data', 'precinct_friendly_names.json');

  const payload = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
  const counties = buildFriendlyNamesIndex(payload);
  const out = {
    version: 1,
    generated_at: new Date().toISOString(),
    generated_from: [path.relative(repoRoot, inputPath).replace(/\\/g, '/')],
    counties
  };

  fs.writeFileSync(outputPath, JSON.stringify(out), 'utf8');
  console.log(`Wrote ${Object.keys(counties).length} counties -> ${path.relative(repoRoot, outputPath)}`);
}

if (require.main === module) main();
