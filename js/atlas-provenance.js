(function initializeAtlasProvenance(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.AtlasProvenance = Object.freeze(api);
}(typeof globalThis !== 'undefined' ? globalThis : this, function createAtlasProvenance() {
  function cleanToken(value) {
    return String(value || '').trim();
  }

  function readableSource(value) {
    const source = cleanToken(value);
    if (!source) return '';
    const known = {
      batch_shatter_vap_party_split: 'Precinct results reallocated with VAP weights',
      sbe2020_to_onemap2025_12_vap_bridge: 'NCSBE results bridged to the current precinct basis',
      county_totals: 'Certified county totals',
      ncga_statpack: 'Official NCGA StatPack district totals'
    };
    if (known[source]) return known[source];
    return source
      .replace(/[_-]+/g, ' ')
      .replace(/\b\w/g, letter => letter.toUpperCase());
  }

  function coverageValue(meta) {
    const value = Number(meta?.match_coverage_pct);
    return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : null;
  }

  function describeProvenance(meta = {}, context = {}) {
    const kind = cleanToken(context.kind).toLowerCase();
    const modeled = !!context.modeled || /model/i.test(cleanToken(meta.source));
    const fallbackScope = cleanToken(context.fallbackScope || context.rowMeta?.__fallback_scope).toLowerCase();
    const coverage = coverageValue(meta);
    const calibrated = !!meta.ncga_statpack_calibrated || !!meta.margin_calibrated_to;
    const exactCounty = kind === 'county' && !!context.hasOfficialCountyTotal && fallbackScope !== 'county';
    const exactRegion = kind === 'region' && !!context.hasOfficialCountyTotal;
    const nongeoMode = cleanToken(meta.nongeo_allocation_mode);
    const source = readableSource(meta.source);
    let level = 'medium';
    let label = 'Estimated';
    let method = source || 'Documented atlas result';
    let summary = 'This result uses a documented geographic allocation method.';

    if (modeled) {
      level = 'modeled';
      label = 'Modeled scenario';
      method = source || 'Atlas election model';
      summary = 'This is a synthetic scenario, not a certified election result.';
    } else if (fallbackScope === 'county') {
      level = 'low';
      label = 'County fallback';
      summary = 'Precinct history was unavailable, so this view uses its county result.';
    } else if (meta.ncga_statpack_calibrated) {
      level = 'high';
      label = 'Official benchmark';
      method = 'Official NCGA StatPack district totals';
      summary = 'District totals are locked to an official published benchmark.';
    } else if (exactCounty) {
      level = 'high';
      label = 'Certified total';
      method = source || 'Certified county contest total';
      summary = 'The displayed county total comes from the source election returns.';
    } else if (exactRegion) {
      level = 'high';
      label = 'Certified county sum';
      method = source || 'Sum of certified county totals';
      summary = 'The regional result sums certified totals from each included county.';
    } else if (calibrated) {
      level = 'high';
      label = 'Calibrated estimate';
      summary = 'The geographic allocation is reconciled to a trusted district benchmark.';
    } else if (coverage !== null && coverage >= 97) {
      level = 'medium-high';
      label = 'High-coverage estimate';
      summary = 'Nearly all source precinct keys matched before geographic allocation; this is not a vote-level accuracy measure.';
    } else if (coverage !== null && coverage < 90) {
      level = 'low';
      label = 'Lower-confidence estimate';
      summary = 'A meaningful share of source precinct keys required fallback allocation.';
    } else if (kind === 'precinct') {
      label = 'Bridged precinct';
      summary = 'The result is mapped across changing precinct boundaries using the documented bridge.';
    }

    const details = [];
    if (coverage !== null) details.push({ label: 'Matched precinct keys', value: `${coverage.toFixed(2)}%` });
    if (nongeoMode) {
      details.push({
        label: 'Allocation method',
        value: nongeoMode.replace(/_/g, ' ')
      });
    }
    if (cleanToken(meta.district_lines_label)) {
      details.push({ label: 'Boundary basis', value: cleanToken(meta.district_lines_label) });
    }
    if (cleanToken(meta.match_crosswalk || meta.bridge)) {
      details.push({ label: 'Source bridge', value: cleanToken(meta.match_crosswalk || meta.bridge) });
    }

    return { level, label, method, summary, coverage, details };
  }

  function comparisonCaution(primary, secondary) {
    const descriptions = [primary, secondary];
    if (descriptions.some(item => item?.level === 'modeled')) {
      return 'This comparison includes a modeled scenario. The change is illustrative, not an observed election shift.';
    }
    if (descriptions.some(item => item?.level === 'low')) {
      return 'At least one result relies on fallback allocation. Small differences may reflect source coverage.';
    }
    if (descriptions.some(item => !item || !['Official benchmark', 'Certified total'].includes(item.label))) {
      return 'At least one result uses geographic allocation. Small differences may reflect boundary matching.';
    }
    return '';
  }

  return { readableSource, describeProvenance, comparisonCaution };
}));
