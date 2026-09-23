const test = require('node:test');
const assert = require('node:assert/strict');
const { createDefinition, boundsFromGeoJSON } = require('../js/atlas-custom-region');

test('custom regions keep only valid unique county names', () => {
  assert.deepEqual(
    createDefinition('  My   Region  ', ['Wake County', 'DURHAM', 'Wake', 'Unknown'], ['WAKE', 'DURHAM']),
    { label: 'My Region', counties: ['DURHAM', 'WAKE'] }
  );
  assert.equal(createDefinition('', ['Wake'], ['WAKE']), null);
  assert.equal(createDefinition('Empty', ['Unknown'], ['WAKE']), null);
});

test('custom region bounds include only selected county geometries', () => {
  const geojson = { features: [
    { properties: { NAME20: 'Wake' }, geometry: { coordinates: [[[[-79, 35], [-78, 36]]]] } },
    { properties: { NAME20: 'Durham' }, geometry: { coordinates: [[[[-79.5, 35.5], [-78.5, 36.5]]]] } },
    { properties: { NAME20: 'Mecklenburg' }, geometry: { coordinates: [[[[-81, 34], [-80, 35]]]] } }
  ] };
  assert.deepEqual(boundsFromGeoJSON(geojson, ['Wake', 'Durham']), [[-79.5, 35], [-78, 36.5]]);
  assert.equal(boundsFromGeoJSON(geojson, ['No county']), null);
});
