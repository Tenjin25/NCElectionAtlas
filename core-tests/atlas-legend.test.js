const test = require('node:test');
const assert = require('node:assert/strict');

const AtlasLegend = require('../js/atlas-legend.js');

function options(overrides = {}) {
  return {
    colorblind: false,
    populationMetric: 'pct',
    colorForMargin: (value, winner) => `${winner}:${value}`,
    colorForWinner: winner => `winner:${winner}`,
    colorForFlip: winner => `flip:${winner}`,
    colorForShift: value => `shift:${value}`,
    colorForDemographics: (...values) => `demo:${values.join(',')}`,
    colorForPopulationPct: value => `pct:${value}`,
    colorForPopulationAbs: value => `abs:${value}`,
    ...overrides
  };
}

function rowCount(html) {
  return (html.match(/class="legend-tier-row"/g) || []).length;
}

test('builds the established category count for every legend mode', () => {
  assert.equal(rowCount(AtlasLegend.buildMarginsLegendHTML(options())), 15);
  assert.equal(rowCount(AtlasLegend.buildWinnersLegendHTML(options())), 3);
  assert.equal(rowCount(AtlasLegend.buildFlipsLegendHTML(options())), 3);
  assert.equal(rowCount(AtlasLegend.buildShiftLegendHTML(options())), 15);
  assert.equal(rowCount(AtlasLegend.buildComparisonLegendHTML(options())), 15);
  assert.equal(rowCount(AtlasLegend.buildDemographicsLegendHTML(options())), 18);
  assert.equal(rowCount(AtlasLegend.buildPopulationChangeLegendHTML(options())), 14);
});

test('keeps shift and comparison semantics distinct', () => {
  const shift = AtlasLegend.buildShiftLegendHTML(options());
  const comparison = AtlasLegend.buildComparisonLegendHTML(options());
  assert.match(shift, /Extreme Democratic shift/);
  assert.match(shift, /Toward Republicans/);
  assert.match(comparison, /Extreme Democratic difference/);
  assert.match(comparison, /Primary more Republican/);
});

test('switches population legends and color functions by metric', () => {
  const percent = AtlasLegend.buildPopulationChangeLegendHTML(options());
  const absolute = AtlasLegend.buildPopulationChangeLegendHTML(options({ populationMetric: 'abs' }));
  assert.match(percent, /Extreme decline/);
  assert.match(percent, /pct:-32/);
  assert.match(absolute, /Extreme loss/);
  assert.match(absolute, /abs:-180000/);
});

test('adds a textual colorblind key when the accessible palette is active', () => {
  const standard = AtlasLegend.buildMarginsLegendHTML(options());
  const accessible = AtlasLegend.buildMarginsLegendHTML(options({ colorblind: true }));
  assert.doesNotMatch(standard, /Color-blind palette/);
  assert.match(accessible, /Republican = orange/);
  assert.match(accessible, /Democratic = blue/);
});
