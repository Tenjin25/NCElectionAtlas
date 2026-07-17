(function initializeAtlasData(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.AtlasData = Object.freeze(api);
}(typeof globalThis !== 'undefined' ? globalThis : this, function createAtlasData() {
  function detectBasePath(locationLike) {
    const hostname = String(locationLike?.hostname || '');
    if (!hostname.endsWith('github.io')) return '';
    const parts = String(locationLike?.pathname || '').split('/').filter(Boolean);
    return parts.length ? `/${parts[0]}` : '';
  }

  function withBase(path, locationLike) {
    if (!path) return path;
    if (/^https?:\/\//i.test(path)) return path;
    const base = detectBasePath(locationLike);
    const cleaned = String(path).replace(/^\.\//, '').replace(/^\/+/, '');
    return base ? `${base}/${cleaned}` : cleaned;
  }

  function toAbsoluteUrl(path, href) {
    const normalized = String(path || '').trim();
    if (!normalized) return normalized;
    try {
      return new URL(normalized, href).toString();
    } catch (_) {
      return normalized;
    }
  }

  function withCacheBuster(path, token) {
    const normalized = String(path || '').trim();
    if (!normalized) return normalized;
    if (/^mapbox:\/\//i.test(normalized)) return normalized;
    if (/[?&]v=/.test(normalized)) return normalized;
    const separator = normalized.includes('?') ? '&' : '?';
    return `${normalized}${separator}v=${encodeURIComponent(token)}`;
  }

  async function loadCached(key, options = {}) {
    const resolvedCache = options.resolvedCache;
    const inflightCache = options.inflightCache;
    if (resolvedCache?.has(key)) return resolvedCache.get(key);
    if (inflightCache?.has(key)) return inflightCache.get(key);
    if (typeof options.load !== 'function') throw new TypeError('loadCached requires a load function');

    const promise = Promise.resolve().then(options.load).then(value => {
      const shouldCache = typeof options.shouldCache === 'function'
        ? options.shouldCache(value)
        : true;
      if (shouldCache) resolvedCache?.set(key, value);
      return value;
    });
    inflightCache?.set(key, promise);
    try {
      return await promise;
    } finally {
      inflightCache?.delete(key);
    }
  }

  function mapContestPayloadRows(payload, contestType, year) {
    return (payload?.rows || []).map(row => ({
      year: Number(year),
      county: row.county,
      [`${contestType}_dem`]: Number(row.dem_votes) || 0,
      [`${contestType}_rep`]: Number(row.rep_votes) || 0,
      [`${contestType}_other`]: Number(row.other_votes) || 0,
      [`${contestType}_total`]: Number(row.total_votes) || 0,
      [`${contestType}_dem_candidate`]: row.dem_candidate || '',
      [`${contestType}_rep_candidate`]: row.rep_candidate || '',
      [`${contestType}_margin`]: Number(row.margin) || 0,
      [`${contestType}_margin_pct`]: Number(row.margin_pct) || 0,
      [`${contestType}_winner`]: row.winner || '',
      [`${contestType}_color`]: row.color || ''
    }));
  }

  return {
    detectBasePath,
    withBase,
    toAbsoluteUrl,
    withCacheBuster,
    loadCached,
    mapContestPayloadRows
  };
}));
