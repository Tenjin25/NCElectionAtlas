const test = require('node:test');
const assert = require('node:assert/strict');
const AtlasURLState = require('../js/atlas-url-state.js');

test('normalizes supported view, mode, and line tokens', () => {
  assert.equal(AtlasURLState.normalizeViewToken(' State_House '), 'state_house');
  assert.equal(AtlasURLState.normalizeViewToken('townships'), '');
  assert.equal(AtlasURLState.normalizeModeToken(' FLIPS '), 'flips');
  assert.equal(AtlasURLState.normalizeModeToken('turnout'), '');
  assert.equal(AtlasURLState.normalizeDistrictLinesYear('2026'), 2026);
  assert.equal(AtlasURLState.normalizeDistrictLinesYear('2018'), 2022);
});

test('parses a complete shareable atlas URL state', () => {
  assert.deepEqual(
    AtlasURLState.parse(
      '?view=counties&contest=us_senate_model_2026&mode=margins&focus=county%3AWAKE' +
      '&lines=2024&swing=-1.5&sscope=wake&bar=on&democontrast=high&popmetric=abs' +
      '&mblend=.7&mturnout=.58&mbonus=1.1'
    ),
    {
      hasAny: true,
      view: 'counties',
      contest: 'us_senate_model_2026',
      mode: 'margins',
      focus: 'county:WAKE',
      lines: 2024,
      swing: -1.5,
      sscope: 'wake',
      barometerEnabled: true,
      demoContrastHigh: true,
      popMetric: 'abs',
      mBlend: 0.7,
      mTurnout: 0.58,
      mBonus: 1.1
    }
  );
});

test('returns neutral defaults when URL state is absent', () => {
  assert.deepEqual(AtlasURLState.parse(''), {
    hasAny: false,
    view: '',
    contest: '',
    mode: '',
    focus: '',
    lines: null,
    swing: null,
    sscope: null,
    barometerEnabled: null,
    demoContrastHigh: null,
    popMetric: null,
    mBlend: null,
    mTurnout: null,
    mBonus: null
  });
});
