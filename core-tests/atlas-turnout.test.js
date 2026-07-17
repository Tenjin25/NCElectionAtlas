const test = require('node:test');
const assert = require('node:assert/strict');
const AtlasTurnout = require('../js/atlas-turnout.js');

test('builds deterministic turnout quantile metadata', () => {
  assert.deepEqual(
    AtlasTurnout.buildOpacityMeta([50, 10, 40, 20, 30]),
    { q20: 10, q40: 20, q60: 30, q80: 40 }
  );
  assert.equal(AtlasTurnout.buildOpacityMeta([0, null, 'bad']), null);
});

test('maps turnout bands to bounded opacity values', () => {
  const meta = { q20: 20, q40: 40, q60: 60, q80: 80 };
  assert.equal(AtlasTurnout.opacityFromTotal(100, meta, 0.9), 0.98);
  assert.ok(Math.abs(AtlasTurnout.opacityFromTotal(70, meta, 0.8) - 0.82) < 1e-12);
  assert.equal(AtlasTurnout.opacityFromTotal(10, meta, 0.3), 0.24);
  assert.equal(AtlasTurnout.opacityFromTotal(0, meta, 0.8), 0.8);
});

test('builds county and district Mapbox turnout expressions', () => {
  const county = AtlasTurnout.buildCountyExpression(0.8, { WAKE: 100, DARE: 25 });
  assert.equal(county[0], 'case');
  assert.deepEqual(county[1][2], 'WAKE');
  assert.equal(county.at(-1), 0.6000000000000001);

  const district = AtlasTurnout.buildDistrictExpression(0.75, { 1: 100, bad: 50 });
  assert.equal(district[0], 'case');
  assert.equal(district[1][2], 1);
  assert.equal(district.length, 4);
  assert.equal(AtlasTurnout.buildDistrictExpression(0.75, { 1: 100 }, false), 0.75);
});

test('builds precinct expressions from map totals', () => {
  const expression = AtlasTurnout.buildPrecinctExpression(
    0.7,
    new Map([['01-01', 100], ['01-02', 50]])
  );
  assert.deepEqual(expression[1], ['==', ['get', 'precinct_norm'], '01-01']);
  assert.equal(expression.at(-1), 0.52);
  assert.equal(AtlasTurnout.buildPrecinctExpression(0.7, null), 0.7);
});
