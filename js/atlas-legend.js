(function initializeAtlasLegend(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.AtlasLegend = Object.freeze(api);
}(typeof globalThis !== 'undefined' ? globalThis : this, function createAtlasLegend() {
  const SHIFT_VALUES = [-25, -20, -15, -10, -5, -1, -0.5, 0, 0.5, 1, 5, 10, 15, 20, 25];
  const SHIFT_NAMES = ['Extreme', 'Major', 'Very strong', 'Strong', 'Clear', 'Moderate', 'Slight'];
  const SHIFT_RANGES = ['25+ pts', '20.00–24.99 pts', '15.00–19.99 pts', '10.00–14.99 pts', '5.00–9.99 pts', '1.00–4.99 pts', '0.50–0.99 pts'];

  function colorFunction(options, name) {
    const fn = options && options[name];
    if (typeof fn !== 'function') throw new TypeError(`${name} must be a function`);
    return fn;
  }

  function buildLegendSpectrum(colors, className) {
    return `
      <div class="legend-spectrum ${className}">
        ${colors.map(color => `<span class="legend-segment legend-color" style="background: ${color};"></span>`).join('')}
      </div>
    `;
  }

  function buildColorblindLegendNote(options) {
    if (!options || !options.colorblind) return '';
    const colorForWinner = colorFunction(options, 'colorForWinner');
    return `
      <div class="colorblind-legend-note" role="note" aria-label="Color-blind palette is active">
        <strong>Color-blind palette</strong>
        <span class="colorblind-legend-key"><i style="background:${colorForWinner('R')};"></i>Republican = orange</span>
        <span class="colorblind-legend-key"><i style="background:${colorForWinner('D')};"></i>Democratic = blue</span>
      </div>
    `;
  }

  function buildTierList(tiers, colorForTier) {
    return `
      <div class="legend-tier-list${tiers.population ? ' population-tiers' : ''}" role="list">
        ${tiers.map(tier => `
          <div class="legend-tier-row" role="listitem">
            <span class="legend-color" style="background: ${colorForTier(tier)};${tier.party === 'tie' || tier.missing ? ' border: 1px solid rgba(15,23,42,0.18);' : ''}"></span>
            <span class="legend-tier-label ${tier.party || ''}">${tier.label}</span>
            <span class="legend-tier-range">${tier.range}</span>
          </div>
        `).join('')}
      </div>
    `;
  }

  function buildMarginsLegendHTML(options) {
    const colorForMargin = colorFunction(options, 'colorForMargin');
    const stops = [40, 30, 20, 10, 5.5, 1, 0.5];
    const labels = ['Annihilation', 'Dominant', 'Stronghold', 'Safe', 'Likely', 'Lean', 'Tilt'];
    const ranges = ['40+', '30.00–39.99', '20.00–29.99', '10.00–19.99', '5.50–9.99', '1.00–5.49', '0.50–0.99'];
    const repTiers = stops.map((value, i) => ({ label: labels[i], range: ranges[i], value, winner: 'R', party: 'rep' }));
    const demTiers = stops.slice().reverse().map((value, i) => ({
      label: labels[labels.length - 1 - i],
      range: ranges[ranges.length - 1 - i],
      value,
      winner: 'D',
      party: 'dem'
    }));
    const tiers = [...repTiers, { label: 'Tossup', range: '<0.50', value: 0, winner: 'R', party: 'tie' }, ...demTiers];
    const spectrum = tiers.map(tier => colorForMargin(tier.value, tier.winner));
    return `
      <div class="legend-scale-shell">
        ${buildColorblindLegendNote(options)}
        ${buildLegendSpectrum(spectrum, 'margins')}
        <div class="legend-scale-caption">
          <span class="rep">Republican ${options && options.colorblind ? 'orange' : 'red'}</span>
          <span>Even</span>
          <span class="dem">Democratic blue</span>
        </div>
        ${buildTierList(tiers, tier => colorForMargin(tier.value, tier.winner))}
      </div>
    `;
  }

  function buildWinnersLegendHTML(options) {
    const colorForWinner = colorFunction(options, 'colorForWinner');
    const tiers = [
      { label: 'Democratic win', range: 'D leads', value: 'D', party: 'dem' },
      { label: 'Republican win', range: 'R leads', value: 'R', party: 'rep' },
      { label: 'Tie or no data', range: 'Even / missing', value: 'T', party: 'tie' }
    ];
    return `${buildColorblindLegendNote(options)}${buildTierList(tiers, tier => colorForWinner(tier.value))}`;
  }

  function buildFlipsLegendHTML(options) {
    const colorForFlip = colorFunction(options, 'colorForFlip');
    const tiers = [
      { label: 'Flip to Democratic', range: 'R → D', value: 'D', party: 'dem' },
      { label: 'Flip to Republican', range: 'D → R', value: 'R', party: 'rep' },
      { label: 'No flip or no prior', range: 'Unchanged / missing', value: 'T', party: 'tie' }
    ];
    return `${buildColorblindLegendNote(options)}${buildTierList(tiers, tier => colorForFlip(tier.value))}`;
  }

  function shiftTiers(comparison) {
    const dem = SHIFT_VALUES.slice(0, 7).map((value, i) => ({
      label: `${SHIFT_NAMES[i]} Democratic ${comparison ? 'difference' : 'shift'}`,
      range: SHIFT_RANGES[i], value, party: 'dem'
    }));
    const rep = SHIFT_VALUES.slice(8).map((value, i) => ({
      label: `${SHIFT_NAMES[6 - i]} Republican ${comparison ? 'difference' : 'shift'}`,
      range: SHIFT_RANGES[6 - i], value, party: 'rep'
    }));
    return [...dem, {
      label: comparison ? 'No notable difference' : 'No notable shift',
      range: 'Under 0.50 pts', value: 0, party: 'tie'
    }, ...rep];
  }

  function buildMovementLegendHTML(options, comparison) {
    const colorForShift = colorFunction(options, 'colorForShift');
    const tiers = shiftTiers(comparison);
    return `
      <div class="legend-scale-shell">
        ${buildColorblindLegendNote(options)}
        ${buildLegendSpectrum(SHIFT_VALUES.map(colorForShift), 'shift')}
        <div class="legend-scale-caption">
          <span class="dem">${comparison ? 'Primary more Democratic' : 'Toward Democrats'}</span>
          <span>${comparison ? 'No difference' : 'No change'}</span>
          <span class="rep">${comparison ? 'Primary more Republican' : 'Toward Republicans'}</span>
        </div>
        ${buildTierList(tiers, tier => colorForShift(tier.value))}
      </div>
    `;
  }

  function buildShiftLegendHTML(options) {
    return buildMovementLegendHTML(options, false);
  }

  function buildComparisonLegendHTML(options) {
    return buildMovementLegendHTML(options, true);
  }

  function buildDemographicsLegendHTML(options) {
    const colorForDemographics = colorFunction(options, 'colorForDemographics');
    const groups = [
      { name: 'White', majority: [60, 20, 20], plurality: [40, 30, 30] },
      { name: 'Black', majority: [20, 60, 20], plurality: [30, 40, 30] },
      { name: 'Hispanic', majority: [20, 20, 60], plurality: [30, 30, 40] },
      { name: 'Native', majority: [15, 15, 10, 60], plurality: [20, 15, 15, 40] },
      { name: 'Asian', majority: [15, 15, 10, 10, 60], plurality: [20, 15, 10, 10, 40] },
      { name: 'Pacific', majority: [10, 10, 10, 5, 5, 60, 0], plurality: [15, 10, 10, 5, 5, 40, 15] },
      { name: 'Multiracial', majority: [10, 10, 10, 5, 5, 0, 60], plurality: [15, 10, 10, 5, 5, 15, 40] }
    ];
    const tiers = groups.flatMap(group => [
      { label: `${group.name} majority`, range: '≥50%', values: group.majority },
      { label: `${group.name} plurality`, range: 'Largest, <50%', values: group.plurality }
    ]);
    tiers.splice(2, 0,
      { label: 'Narrow White majority · strong Black second', range: '≥50%', values: [52, 41, 7] },
      { label: 'Narrow Black majority · strong White second', range: '≥50%', values: [41, 52, 7] }
    );
    tiers.push(
      { label: 'Near tie / mixed', range: 'No clear leader', values: [35, 35, 30] },
      { label: 'No demographic data', range: 'Unavailable', values: [null, null, null, null, null, null, null], missing: true }
    );
    return buildTierList(tiers, tier => colorForDemographics(...tier.values));
  }

  function populationTierDefinitions(useAbs) {
    const values = useAbs
      ? [-180000, -120000, -60000, -30000, -15000, -4000, 0, 4000, 15000, 30000, 60000, 120000, 180000]
      : [-32, -22, -12, -7, -3, -1, 0, 1, 3, 7, 12, 22, 32];
    const labels = useAbs
      ? ['Extreme loss', 'Major loss', 'Severe loss', 'Sharp loss', 'Moderate loss', 'Mild loss', 'Near flat', 'Modest gain', 'Steady gain', 'Substantial gain', 'Large gain', 'Major gain', 'Extreme gain']
      : ['Extreme decline', 'Major decline', 'Severe decline', 'Sharp decline', 'Moderate decline', 'Mild decline', 'Near flat', 'Modest growth', 'Steady growth', 'Strong growth', 'Rapid growth', 'Boom growth', 'Explosive growth'];
    const ranges = useAbs
      ? ['≤−150k', '−149.99k to −100k', '−99.99k to −50k', '−49.99k to −25k', '−24.99k to −10k', '−9.99k to −2.50k', '−2.50k to +2.50k', '+2.50k–9.99k', '+10k–24.99k', '+25k–49.99k', '+50k–99.99k', '+100k–149.99k', '+150k+']
      : ['≤−30%', '−29.99 to −20%', '−19.99 to −10%', '−9.99 to −5%', '−4.99 to −2%', '−1.99 to −0.50%', '−0.50 to +1%', '+1–1.99%', '+2–4.99%', '+5–9.99%', '+10–19.99%', '+20–29.99%', '≥30%'];
    return values.map((value, i) => ({ label: labels[i], range: ranges[i], value, party: i === 6 ? 'tie' : '' }));
  }

  function buildPopulationChangeLegendHTML(options) {
    const useAbs = String(options && options.populationMetric || 'pct') === 'abs';
    const color = colorFunction(options, useAbs ? 'colorForPopulationAbs' : 'colorForPopulationPct');
    const tiers = populationTierDefinitions(useAbs);
    tiers.push({ label: 'No population data', range: 'Unavailable', value: undefined, party: 'tie', missing: true });
    tiers.population = true;
    const axis = useAbs
      ? ['-150k+', '-100k', '-50k', '-25k', '-10k', '-2.5k', 'Flat', '+2.5k', '+10k', '+25k', '+50k', '+100k', '+150k+']
      : ['-30%+', '-20%', '-10%', '-5%', '-2%', '-0.5%', 'Flat', '+1%', '+2%', '+5%', '+10%', '+20%', '+30%+'];
    return `
      <div class="legend-scale-shell">
        ${buildLegendSpectrum(tiers.slice(0, 13).map(tier => color(tier.value)), 'population-change')}
        <div class="legend-scale-caption population-change"><span class="dem">Decline</span><span>Near flat</span><span class="rep">Growth</span><span class="rep">${useAbs ? 'Large gains' : 'Explosive growth'}</span></div>
        <div class="legend-axis population-change">${axis.map((label, i) => `<span class="${i < 6 ? 'dem' : (i > 6 ? 'rep' : '')}">${label}</span>`).join('')}</div>
        ${buildTierList(tiers, tier => color(tier.value))}
      </div>
    `;
  }

  return {
    buildLegendSpectrum,
    buildColorblindLegendNote,
    buildMarginsLegendHTML,
    buildWinnersLegendHTML,
    buildFlipsLegendHTML,
    buildShiftLegendHTML,
    buildComparisonLegendHTML,
    buildDemographicsLegendHTML,
    buildPopulationChangeLegendHTML
  };
}));
