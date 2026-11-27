const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const readJson = (...parts) => JSON.parse(fs.readFileSync(path.join(root, ...parts), 'utf8'));
const source = readJson('data', 'contests', 'us_senate_2026.json');
const plan2024 = readJson('data', 'district_contests_2024_lines', 'congressional_us_senate_2026.json');
const plan2026 = readJson('data', 'district_contests_2026_lines', 'congressional_us_senate_2026.json');
const buckets = ['dem_votes', 'rep_votes', 'other_votes'];
const changed = new Set(['1', '3']);
const districtIds = Array.from({ length: 14 }, (_, index) => String(index + 1));

function sumVotes(results, districts, bucket) {
  return districts.reduce((sum, district) => sum + results[district][bucket], 0);
}

test('2026 Senate district totals conserve every party vote on both congressional plans', () => {
  const sourceTotals = Object.fromEntries(buckets.map(bucket => [
    bucket,
    source.rows.reduce((sum, row) => sum + row[bucket], 0)
  ]));

  for (const [label, plan] of [['2024', plan2024], ['2026', plan2026]]) {
    const results = plan.general.results;
    assert.deepEqual(Object.keys(results).sort((a, b) => Number(a) - Number(b)), districtIds, `${label} district IDs`);
    for (const bucket of buckets) {
      assert.equal(sumVotes(results, districtIds, bucket), sourceTotals[bucket], `${label} ${bucket}`);
      assert.equal(plan.meta[bucket], sourceTotals[bucket], `${label} metadata ${bucket}`);
    }
    for (const district of districtIds) {
      const row = results[district];
      assert.equal(row.total_votes, buckets.reduce((sum, bucket) => sum + row[bucket], 0), `${label} CD-${district} total`);
    }
  }
});

test('the 12 unchanged congressional districts have identical Senate results', () => {
  const unchanged = districtIds.filter(district => !changed.has(district));
  assert.equal(unchanged.length, 12);
  for (const district of unchanged) {
    assert.deepEqual(plan2026.general.results[district], plan2024.general.results[district], `CD-${district}`);
  }
});

test('CD-01 and CD-03 conserve their combined Senate votes between plans', () => {
  const districts = [...changed];
  for (const bucket of buckets) {
    assert.equal(
      sumVotes(plan2026.general.results, districts, bucket),
      sumVotes(plan2024.general.results, districts, bucket),
      bucket
    );
  }
});
