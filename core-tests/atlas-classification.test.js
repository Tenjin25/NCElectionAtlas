const test = require('node:test');
const assert = require('node:assert/strict');
const AtlasClassification = require('../js/atlas-classification.js');

test('labels current lean and opposing movement consistently', () => {
  assert.equal(
    AtlasClassification.classifyLabel(8, -3, false, {
      tone: 'rep',
      marginParty: 'rep',
      longThreshold: 2,
      recentThreshold: 1
    }),
    'Red-leaning, cooling'
  );
  assert.equal(
    AtlasClassification.classifyLabel(-8, -3, false, {
      marginParty: 'dem',
      longThreshold: 2,
      recentThreshold: 1
    }),
    'Moving left'
  );
  assert.equal(
    AtlasClassification.classifyLabel(0, 0, true, { tone: 'dem' }),
    'Recent flip to Democrats'
  );
});

test('classifies structured trajectory snapshots', () => {
  assert.deepEqual(
    AtlasClassification.classifyTrajectorySnapshot({
      current_margin: 8,
      shift_since_2020: -2,
      shift_since_2000: -22
    }),
    {
      base: 'Emerging Republican Edge',
      subtype: 'Active Suburban Transition',
      momentum: '\u2190 Moving left faster'
    }
  );
  assert.deepEqual(
    AtlasClassification.classifyTrajectorySnapshot({
      base: 'Custom base',
      current_margin: -18,
      shift_since_2020: 2.5,
      shift_since_2000: 3
    }),
    {
      base: 'Custom base',
      subtype: 'Blue-leaning, cooling',
      momentum: '\u2192 Moving right'
    }
  );
});

test('preserves trajectory-rule precedence across every structured subtype', () => {
  const cases = [
    [{ current_margin: -8, shift_since_2020: 2, shift_since_2000: 22 }, 'Active Republican Transition'],
    [{ current_margin: 20, shift_since_2020: 1, shift_since_2000: -6 }, 'Suburbanizing (Lagging)'],
    [{ current_margin: -20, shift_since_2020: -1, shift_since_2000: 6 }, 'Counter-Suburbanizing (Lagging)'],
    [{ current_margin: 15, shift_since_2020: -3, shift_since_2000: 0 }, 'Red-leaning, cooling'],
    [{ current_margin: -15, shift_since_2020: 3, shift_since_2000: 0 }, 'Blue-leaning, cooling'],
    [{ current_margin: 16, shift_since_2020: 2, shift_since_2000: 12 }, 'Moving right'],
    [{ current_margin: -8, shift_since_2020: -2, shift_since_2000: -12 }, 'Moving left'],
    [{ current_margin: 2, shift_since_2020: 0, shift_since_2000: 20 }, 'Breaking right'],
    [{ current_margin: -2, shift_since_2020: 0, shift_since_2000: -20 }, 'Breaking left'],
    [{ current_margin: 2, shift_since_2020: 0, shift_since_2000: 0 }, 'Stable / Mixed']
  ];

  cases.forEach(([input, expectedSubtype]) => {
    assert.equal(AtlasClassification.classifyTrajectorySnapshot(input).subtype, expectedSubtype);
  });
});

test('maps growth archetypes without using the unused growth-rate argument', () => {
  assert.equal(AtlasClassification.classifyGrowthType('Brunswick'), '\u{1F30A} Coastal Growth');
  assert.equal(AtlasClassification.classifyGrowthType('Mecklenburg'), '\u{1F306} Metro Spillover');
  assert.equal(AtlasClassification.classifyGrowthType('Johnston'), '\u{1F6E3}\uFE0F Corridor Growth');
  assert.equal(AtlasClassification.classifyGrowthType('Orange'), '\u{1F3ED} Stable / Local Growth');
});

test('normalizes signed margins and result labels', () => {
  assert.equal(
    AtlasClassification.getSignedMarginTowardGop({ margin_pct: 4.2, winner: 'D' }),
    -4.2
  );
  assert.equal(
    AtlasClassification.getSignedMarginTowardGop({
      rep_votes: 55,
      dem_votes: 45,
      total_votes: 100
    }),
    10
  );
  assert.equal(AtlasClassification.formatShiftLabel(-2.345, 0.05), '\u2190 D+2.35%');
  assert.equal(AtlasClassification.formatShiftLabel(0.01, 0.05), '\u2194 No clear shift');
  assert.equal(
    AtlasClassification.formatWinnerLabel({ year: 2024 }, 3.456),
    '2024: R+3.46%'
  );
});
