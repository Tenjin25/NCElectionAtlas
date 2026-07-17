const test = require('node:test');
const assert = require('node:assert/strict');
const AtlasModeling = require('../js/atlas-modeling.js');

test('builds stable modeled-definition signatures independent of key order', () => {
  const first = {
    year: 2026,
    contestType: 'us_senate_model',
    weights: { recent: 0.6, baseline: 0.4 }
  };
  const second = {
    weights: { baseline: 0.4, recent: 0.6 },
    contestType: 'us_senate_model',
    year: 2026
  };

  assert.equal(
    AtlasModeling.getDefinitionSignature(first),
    AtlasModeling.getDefinitionSignature(second)
  );
  assert.equal(AtlasModeling.getDefinitionSignature({ year: 2026 }), '');
});

test('serializes non-finite and circular model inputs deterministically', () => {
  const input = { uncertainty: Number.POSITIVE_INFINITY };
  input.self = input;

  assert.equal(
    AtlasModeling.stableStringify(input),
    '{"self":"[Circular]","uncertainty":"Infinity"}'
  );
});

test('returns model county-behavior labels with a balanced fallback', () => {
  assert.equal(AtlasModeling.getCountyBehaviorLabel('rural_surge'), 'Rural surge');
  assert.equal(AtlasModeling.getCountyBehaviorLabel('unknown'), 'Balanced counties');
});

test('classifies model confidence from tuning distance and behavior', () => {
  const baseline = {
    blendWeight: 0.6,
    turnoutFactor: 1,
    candidateBonusScale: 1,
    countyBehaviorMode: 'balanced',
    uncertaintyBoost: 1
  };

  assert.deepEqual(
    AtlasModeling.inferConfidence({ ...baseline }, baseline),
    { label: 'High', range: '\u00b11.4 pts' }
  );
  assert.deepEqual(
    AtlasModeling.inferConfidence({
      blendWeight: 1.2,
      turnoutFactor: 1.8,
      candidateBonusScale: 2,
      countyBehaviorMode: 'volatile',
      uncertaintyBoost: 2
    }, baseline),
    { label: 'Low', range: '\u00b13.0 pts' }
  );
  assert.deepEqual(
    AtlasModeling.inferConfidence(null, baseline),
    { label: 'Low', range: '\u00b12.0 pts' }
  );
});
