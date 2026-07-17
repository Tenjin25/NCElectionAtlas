const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require('@playwright/test');

const chromeCandidates = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe'
];
let modelServer = null;
let modelBrowser = null;
const modelRoot = process.env.MODEL_ROOT
  ? path.resolve(process.env.MODEL_ROOT)
  : path.join(__dirname, '..');
const modelPort = Number(process.env.MODEL_PORT || 4173);
const modelOrigin = `http://127.0.0.1:${modelPort}`;

function summarizeResults(results) {
  const rows = Object.values(results || {});
  const totals = rows.reduce((sum, row) => {
    sum.dem += Number(row?.dem_votes || 0);
    sum.rep += Number(row?.rep_votes || 0);
    sum.total += Number(row?.total_votes || 0);
    return sum;
  }, { dem: 0, rep: 0, total: 0 });
  const twoParty = totals.dem + totals.rep;
  return {
    districts: rows.length,
    dem: Math.round(totals.dem),
    rep: Math.round(totals.rep),
    total: Math.round(totals.total),
    marginPctRMinusD: twoParty > 0 ? ((totals.rep - totals.dem) / twoParty) * 100 : null,
    // Live panel metric on post-clamp backend: (R−D)/total including other.
    marginPctUiSigned: totals.total > 0 ? ((totals.rep - totals.dem) / totals.total) * 100 : null
  };
}

