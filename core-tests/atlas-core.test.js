const test = require('node:test');
const assert = require('node:assert/strict');
const AtlasCore = require('../js/atlas-core.js');

test('normalizes county and row keys without changing established semantics', () => {
  assert.equal(AtlasCore.normalizeCountyToken("  New Hanover's  "), 'NEW HANOVERS');
  assert.equal(AtlasCore.normalizeCountyToken('WAKE - 01.14'), 'WAKE - 01.14');
  assert.equal(AtlasCore.normalizeRowKey('  Scotland   -  01-16 '), 'SCOTLAND - 01-16');
});

test('normalizes and compacts legacy precinct aliases', () => {
  assert.equal(
    AtlasCore.normalizePrecinctAliasToken('Precinct 04_Arcadia #04'),
    '04 ARCADIA #04'
  );
  assert.equal(
    AtlasCore.normalizePrecinctAliasToken('Ward 6 - Voting Location'),
    '6'
  );
  assert.equal(AtlasCore.compactPrecinctAliasToken('06_Boone #06'), '06BOONE06');
});

test('computes signed R-minus-D margin using total votes including other', () => {
  assert.equal(AtlasCore.signedMarginPctFromVotes(40, 50, 100), 10);
  assert.equal(AtlasCore.signedMarginPctFromVotes(55, 40, 100), -15);
  assert.equal(AtlasCore.signedMarginPctFromVotes(10, 20, 0), 0);
});

test('rescales vote sets while conserving the requested integer total', () => {
  assert.deepEqual(
    AtlasCore.rescaleVoteSetToTargetTotal(
      { dem: 40, rep: 50, other: 10, total: 100 },
      50
    ),
    { dem: 20, rep: 25, other: 5, total: 50 }
  );

  const unchanged = { dem: 1, rep: 2, other: 0, total: 3 };
  assert.equal(AtlasCore.rescaleVoteSetToTargetTotal(unchanged, 0), unchanged);
});
