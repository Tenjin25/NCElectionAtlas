/* eslint-disable no-console */
// Adds deterministic, display-safe margin fields to contest JSON rows:
//   - margin_pct_display_2dp (string, e.g. "1.94")
//   - margin_pct_display_3dp (string, e.g. "0.019")
//
// Computed from integer votes using BigInt rounding (half-up), so it cannot drift
// by 0.01 due to IEEE-754 floating point edge cases.
//
// Usage:
//   node tools/add_margin_pct_display_fields.js
//   node tools/add_margin_pct_display_fields.js --dir data/contests
//
// Notes:
// - Does not remove or modify existing fields (like `margin_pct`).
// - Uses `rep_votes - dem_votes` absolute difference and `total_votes` (fallback to sum).

const fs = require('fs');
const path = require('path');

function toBigIntSafeInt(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0n;
  return BigInt(Math.trunc(n));
}

function pow10n(digits) {
  const d = Math.max(0, Math.floor(Number(digits) || 0));
  let p = 1n;
  for (let i = 0; i < d; i++) p *= 10n;
  return p;
}

function divRoundHalfUpBigInt(numerator, denominator) {
  const d = BigInt(denominator);
  if (d <= 0n) return 0n;
  const n = BigInt(numerator);
  if (n <= 0n) return 0n;
  return (n + (d / 2n)) / d;
}

function fixedStringFromScaledBigInt(scaled, digits) {
  const d = Math.max(0, Math.floor(Number(digits) || 0));
  const s = BigInt(scaled);
  if (d <= 0) return s.toString();
  const scale = pow10n(d);
  const intPart = (s / scale).toString();
  const fracPart = (s % scale).toString().padStart(d, '0');
  return `${intPart}.${fracPart}`;
}

function absPctFixedFromVotes(numeratorVotes, totalVotes, digits) {
  // percent = (numeratorVotes / totalVotes) * 100
  const total = toBigIntSafeInt(totalVotes);
  if (total <= 0n) return fixedStringFromScaledBigInt(0n, digits);
  const numer = toBigIntSafeInt(numeratorVotes);
  if (numer <= 0n) return fixedStringFromScaledBigInt(0n, digits);
  const scale = pow10n(digits);
  const scaled = divRoundHalfUpBigInt(numer * 100n * scale, total);
  return fixedStringFromScaledBigInt(scaled, digits);
}

function computeMarginDisplayStrings(row) {
  const demVotes = toBigIntSafeInt(row?.dem_votes ?? 0);
  const repVotes = toBigIntSafeInt(row?.rep_votes ?? 0);
  const otherVotes = toBigIntSafeInt(row?.other_votes ?? 0);
  const totalVotesRaw = toBigIntSafeInt(row?.total_votes ?? 0);
  const totalVotes = totalVotesRaw > 0n ? totalVotesRaw : (demVotes + repVotes + otherVotes);
  if (totalVotes <= 0n) return { d2: '0.00', d3: '0.000' };

  const diff = repVotes >= demVotes ? (repVotes - demVotes) : (demVotes - repVotes);
  return {
    d2: absPctFixedFromVotes(diff, totalVotes, 2),
    d3: absPctFixedFromVotes(diff, totalVotes, 3),
  };
}

function walkJsonFiles(dirPath) {
  const out = [];
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  for (const e of entries) {
    const p = path.join(dirPath, e.name);
    if (e.isDirectory()) continue;
    if (!e.isFile()) continue;
    if (!e.name.toLowerCase().endsWith('.json')) continue;
    out.push(p);
  }
  out.sort((a, b) => a.localeCompare(b));
  return out;
}

function main() {
  const root = path.resolve(__dirname, '..');
  const args = process.argv.slice(2);
  const dirFlagIdx = args.indexOf('--dir');
  const relDir = (dirFlagIdx >= 0 ? args[dirFlagIdx + 1] : null) || 'data/contests';
  const targetDir = path.resolve(root, relDir);

  if (!fs.existsSync(targetDir) || !fs.statSync(targetDir).isDirectory()) {
    console.error(`Directory not found: ${targetDir}`);
    process.exit(2);
  }

  const files = walkJsonFiles(targetDir);
  if (!files.length) {
    console.log(`[margin-display] No JSON files found in ${path.relative(root, targetDir)}`);
    return;
  }

  let updatedFiles = 0;
  let updatedRows = 0;

  for (const filePath of files) {
    let doc;
    try {
      doc = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    } catch (err) {
      console.warn(`[margin-display] Skip (invalid JSON): ${path.relative(root, filePath)}`);
      continue;
    }

    const rows = Array.isArray(doc?.rows) ? doc.rows : null;
    if (!rows) continue;

    let changed = false;
    for (const row of rows) {
      if (!row || typeof row !== 'object') continue;
      const { d2, d3 } = computeMarginDisplayStrings(row);
      if (row.margin_pct_display_2dp !== d2) {
        row.margin_pct_display_2dp = d2;
        changed = true;
      }
      if (row.margin_pct_display_3dp !== d3) {
        row.margin_pct_display_3dp = d3;
        changed = true;
      }
      if (changed) updatedRows++;
    }

    if (!changed) continue;
    fs.writeFileSync(filePath, JSON.stringify(doc, null, 2) + '\n', 'utf8');
    updatedFiles++;
  }

  console.log(`[margin-display] Updated files: ${updatedFiles}/${files.length}`);
  console.log(`[margin-display] Rows updated: ${updatedRows}`);
}

main();