(async () => {
  modelServer = spawn(process.execPath, [path.join(__dirname, '..', 'tools', 'static_server.js'), '--port', String(modelPort), '--host', '127.0.0.1'], {
    cwd: modelRoot,
    stdio: 'ignore',
    windowsHide: true
  });
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      const response = await fetch(`${modelOrigin}/index.html`);
      if (response.ok) break;
    } catch (_) {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  const executablePath = chromeCandidates.find(fs.existsSync);
  modelBrowser = await chromium.launch(executablePath ? { executablePath } : {});
  const page = await modelBrowser.newPage();
  await page.addInitScript(() => {
    let mapboxValue;
    class DiagnosticMap {
      constructor(options = {}) {
        const container = typeof options.container === 'string'
          ? document.getElementById(options.container)
          : options.container;
        this.canvas = document.createElement('canvas');
        this.canvas.className = 'mapboxgl-canvas';
        if (container) container.appendChild(this.canvas);
        return new Proxy(this, {
          get: (target, property) => {
            if (property in target) return target[property];
            return () => target;
          }
        });
      }
      on(event, layerOrCallback, maybeCallback) {
        const callback = typeof layerOrCallback === 'function' ? layerOrCallback : maybeCallback;
        if ((event === 'load' || event === 'style.load') && typeof callback === 'function') setTimeout(callback, 0);
        return this;
      }
      once(event, callback) { return this.on(event, callback); }
      loaded() { return true; }
      isStyleLoaded() { return true; }
      getCanvas() { return this.canvas; }
      getContainer() { return this.canvas?.parentElement || null; }
      getBounds() {
        return { getWest: () => -85, getSouth: () => 33, getEast: () => -75, getNorth: () => 37 };
      }
      getLayer() { return null; }
      getSource() { return null; }
      queryRenderedFeatures() { return []; }
    }
    Object.defineProperty(window, 'mapboxgl', {
      configurable: true,
      get: () => mapboxValue,
      set: value => {
        mapboxValue = value;
        if (mapboxValue) mapboxValue.Map = DiagnosticMap;
      }
    });
  });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(String(error?.message || error)));
  await page.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.hostname === '127.0.0.1') return route.continue();
    if (request.resourceType() === 'script') {
      if (url.hostname === 'api.mapbox.com') {
        return route.fulfill({ contentType: 'application/javascript', body: `window.mapboxgl={Map:class{},NavigationControl:class{},Popup:class{},Marker:class{},setTelemetryEnabled(){}};` });
      }
      if (url.pathname.includes('papaparse')) {
        return route.fulfill({ contentType: 'application/javascript', body: `window.Papa={parse(){return {data:[],errors:[]}}};` });
      }
      if (url.pathname.includes('turf')) {
        return route.fulfill({ contentType: 'application/javascript', body: `window.turf=new Proxy({}, {get(){return ()=>null}});` });
      }
    }
    return route.fulfill({ status: 204, body: '' });
  });
  await page.goto(`${modelOrigin}/index.html`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  try {
    await page.waitForFunction(() => {
      try {
        return typeof loadContestSlice === 'function'
          && typeof loadDistrictSlice === 'function'
          && !!getModeledContestDefinition('us_senate_model', 2026);
      } catch (_) {
        return false;
      }
    }, null, { timeout: 20000 });
  } catch (error) {
    throw new Error(`${error.message}\nPage errors:\n${pageErrors.join('\n')}`);
  }

  const visibleStatewide = await page.evaluate(async () => {
    const key = 'us_senate_model_2026';
    const select = document.getElementById('contestSelect');
    if (select) select.value = key;
    await applyContest(key);
    const cards = Array.from(document.querySelectorAll('[data-statewide-content]'))
      .map(node => String(node?.innerText || '').trim())
      .filter(Boolean);
    return {
      cardText: cards[0] || '',
      selectedContest: String(select?.value || '')
    };
  });

  const output = await page.evaluate(async () => {
    const precinctRows = await loadContestSlice('us_senate_model', 2026);
    const senate2022Rows = await loadContestSlice('us_senate', 2022);
    const president2024Rows = await loadContestSlice('president', 2024);
    const countyRows = precinctRows;
    const aggregateContestByCounty = (rows, contestType) => rows.reduce((counties, row) => {
      const county = String(row?.county || '').toUpperCase().split(' - ')[0].trim();
      if (!county) return counties;
      const totals = counties[county] || { dem: 0, rep: 0, total: 0 };
      totals.dem += Number(row?.[`${contestType}_dem`] || 0);
      totals.rep += Number(row?.[`${contestType}_rep`] || 0);
      totals.total += Number(row?.[`${contestType}_total`] || 0);
      counties[county] = totals;
      return counties;
    }, {});
    const senate2022ByCounty = aggregateContestByCounty(senate2022Rows, 'us_senate');
    const president2024ByCounty = aggregateContestByCounty(president2024Rows, 'president');
    const precinctTotals = precinctRows.reduce((sum, row) => {
      sum.dem += Number(row?.us_senate_model_dem || 0);
      sum.rep += Number(row?.us_senate_model_rep || 0);
      sum.total += Number(row?.us_senate_model_total || 0);
      return sum;
    }, { dem: 0, rep: 0, total: 0 });
    const officialCountyTotals = null;
    const rawCountyTotals = countyRows.reduce((sum, row) => {
      sum.dem += Number(row?.us_senate_model_dem || 0);
      sum.rep += Number(row?.us_senate_model_rep || 0);
      sum.total += Number(row?.us_senate_model_total || 0);
      return sum;
    }, { dem: 0, rep: 0, total: 0 });
    const countyTotals = officialCountyTotals
      ? Object.values(officialCountyTotals).reduce((sum, row) => {
        sum.dem += Number(row?.dem_votes || 0);
        sum.rep += Number(row?.rep_votes || 0);
        sum.total += Number(row?.total_votes || 0);
        return sum;
      }, { dem: 0, rep: 0, total: 0 })
      : rawCountyTotals;
    const countyTwoParty = countyTotals.dem + countyTotals.rep;
    const countyUiSigned = countyTotals.total > 0
      ? ((countyTotals.rep - countyTotals.dem) / countyTotals.total) * 100
      : null;
    const modeledTargetMoment = countyRows.reduce((sum, row) => {
      const total = Number(row?.us_senate_model_total || 0);
      const target = Number(row?.__model_with_candidates_margin_pct);
      if (total > 0 && Number.isFinite(target)) {
        sum.moment += target * total;
        sum.total += total;
      }
      return sum;
    }, { moment: 0, total: 0 });
    const countyByName = {};
    countyRows.forEach(row => {
      const county = String(row?.county || '').toUpperCase().split(' - ')[0].trim();
      const node = countyByName[county] || { dem: 0, rep: 0, localEffectD: 0, countyTypeEffectD: 0 };
      node.dem += Number(row?.us_senate_model_dem || 0);
      node.rep += Number(row?.us_senate_model_rep || 0);
      node.localEffectD = Number(row?.__model_candidate_effect_local_d_pts || node.localEffectD || 0);
      node.countyTypeEffectD = Number(row?.__model_candidate_effect_county_type_d_pts || node.countyTypeEffectD || 0);
      node.baselineMargin = Number(row?.__model_baseline_margin_pct ?? node.baselineMargin);
      node.targetMargin = Number(row?.__model_with_candidates_margin_pct ?? node.targetMargin);
      node.candidateEffectD = Number(row?.__model_candidate_effect_d_pts ?? node.candidateEffectD);
      node.anchorSpread = Number(row?.__model_anchor_spread_pts ?? node.anchorSpread);
      node.inputDisagreement = String(row?.__model_input_disagreement || node.inputDisagreement || '');
      node.countyType = String(row?.__model_county_type || node.countyType || '');
      countyByName[county] = node;
    });
    if (officialCountyTotals) Object.entries(officialCountyTotals).forEach(([county, row]) => {
      const key = String(county || '').toUpperCase();
      countyByName[key] = {
        ...(countyByName[key] || {}),
        dem: Number(row?.dem_votes || 0),
        rep: Number(row?.rep_votes || 0)
      };
    });
    const scopes = {};
    for (const scope of ['congressional', 'state_house', 'state_senate']) {
      const node = await loadDistrictSlice(scope, 'us_senate_model', 2026);
      scopes[scope] = node?.general?.results || {};
    }
    return {
      precinct: {
        rows: precinctRows.length,
        dem: precinctTotals.dem,
        rep: precinctTotals.rep,
        total: precinctTotals.total,
        marginPctUiSigned: precinctTotals.total > 0
          ? ((precinctTotals.rep - precinctTotals.dem) / precinctTotals.total) * 100
          : null
      },
      county: {
        rows: countyRows.length,
        officialCounties: officialCountyTotals ? Object.keys(officialCountyTotals).length : 0,
        dem: countyTotals.dem,
        rep: countyTotals.rep,
        total: countyTotals.total,
        marginPctRMinusD: countyTwoParty > 0 ? ((countyTotals.rep - countyTotals.dem) / countyTwoParty) * 100 : null,
        marginPctUiSigned: countyUiSigned,
        targetMarginPctUiSigned: modeledTargetMoment.total > 0
          ? modeledTargetMoment.moment / modeledTargetMoment.total
          : null,
        targetMarginTotal: modeledTargetMoment.total
      },
      countyByName,
      anchorsByCounty: Object.fromEntries(
        Array.from(new Set([
          ...Object.keys(senate2022ByCounty),
          ...Object.keys(president2024ByCounty)
        ])).map(county => {
          const signed = (totals) => Number(totals?.total || 0) > 0
            ? ((Number(totals?.rep || 0) - Number(totals?.dem || 0)) / Number(totals.total)) * 100
            : null;
          return [county, {
            senate2022MarginPctUiSigned: signed(senate2022ByCounty[county]),
            president2024MarginPctUiSigned: signed(president2024ByCounty[county])
          }];
        })
      ),
      countyTypeTotals: Object.values(countyByName).reduce((groups, row) => {
        const key = String(row?.countyType || 'unknown').toLowerCase() || 'unknown';
        const group = groups[key] || { dem: 0, rep: 0, total: 0, counties: 0 };
        group.dem += Number(row?.dem || 0);
        group.rep += Number(row?.rep || 0);
        group.total += Number(row?.dem || 0) + Number(row?.rep || 0);
        group.counties += 1;
        groups[key] = group;
        return groups;
      }, {}),
      scopes
    };
  });

  const result = {
    visibleStatewide,
    precinct: output.precinct,
    county: output.county,
    countyTypeTotals: output.countyTypeTotals,
    focusCounties: Object.fromEntries(['NASH', 'WILSON', 'ANSON', 'PASQUOTANK', 'HOKE', 'ROBESON', 'BLADEN', 'SCOTLAND', 'WAKE', 'MECKLENBURG', 'DURHAM', 'ORANGE', 'CHATHAM', 'GRANVILLE', 'GUILFORD', 'FORSYTH', 'BUNCOMBE', 'CUMBERLAND', 'NEW HANOVER', 'WATAUGA', 'MOORE', 'GASTON', 'CABARRUS', 'ALAMANCE', 'CATAWBA', 'PITT', 'JACKSON', 'LINCOLN', 'UNION', 'JOHNSTON'].map(county => {
      const row = output.countyByName[county] || {};
      const anchors = output.anchorsByCounty[county] || {};
      const twoParty = Number(row.dem || 0) + Number(row.rep || 0);
      return [county, {
        ...row,
        ...anchors,
        marginPctRMinusD: twoParty > 0 ? ((Number(row.rep || 0) - Number(row.dem || 0)) / twoParty) * 100 : null
      }];
    })),
    districts: Object.fromEntries(Object.entries(output.scopes).map(([scope, results]) => [scope, summarizeResults(results)])),
    pageErrors
  };
  console.log(JSON.stringify(result, null, 2));
  await modelBrowser.close();
  modelServer.kill();
})().catch(error => {
  try { modelBrowser?.close(); } catch (_) {}
  try { modelServer?.kill(); } catch (_) {}
  console.error(error);
  process.exitCode = 1;
});
