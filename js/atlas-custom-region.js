(function initializeAtlasCustomRegion(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.AtlasCustomRegion = Object.freeze(api);
}(typeof globalThis !== 'undefined' ? globalThis : this, function createAtlasCustomRegion() {
  function normalizeCounty(name) {
    return String(name || '').trim().replace(/\s+County$/i, '').replace(/\s+/g, ' ').toUpperCase();
  }

  function createDefinition(name, counties, allowedCounties) {
    const label = String(name || '').trim().replace(/\s+/g, ' ').slice(0, 60);
    const allowed = new Set((Array.isArray(allowedCounties) ? allowedCounties : []).map(normalizeCounty));
    const unique = [...new Set((Array.isArray(counties) ? counties : []).map(normalizeCounty))].filter(county => allowed.has(county)).sort();
    if (!label || !unique.length) return null;
    return { label, counties: unique };
  }

  function boundsFromGeoJSON(geojson, counties) {
    const selected = new Set((Array.isArray(counties) ? counties : []).map(normalizeCounty));
    const bounds = [Infinity, Infinity, -Infinity, -Infinity];
    function visit(coordinates) {
      if (!Array.isArray(coordinates)) return;
      if (typeof coordinates[0] === 'number' && typeof coordinates[1] === 'number') {
        const [lon, lat] = coordinates;
        if (Number.isFinite(lon) && Number.isFinite(lat)) {
          bounds[0] = Math.min(bounds[0], lon);
          bounds[1] = Math.min(bounds[1], lat);
          bounds[2] = Math.max(bounds[2], lon);
          bounds[3] = Math.max(bounds[3], lat);
        }
        return;
      }
      coordinates.forEach(visit);
    }
    for (const feature of geojson?.features || []) {
      const props = feature?.properties || {};
      const county = normalizeCounty(props.NAME20 || props.county_nam || props.COUNTYNAME || props.NAME || props.County || props.name);
      if (selected.has(county)) visit(feature?.geometry?.coordinates);
    }
    return bounds.every(Number.isFinite) ? [[bounds[0], bounds[1]], [bounds[2], bounds[3]]] : null;
  }

  return { normalizeCounty, createDefinition, boundsFromGeoJSON };
}));
