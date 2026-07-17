const test = require('node:test');
const assert = require('node:assert/strict');
const AtlasElection = require('../js/atlas-election.js');

test('finalizes vote sets as non-negative integers', () => {
  assert.deepEqual(
    AtlasElection.finalizeVoteSet(10.4, 20.6, -2, 100),
    { dem: 10, rep: 21, other: 0, total: 31 }
  );
  assert.deepEqual(
    AtlasElection.finalizeVoteSet(0, 0, 0, 25),
    { dem: 0, rep: 0, other: 0, total: 25 }
  );
});

test('applies margin swing as a vote transfer while preserving total votes', () => {
  assert.deepEqual(
    AtlasElection.shiftVotesBySwingPct(40, 50, 10, 100, 10),
    { dem: 45, rep: 45, other: 10, total: 100 }
  );
  assert.deepEqual(
    AtlasElection.shiftVotesBySwingPct(40, 50, 10, 100, 0),
    { dem: 40, rep: 50, other: 10, total: 100 }
  );
});

test('selects deterministic quantiles from sorted values', () => {
  assert.equal(AtlasElection.quantile([10, 20, 30, 40, 50], 0.6), 30);
  assert.equal(AtlasElection.quantile([], 0.5), 0);
});

test('parses contest values and identifies party flips', () => {
  assert.deepEqual(AtlasElection.parseContestValue('us_senate_2026'), ['us_senate', '2026']);
  assert.deepEqual(AtlasElection.parseContestValue('governor'), ['governor', '']);
  assert.deepEqual(
    AtlasElection.flipInfo(-2.5, 1.2),
    { flipped: true, from: 'D', to: 'R' }
  );
  assert.deepEqual(
    AtlasElection.flipInfo(0, 1.2),
    { flipped: false, from: 'T', to: 'R' }
  );
});
