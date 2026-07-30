const test = require('node:test');
const assert = require('node:assert/strict');
const AtlasCore = require('../js/atlas-core.js');

test('normalizes county and row keys without changing established semantics', () => {
  assert.equal(AtlasCore.normalizeCountyToken("  New Hanover's  "), 'NEW HANOVERS');
  assert.equal(AtlasCore.normalizeCountyToken('WAKE - 01.14'), 'WAKE - 01.14');
  assert.equal(AtlasCore.normalizeRowKey('  Scotland   -  01-16 '), 'SCOTLAND - 01-16');
});

test('preserves complete OpenElections precinct labels for historical matching', () => {
  assert.equal(
    AtlasCore.normalizeOpenElectionsPrecinctLabel('  Precinct   01-07A '),
    'PRECINCT 01-07A'
  );
  assert.equal(
    AtlasCore.normalizeOpenElectionsPrecinctLabel('Burlington 10'),
    'BURLINGTON 10'
  );
  assert.equal(AtlasCore.normalizeOpenElectionsPrecinctLabel('PCT 243'), 'PCT 243');
  assert.equal(AtlasCore.normalizeOpenElectionsPrecinctLabel('PRECINCT #4 NORTH'), 'PRECINCT #4 NORTH');
  assert.equal(AtlasCore.normalizeOpenElectionsPrecinctLabel('Lake Landing'), 'LAKE LANDING');
  assert.notEqual(
    AtlasCore.normalizeOpenElectionsPrecinctLabel('PRECINCT 01-01'),
    AtlasCore.normalizeOpenElectionsPrecinctLabel('PRECINCT 01-02')
  );
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

test('expands legacy precinct labels without conflating exact Wake codes', () => {
  const davidsonAliases = AtlasCore.extractPrecinctAliasCandidates('06_BOONE #06');
  assert.equal(davidsonAliases.has('06_BOONE #06'), true);
  assert.equal(davidsonAliases.has('06'), true);
  assert.equal(davidsonAliases.has('BOONE #06'), true);

  const wake0125 = AtlasCore.extractPrecinctAliasCandidates('01-25');
  const wake1925 = AtlasCore.extractPrecinctAliasCandidates('19-25');
  assert.equal(wake0125.has('01-25'), true);
  assert.equal(wake1925.has('19-25'), true);
  assert.equal(wake1925.has('01-25'), false);
});

test('extracts embedded, split, compact, and prefixed precinct code variants', () => {
  const embedded = new Set();
  AtlasCore.addEmbeddedPrecinctCodeVariants(
    'PRECINCT 01-14A',
    value => embedded.add(value)
  );
  assert.deepEqual(embedded, new Set(['01-14A', '01-14']));

  const alphaBase = new Set();
  AtlasCore.addNumericBaseVariantsFromAlphaSuffix('0010A', value => alphaBase.add(value));
  assert.equal(alphaBase.has('10'), true);
  assert.equal(alphaBase.has('0010'), true);
  assert.equal(alphaBase.has('10-1'), true);

  const compact = [];
  AtlasCore.addCompactCodeVariants(
    '01.14',
    new Set(['01-14', '01-15']),
    value => compact.push(value)
  );
  assert.deepEqual(compact, ['01-14']);

  const prefixed = [];
  AtlasCore.addPrefixStrippedNumericVariants(
    'PR01',
    new Set(['01', '02']),
    value => prefixed.push(value)
  );
  assert.deepEqual(prefixed, ['01']);
});

test('uses closest Wake-style split codes only when the exact code is absent', () => {
  const countyCodes = new Set(['01-07A', '01-07B', '01-08', '01-25']);
  const splitMatches = [];
  AtlasCore.addClosestHyphenCodeVariants(
    'PRECINCT 01-07',
    countyCodes,
    value => splitMatches.push(value)
  );
  assert.deepEqual(splitMatches.sort(), ['01-07A', '01-07B']);

  const exactMatches = [];
  AtlasCore.addClosestHyphenCodeVariants(
    '01-25',
    countyCodes,
    value => exactMatches.push(value)
  );
  assert.deepEqual(exactMatches, []);
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
