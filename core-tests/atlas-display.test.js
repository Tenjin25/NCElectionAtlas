const test = require('node:test');
const assert = require('node:assert/strict');
const AtlasDisplay = require('../js/atlas-display.js');

test('rounds display values consistently at decimal boundaries', () => {
  assert.equal(AtlasDisplay.roundForDisplay(1.005, 2), 1.01);
  assert.equal(AtlasDisplay.toFixedForDisplay(1.65, 1), '1.7');
  assert.equal(AtlasDisplay.toFixedForDisplay(2.675, 2), '2.68');
  assert.equal(AtlasDisplay.formatVotehubPct(Number.NaN, 2), '0.00');
});

test('preserves a visible margin in extremely close races', () => {
  assert.equal(AtlasDisplay.closeRaceDisplayDigits(0.014), 3);
  assert.equal(AtlasDisplay.closeRaceDisplayDigits(0.049), 3);
  assert.equal(AtlasDisplay.closeRaceDisplayDigits(0.05), 1);
  assert.ok(Math.abs(AtlasDisplay.marginPctDisplayValue(5001, 5000, 10001) - 0.01) < 1e-10);
  assert.equal(AtlasDisplay.formatMarginPctForDisplay(0.014), '0.014');
  assert.equal(AtlasDisplay.formatMarginPctForDisplay(5.45), '5.5');
});

test('rounds county margins directly from raw vote totals', () => {
  assert.ok(Math.abs(AtlasDisplay.countyMarginPctDisplayValue(63746, 54494, 120202) - 7.7) < 1e-10);
  assert.ok(Math.abs(AtlasDisplay.countyMarginPctDisplayValue(63237, 52162, 117227) - 9.4) < 1e-10);
});

test('rounds the raw NC-13 margin instead of subtracting rounded shares', () => {
  assert.equal(AtlasDisplay.marginPctDisplayValue(158392, 150859, 323433), 2.3);
});

test('rounds the 2024 statewide presidential margin directly to 3.2', () => {
  assert.equal(AtlasDisplay.marginPctDisplayValue(2898423, 2715375, 5699141), 3.2);
});

test('formats compact totals and signed deltas with established suffixes', () => {
  assert.equal(AtlasDisplay.formatCompactVoteTotal(1250), '1.3K');
  assert.equal(AtlasDisplay.formatCompactDeltaTotal(1250), '1.3k');
  assert.equal(AtlasDisplay.formatSignedCompactDelta(-1250), '-1.3k');
  assert.equal(AtlasDisplay.formatSignedPctDelta(1.234, 2), '+1.23%');
});

test('escapes dynamic text used in generated HTML', () => {
  assert.equal(
    AtlasDisplay.escapeHtml(`<Roy & "Pat's">`),
    '&lt;Roy &amp; &quot;Pat&#39;s&quot;&gt;'
  );
});
