const test = require('node:test');
const assert = require('node:assert/strict');
const AtlasDisplay = require('../js/atlas-display.js');

test('rounds display values consistently at decimal boundaries', () => {
  assert.equal(AtlasDisplay.roundForDisplay(1.005, 2), 1.01);
  assert.equal(AtlasDisplay.toFixedForDisplay(2.675, 2), '2.68');
  assert.equal(AtlasDisplay.formatVotehubPct(Number.NaN, 2), '0.00');
});

test('preserves a visible margin in extremely close races', () => {
  assert.equal(AtlasDisplay.closeRaceDisplayDigits(0.014), 3);
  assert.equal(AtlasDisplay.closeRaceDisplayDigits(0.015), 2);
  assert.ok(Math.abs(AtlasDisplay.marginPctDisplayValue(5001, 5000, 10001) - 0.01) < 1e-10);
  assert.equal(AtlasDisplay.formatMarginPctForDisplay(0.014), '0.014');
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
