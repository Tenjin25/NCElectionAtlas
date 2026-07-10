/* eslint-disable no-console */
const fs = require('fs');
const path = require('path');

const TARGET_FILES = [
  'president_2024.json',
  'nc_court_of_appeals_judge_seat_12_2024.json',
  'nc_court_of_appeals_judge_seat_14_2024.json',
  'nc_court_of_appeals_judge_seat_15_2024.json',
  'nc_supreme_court_associate_justice_seat_06_2024.json'
];

const REMAPS = new Map([
  ['ROCKINGHAM - HO-1', 'ROCKINGHAM - HO'],
  ['ROCKINGHAM - HU-1', 'ROCKINGHAM - HU'],
  ['ROCKINGHAM - LI-1', 'ROCKINGHAM - LI'],
  ['ROCKINGHAM - WS-1', 'ROCKINGHAM - WS'],
  ['COLUMBUS - P117', 'COLUMBUS - P11'],
  ['COLUMBUS - P245', 'COLUMBUS - P24'],
  ['RICHMOND - 21', 'RICHMOND - 03']
]);

function fixFile(filePath) {
  const payload = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  let changed = 0;
  for (const row of payload.rows || []) {
    const current = String(row.county || '');
    const next = REMAPS.get(current);
    if (!next) continue;
    row.county = next;
    changed += 1;
  }
  if (changed > 0) {
    fs.writeFileSync(filePath, JSON.stringify(payload));
  }
  return changed;
}

function main() {
  const repoRoot = path.resolve(__dirname, '..');
  const contestDir = path.join(repoRoot, 'data', 'contests');
  const summary = {};

  for (const fileName of fs.readdirSync(contestDir).filter((name) => name.endsWith('_2024.json')).sort()) {
    const filePath = path.join(contestDir, fileName);
    const changed = fixFile(filePath);
    if (changed > 0) {
      summary[fileName] = changed;
    }
  }

  for (const fileName of TARGET_FILES) {
    if (!(fileName in summary)) {
      summary[fileName] = 0;
    }
  }

  console.log(JSON.stringify(summary, null, 2));
}

main();
