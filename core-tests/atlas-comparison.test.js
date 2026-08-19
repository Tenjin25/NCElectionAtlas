const test = require('node:test');
const assert = require('node:assert/strict');
const AtlasComparison = require('../js/atlas-comparison.js');

test('computes signed Republican-minus-Democratic margins and A-minus-B changes', () => {
  const primary = AtlasComparison.signedMarginPct(45, 55, 100);
  const comparison = AtlasComparison.signedMarginPct(52, 48, 100);
  assert.equal(primary, 10);
  assert.equal(comparison, -4);
  assert.deepEqual(AtlasComparison.compareSignedMargins(primary, comparison), {
    primary: 10,
    comparison: -4,
    delta: 14,
    direction: 'rep',
    magnitude: 14
  });
});

test('marks missing comparisons and effectively even changes safely', () => {
  assert.equal(AtlasComparison.compareSignedMargins(2, 2.003).direction, 'even');
  assert.equal(AtlasComparison.compareSignedMargins(2, NaN).direction, 'none');
  assert.ok(Number.isNaN(AtlasComparison.signedMarginPct(0, 0, 0)));
});

test('derives displayed comparison changes from the displayed margins', () => {
  assert.deepEqual(
    AtlasComparison.compareDisplayedSignedMargins(-25.437, -26.452),
    {
      primary: -25.44,
      comparison: -26.45,
      delta: 1.01,
      direction: 'rep',
      magnitude: 1.01
    }
  );
});

test('prefers the nearest prior contest of the same type', () => {
  assert.equal(
    AtlasComparison.pickDefaultComparisonContest('president_2024', [
      'governor_2024',
      'president_2016',
      'president_2020',
      'president_2024'
    ]),
    'president_2020'
  );
  assert.equal(
    AtlasComparison.pickDefaultComparisonContest('state_house_2024', [
      'state_house_2022',
      'state_house_2024',
      'state_senate_2024'
    ]),
    'state_house_2022'
  );
});

test('falls back to another contest from the same year for ticket-split comparisons', () => {
  assert.equal(
    AtlasComparison.pickDefaultComparisonContest('governor_2024', [
      'president_2024',
      'us_senate_2022'
    ]),
    'president_2024'
  );
});
