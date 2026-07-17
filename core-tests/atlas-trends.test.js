const test = require('node:test');
const assert = require('node:assert/strict');
const AtlasTrends = require('../js/atlas-trends.js');

const signedMargin = row => Number(row.margin);

test('normalizes trend series by numeric year', () => {
  assert.deepEqual(
    AtlasTrends.normalizeSeries([
      { year: 2024 },
      null,
      { year: 'bad' },
      { year: 2000 }
    ]).map(row => Number(row.year)),
    [2000, 2024]
  );
});

test('analyzes long-run and recent partisan shifts', () => {
  const analysis = AtlasTrends.analyzeSeries([
    { year: 2024, margin: 8 },
    { year: 2000, margin: -4 },
    { year: 2008, margin: 0 },
    { year: 2020, margin: 3 },
    { year: 2016, margin: 1 }
  ], { signedMargin });

  assert.equal(analysis.latest.year, 2024);
  assert.equal(analysis.first.year, 2000);
  assert.equal(analysis.longShiftTowardGop, 12);
  assert.equal(analysis.shiftSince2008, 8);
  assert.equal(analysis.shiftSince2020, 5);
  assert.equal(analysis.crossedParties, true);
  assert.equal(analysis.rightwardSteps, 2);
  assert.equal(analysis.leftwardSteps, 0);
  assert.equal(analysis.hasLongAnchor, true);
});

test('measures shifts toward the current Democratic side', () => {
  const analysis = AtlasTrends.analyzeSeries([
    { year: 2016, margin: -2 },
    { year: 2020, margin: -5 },
    { year: 2024, margin: -9 }
  ], { signedMargin });

  assert.equal(analysis.recentShiftTowardGop, -4);
  assert.equal(analysis.towardCurrentSide, 4);
  assert.equal(analysis.towardCurrentSideLong, 7);
  assert.equal(analysis.awayFromCurrentSide, -4);
  assert.equal(analysis.cycleShiftLabel, 'Since 2020');
  assert.equal(analysis.historySparse, true);
});

test('returns an empty normalized result for missing history', () => {
  assert.deepEqual(AtlasTrends.analyzeSeries([], { signedMargin }), { sorted: [] });
});
