# A Student and Contributor Guide to the North Carolina Election Atlas

> **In one sentence:** The North Carolina Election Atlas is an interactive civic map that lets you compare how North Carolina places voted, while also showing the difficult data work required to put elections from different years onto precinct and district boundaries that keep changing.

This guide explains the atlas in two connected ways: as a tool for learning about North Carolina politics, and as a static web application whose build scripts turn election returns, Census geography, and crosswalks into map-ready files. It describes the repository as it exists now. When current code, older generated data, and written documentation disagree, the current browser code is treated as the authority and the difference is called out.

The repository is named `NCPrecinctMap`, its original and technical project name. The current interface and public site call the product **North Carolina Election Atlas**. They refer to the same project.

---

## 1. What the atlas is

The atlas helps a reader ask civic questions without first learning geographic information systems (GIS):

- Which counties were close in the 2024 presidential election?
- Did a county move toward Republicans or Democrats since the previous comparable election?
- Where did voters choose different parties for President and Governor?
- How would an older statewide election look if its votes were allocated to the 2022, 2024, or 2026 district lines?
- Which displayed results are direct totals, which are sums, and which depend on geographic estimates?

Likely users include students, teachers, voters, journalists, researchers, campaign observers, and people studying redistricting. The available views are Counties, a precinct overlay within the county view, Congressional districts, State House districts, and State Senate districts. The current precinct manifest covers general-election contests in the even years **2000, 2002, 2004, 2006, 2008, 2010, 2012, 2014, 2016, 2018, 2020, 2022, and 2024**, though not every office appears in every year. The interface also constructs two explicitly synthetic 2026 entries in code: a U.S. Senate model and an N.C. Supreme Court model (`MODELED_CONTEST_DEFINITIONS` in `index.html`).

The main contest families in `data/contests/manifest.json` are:

- President every four years from 2000 through 2024.
- U.S. Senate in the years when North Carolina had a Senate election from 2002 through 2022.
- Governor and the statewide Council of State offices, mainly every four years from 2000 through 2024. The 2012 Attorney General race is intentionally absent because it was uncontested.
- N.C. Supreme Court and Court of Appeals contests. Older named-seat contests are linked to numbered seat families by frontend logic and `data/mappings/judicial_seat_crosswalk.csv`.

The district manifests add district-scoped contest files and, in some cases, U.S. House contests. As of this guide, the production catalogs contain 156 precinct contest slices, 482 slices for 2022 lines, 390 for 2024 lines, and 129 congressional slices for 2026 lines. The exact manifest, rather than a prose list, is the final authority on what the picker offers.

### Why historical election mapping is hard

Election results name voting units as they existed at the time. Those units do not stand still. Counties can rename, split, merge, or renumber precincts. A precinct code reused in two years may describe a different footprint. Legislative districts are redrawn after each census and sometimes again because of litigation. Early, absentee, provisional, and administrative vote rows may not describe a polygon at all.

That means an older election shown on a newer district plan is not a photograph of the historical contest. It answers a hypothetical: **approximately how would those older votes distribute across this selected set of newer boundaries?** The atlas uses documented crosswalks and population weights to estimate the answer.

> **Why this matters:** A map can look exact even when its underlying geography is estimated. Responsible interpretation begins by asking both “what votes?” and “on whose boundaries?”

---

## 2. Political and civic foundations

### The geographic building blocks

**Precinct.** A local election-administration unit. Voters are assigned to precincts, and election returns are often reported by precinct. A precinct is smaller than a county, but it is not guaranteed to remain unchanged from one election to the next.

**Voting Tabulation District (VTD).** A Census Bureau geographic approximation of election precincts, created with state and local officials so voting data can be tabulated with Census geography. A VTD can be extremely useful for connecting elections to Census blocks, but it is not automatically identical to the precinct definition used in an election return.

**County.** One of North Carolina's 100 major local-government and election-administration units. Precincts belong to counties, and the county portion of a precinct identity is essential. `WAKE - 01-01` is a safer key than `01-01` alone because another county can use the same code.

**Congressional district.** A district that elects one member of the U.S. House of Representatives.

**State House district.** A district that elects one member of the North Carolina House of Representatives.

**State Senate district.** A district that elects one member of the North Carolina Senate.

**Census block.** The smallest Census geography. Blocks are useful here because precinct and district boundaries can both be related to them. That makes a block a practical bridge between two geographic systems.

Precincts nest inside counties, but political districts do not have to follow precinct lines. A congressional or legislative boundary can pass through a precinct. When that happens, the precinct's single reported vote total must be divided somehow if the atlas is to estimate results for both districts.

### Change and connection

**Redistricting.** Redrawing electoral districts, normally after the decennial census but sometimes because a court or legislature replaces a plan.

**District-line vintage.** The particular version and year of district boundaries: for example, the 2022 court-ordered lines, the 2024 lines, or the enacted 2026 congressional plan. “Vintage” says which boundary set is being used, not which election year is displayed.

**Crosswalk.** A table connecting identifiers or geographic pieces in one system to another. In this project a crosswalk may connect an election-era precinct to 2020 Census blocks, a block to a district, or a stable December 2025 precinct key to the live August 2026 display geometry.

The same precinct code can change meaning because local election administrators can redraw or rename precincts while retaining familiar numbering. A crosswalk therefore needs county, vintage, geometry, aliases, and sometimes population weights; matching on a code alone is unsafe.

> **Why this matters:** Comparing “Precinct 12” in two years is meaningful only after checking that both records describe the same place—or after documenting how one was translated into the other.

### Population measures

**Voting-age population (VAP).** Everyone age 18 or older, regardless of citizenship or registration. The shattering pipeline uses VAP as a geographic weight because blocks with more voting-age residents are a more plausible location for more of a precinct's votes than blocks with none.

**Citizen voting-age population (CVAP).** Citizens age 18 or older. The interface can show 2020–2024 ACS/RDH CVAP context in demographic cards and hover totals. It does **not** replace the VAP weighting used by the election-allocation pipeline.

Neither VAP nor CVAP is turnout. Neither tells the program which people voted or how they voted.

### Authority and evidence

**Certified election result.** A result officially finalized by the responsible election authority. In the atlas, certified or official county totals can be displayed directly or summed, while a district total reconstructed from precinct geography is an estimate even if its statewide total is conserved.

**Geographic allocation or estimate.** A calculated placement of votes among map areas when the source return and target boundaries do not line up. VAP-weighted shattering is one such method.

**Data provenance.** The record of where data came from and what transformations it received. Examples in slice metadata include `source`, `bridge`, `match_crosswalk`, `nongeo_allocation_mode`, `match_coverage_pct`, district-line labels, and calibration flags. `js/atlas-provenance.js` translates these into categories such as Certified total, Official benchmark, Calibrated estimate, High-coverage estimate, Bridged precinct, County fallback, and Modeled scenario.

Trustworthy civic maps identify source, method, uncertainty, and modeled values because correct statewide arithmetic alone cannot prove correct local placement.

---

## 3. Understanding votes, margins, categories, and colors

This is the most important section to understand before drawing a political conclusion from the map.

### Vote share is not margin

Suppose a place reports:

- Democratic candidate: 55 votes
- Republican candidate: 45 votes
- Total two-party votes: 100

The Democratic share is 55%, the Republican share is 45%, and the Democratic margin of victory is **10 percentage points**. Under the atlas's signed convention, the signed R−D margin is `45% − 55% = −10 points`. Therefore the result is **D+10**, not D+55.

These measurements answer different questions:

| Measure | Meaning | Example |
| --- | --- | ---: |
| Vote share | A candidate's votes divided by the selected denominator | 55 / 100 = 55% |
| Raw vote margin | Winner's votes minus loser's votes | 55 − 45 = 10 votes |
| Percentage-point margin | Difference between the two vote shares | 55% − 45% = 10 points |
| Percentage change | Relative change from an earlier value | 50 votes to 55 votes is a 10% increase |
| Total turnout | All votes counted in the result | 100 votes here |

### The atlas's actual denominator

The live core function is `signedMarginPctFromVotes(demVotes, repVotes, totalVotes)` in `js/atlas-core.js`:

```text
(Republican votes − Democratic votes) / total_votes × 100
```

When `total_votes` equals Democratic + Republican + Other, **other-party votes are included in the denominator**. That is the normal path for contest slices, county sums, district rows, shifts, and much of the display. `js/atlas-display.js` uses the same all-vote denominator for party percentages and margins. For example, the current 2024 presidential slice stores Anson County as 5,253 D, 5,525 R, 97 Other, 10,875 total; its margin is `272 / 10,875 = 2.5011%`.

`js/atlas-comparison.js` has a careful fallback: `signedMarginPct()` uses a supplied positive total, but if none is usable it falls back to `D + R`. Consequently, the safest description is **R−D as a percentage of the reported total when that total is available**, not an assumption that every screen always uses a two-party denominator.

The project previously called this quantity “two-party margin.” That phrase is imprecise for the production code whenever Other votes are present. Current documentation instead describes it as the difference between the Republican and Democratic shares of the reported total. The 55–45 teaching example is a true two-party case, so the arithmetic is still correct.

### Signed margin convention

The atlas commonly stores or derives a signed number:

```text
signed margin = Republican share − Democratic share
```

- `+12` means R+12.
- `−7.5` means D+7.5.
- `0` means tied.

Signed margins make changes easy to calculate because movement toward Republicans is positive and movement toward Democrats is negative.

### Competitiveness categories

The category uses the **absolute** displayed margin, regardless of winner. `competitivenessMarginValue()` rounds to two decimal places before classification so the tier agrees with the value readers see. The 5.50-point Likely boundary is intentional.

| Absolute margin | Category |
| ---: | --- |
| Below 0.50 points | Tossup |
| 0.50–0.99 | Tilt |
| 1.00–5.49 | Lean |
| 5.50–9.99 | Likely |
| 10.00–19.99 | Safe |
| 20.00–29.99 | Stronghold |
| 30.00–39.99 | Dominant |
| 40.00 or more | Annihilation |

Examples: D+0.30 is Tossup; R+0.75 is Tilt Republican; D+3.20 is Lean Democratic; R+7.00 is Likely Republican; D+14.00 is Safe Democratic; R+24.00 is Stronghold Republican; D+35.00 is Dominant Democratic; and R+42.00 is Republican Annihilation.

These are descriptive labels created by the atlas. They are not classifications from the North Carolina State Board of Elections.

#### Why “Annihilation” is the terminal tier

The term is intentionally dramatic. Functionally, it separates the most one-sided results from already large 30–39.99-point margins and gives the darkest red and blue a clear endpoint. In a strict two-party example, a 70%–30% result is a 40-point margin; 75%–25% is a 50-point margin. Thus:

- 70% R and 30% D → R+40 → Republican Annihilation.
- 72% D and 28% R → D+44 → Democratic Annihilation.
- 65% D and 35% R → D+30 → Democratic Dominant, not Annihilation.

“Annihilation” describes only one contest's margin. It does not say the losing party has no voters, organization, influence, or future prospects. More conventional civic-writing labels might be “Overwhelming,” “Landslide,” or “Solid.” This project instead completes its unusually detailed scale as Tossup → Tilt → Lean → Likely → Safe → Stronghold → Dominant → Annihilation.

A search of README, changelog, code comments, tests, and Git history finds the label present from the initial repository commit, but no recorded explanation of why the creator originally chose that word. The functional explanation above is therefore an interpretation, not a documented statement of authorial intent.

### Exact current margin colors

`categoryColorForMargin()` in `index.html` is the current production authority. The live function ignores older color values that may still be embedded in generated JSON and computes colors again. The default palette is the Atlas/DRA compromise:

| Party | Category | Margin range | Description | Hex | Plain-language meaning |
| --- | --- | ---: | --- | --- | --- |
| Both | Tossup | <0.50 | Near white | `#f7f7f7` | Essentially tied |
| Republican | Tilt | 0.50–0.99 | Very pale red | `#f4c9c5` | Tiny Republican lead |
| Republican | Lean | 1.00–5.49 | Pale red | `#fcae91` | Small Republican lead |
| Republican | Likely | 5.50–9.99 | Coral red | `#f7634b` | Moderate Republican lead |
| Republican | Safe | 10.00–19.99 | Strong red | `#e93a2d` | Clear Republican lead |
| Republican | Stronghold | 20.00–29.99 | Deep red | `#cb181d` | Very large Republican lead |
| Republican | Dominant | 30.00–39.99 | Dark red | `#a50f15` | Extremely large Republican lead |
| Republican | Annihilation | ≥40.00 | Darkest red | `#67000d` | Terminal Republican tier |
| Democratic | Tilt | 0.50–0.99 | Very pale blue | `#c7ddf0` | Tiny Democratic lead |
| Democratic | Lean | 1.00–5.49 | Pale blue | `#9ecae1` | Small Democratic lead |
| Democratic | Likely | 5.50–9.99 | Medium-light blue | `#5b9fd0` | Moderate Democratic lead |
| Democratic | Safe | 10.00–19.99 | Medium blue | `#3f8fc9` | Clear Democratic lead |
| Democratic | Stronghold | 20.00–29.99 | Deep blue | `#2876b5` | Very large Democratic lead |
| Democratic | Dominant | 30.00–39.99 | Dark blue | `#08519c` | Extremely large Democratic lead |
| Democratic | Annihilation | ≥40.00 | Darkest blue | `#08306b` | Terminal Democratic tier |

An older changelog entry says an unchanged “original Atlas” palette can be selected under More. In the current `index.html`, however, there is no DRA-colors control, persisted setting, or alternate standard-palette function. Only the compromise palette and colorblind palette are wired into `colorForMarginMode()`. Treat the optional-original-palette statement as historical unless that control is restored. Several offline generators also retain older hex tables; those do not control current live fills.

#### Original Atlas palette compared with the current palette

The original scale can be recovered exactly from the parent of Git commit `86f03181` (`Add optional DRA partisan palette`) and is still visible in older/offline color helpers such as `scripts/build_nc_elections_aggregated.py`. It used the same category thresholds as today. The comparison below shows what changed when the project moved to the current Atlas/DRA compromise.

| Category | Range | Original Republican | Current Republican | Original Democratic | Current Democratic |
| --- | ---: | --- | --- | --- | --- |
| Tossup | <0.50 | `#f7f7f7` | `#f7f7f7` | `#f7f7f7` | `#f7f7f7` |
| Tilt | 0.50–0.99 | `#fee8c8` | `#f4c9c5` | `#e1f5fe` | `#c7ddf0` |
| Lean | 1.00–5.49 | `#fcae91` | `#fcae91` | `#c6dbef` | `#9ecae1` |
| Likely | 5.50–9.99 | `#fb6a4a` | `#f7634b` | `#9ecae1` | `#5b9fd0` |
| Safe | 10.00–19.99 | `#ef3b2c` | `#e93a2d` | `#6baed6` | `#3f8fc9` |
| Stronghold | 20.00–29.99 | `#cb181d` | `#cb181d` | `#3182bd` | `#2876b5` |
| Dominant | 30.00–39.99 | `#a50f15` | `#a50f15` | `#08519c` | `#08519c` |
| Annihilation | ≥40.00 | `#67000d` | `#67000d` | `#08306b` | `#08306b` |

The original Republican scale was already a sequential ColorBrewer-like red ramp, but its Tilt color (`#fee8c8`) could appear cream or peach rather than red depending on the screen and basemap. It might have remained technically usable, but `#f4c9c5` communicates “very light Republican red” more consistently. The clearest Democratic problem was that original Lean (`#c6dbef`) was so light that it could look like original Tilt (`#e1f5fe`), especially at precinct scale or on a bright display. The finalized ramp effectively moved the old Lean shade down into the Tilt role—the new Tilt is `#c7ddf0`, only one small RGB step from `#c6dbef`—and assigned Lean the meaningfully darker `#9ecae1`. Likely, Safe, and Stronghold were adjusted along with it so each increase in margin remains visibly distinct on desktop and mobile. Dominant and Annihilation are unchanged for both parties.

The Democratic reassignment continues upward. Original Democratic Likely (`#9ecae1`) became the finalized Lean color exactly. Finalized Likely (`#5b9fd0`) was then placed between that Lean and the deeper Safe tier, while finalized Safe (`#3f8fc9`) was made substantially darker than original Safe (`#6baed6`). This creates a readable progression from a genuinely competitive Lean, through an intermediate Likely, to a clearly established Safe result. Without that redistribution, the light original Lean/Likely pair consumed too much of the pale end of the scale and compressed the visual difference among politically different margins.

The Republican Likely and Safe changes were intentionally smaller because the original red sequence already separated those tiers reasonably well. Likely moved from `#fb6a4a` to the slightly deeper, less orange `#f7634b`; Safe moved from `#ef3b2c` to `#e93a2d`. These adjustments keep the hues recognizably red, reduce the orange cast, and balance their apparent strength against the newly deepened Democratic Likely and Safe colors without disturbing Republican Stronghold, Dominant, or Annihilation.

The short-lived optional DRA palette introduced by that commit was a third scale, not the same as either column above. It used vivid values such as Safe Republican `#ff2020` and Safe Democratic `#2020ff`. The project creator's stated reason for moving on from it is that the DRA colors were too strong for the finished atlas. The current compromise therefore keeps the DRA experiment's clearer separation between categories while returning to the original Atlas palette's more restrained civic-map tone. Later cleanup removed the live toggle. Thus “original,” “optional DRA,” and “current compromise” are three distinct historical concepts.

### What red and blue mean—and do not mean

In Margins mode, blue means a Democratic advantage, red means a Republican advantage, near-white means a very close result, and darkness means a larger percentage-point margin. Darkness does **not** mean more turnout, more people, a larger raw vote margin, a larger land area, or greater political importance.

A geographically large rural county can have fewer voters than a geographically small urban county. A choropleth colors land, not people.

### Colors in each visualization mode

**Margins.** Hue identifies the leading party; darkness identifies absolute margin tier. `colorForMarginMode()` chooses the standard or accessible ramp.

**Winners.** `colorForWinnerMode()` deliberately removes margin detail. Standard colors are Republican `#dc2626`, Democratic `#2563eb`, and tie `#9ca3af`. In colorblind mode they are Republican orange `#d65300`, Democratic blue `#0072b2`, and the same gray tie.

**Shift.** The formula is:

```text
new signed R−D margin − old signed R−D margin
```

Positive is a Republican-direction shift; negative is a Democratic-direction shift. D+10 (`−10`) to D+4 (`−4`) equals `+6`, a six-point Republican shift. R+3 (`+3`) to D+2 (`−2`) equals `−5`, a five-point Democratic shift. A county can remain Democratic but appear red because it became more Republican.

`colorForShiftMode()` uses near-white `#f8fafc` below 0.5 point, then seven directional bins at 0.5, 1, 5, 10, 15, 20, and 25 points:

| Shift size | Republican direction | Democratic direction |
| ---: | --- | --- |
| 0.50–0.99 | `#fee2e2` | `#dbeafe` |
| 1.00–4.99 | `#fecaca` | `#bfdbfe` |
| 5.00–9.99 | `#fca5a5` | `#93c5fd` |
| 10.00–14.99 | `#f87171` | `#60a5fa` |
| 15.00–19.99 | `#ef4444` | `#3b82f6` |
| 20.00–24.99 | `#dc2626` | `#2563eb` |
| ≥25.00 | `#7f1d1d` | `#1e3a8a` |

**Flips.** A flip is a change from one party winner to the other, calculated by `winnerFromSignedMarginPct()` and `flipInfo()` in `js/atlas-election.js`. Standard destination colors are R `#dc2626`, D `#2563eb`, and no/tie `#e2e8f0`; colorblind destination colors are orange `#d65300` and blue `#0072b2`. The color communicates destination party, not the new margin's size.

**Compare.** Compare uses the same diverging colors as Shift. `compareSignedMargins()` in `js/atlas-comparison.js` calculates **primary minus comparison**. The UI describes this as `comparison → primary`. If President is R+4 (`+4`) and Governor is D+2 (`−2`), a comparison from President to Governor means Governor is primary and President is comparison: `−2 − (+4) = −6`, or six points more Democratic.

**Demographics.** These colors classify the largest reported race/ethnicity share, with separate colors for white, Black, Hispanic, Native, Asian, Pacific Islander, multiracial, mixed, and narrow-majority combinations. They describe population composition, not partisan support. `classifyDemographicDominance()` and `colorForDemographicsMode()` contain the exact palette and a high-contrast option.

**Population Change.** These county-only colors describe 2020–2025 population change. Browns show decline, near-white shows little change, and greens show growth. Percent and absolute-number scales are separate (`colorForPopulationChangeMode()` and `colorForPopulationChangeAbsMode()`). They do not show partisan movement.

**Turnout-intensity opacity.** When enabled, hue still describes the selected election mode, while opacity is assigned by turnout quantiles. `js/atlas-turnout.js` uses 20th, 40th, 60th, and 80th percentile breakpoints. A pale-looking place can therefore be low-turnout under the opacity setting rather than politically close.

### Accessibility and colorblind mode

The accessibility ramp keeps Democratic results blue but changes Republican results to orange. Its exact Tilt → Annihilation colors are:

| Party | Tilt | Lean | Likely | Safe | Stronghold | Dominant | Annihilation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Republican | `#ffd29a` | `#f6ad55` | `#f58a2a` | `#ed6a00` | `#d65300` | `#b33c00` | `#8c2d04` |
| Democratic | `#bae6fd` | `#60a5fa` | `#0ea5e9` | `#0284c7` | `#0369a1` | `#075985` | `#063f5c` |

Accessible Tossup is slate `#cbd5e1`. The underlying votes, sign, and category do not change. The interface supplements color with legend text, R/D labels, category labels, candidate and vote numbers, boundary/hover outlines, keyboard focus rings, and live screen-reader summaries. It does not currently add hatch patterns to election fills.

### How to read any atlas map correctly

1. Check the active geographic view.
2. Check the selected contest and year.
3. Check the visualization mode.
4. Read that mode's legend.
5. Decide whether hue means winner, shift direction, demographics, or population change.
6. Decide what darkness means.
7. Check whether turnout opacity is enabled.
8. Check whether the result is official, summed, geographically estimated, calibrated, or modeled.
9. Hover or select the geography and read the numbers instead of relying on color alone.

> **Common mistakes**
>
> - A dark color does not necessarily mean many voters.
> - A blue demographic color does not necessarily mean a Democratic result.
> - A red area in Shift mode may still have been won by a Democrat.
> - A 55% vote share does not mean a 55-point victory.
> - Land area does not equal population or political influence.
> - A geographically reallocated or modeled result is not automatically a certified result.

---

## 4. High-level technical architecture

The atlas is primarily a **static, client-side Mapbox GL application**. There is no normal application server calculating results on each request. GitHub Pages or another static host publishes HTML, CSS, JavaScript, JSON, CSV, and GeoJSON. The browser loads those files, performs selected sums and comparisons, and styles Mapbox layers.

```text
raw election returns + geographic sources
                    ↓
          cleaning and normalization
                    ↓
        precinct matching and crosswalks
                    ↓
      generated JSON slices and manifests
                    ↓
          browser loading and caching
                    ↓
       county or regional calculations
                    ↓
      Mapbox styling and interactive panels
```

The responsibilities are:

- `index.html`: page structure plus a large inline application script. It creates the map, owns most state, coordinates loading, adds layers, handles controls, calculates many display values, and builds panels. Legend category markup now lives in `js/atlas-legend.js`; broader modularization remains incomplete.
- `css/atlas-main.css`: layout, desktop/mobile controls, cards, legends, focus states, accessibility, and responsive presentation.
- `js/atlas-*.js`: reusable pure or mostly pure helpers, exposed on `window.Atlas…` and tested with Node.
- `data/`: published contest slices, manifests, geometry, crosswalks, demographic inputs, and report artifacts.
- `scripts/`: offline ingestion, normalization, crosswalk construction, shattering, calibration, splitting, validation, and audits.
- Manifests: catalogs that say which contest slices exist and what filenames to load.
- Generated slices: small contest/year payloads that avoid sending the enormous aggregated file for every selection.
- GeoJSON/vector geometry: shapes to draw. Current configuration has tileset support, but the configured `url` fields are blank, so checked-in GeoJSON is the active source path.
- Browser caches: Maps of resolved payloads and in-flight Promises prevent repeated requests and duplicate simultaneous work.
- URL state: share-only query parameters capture view, contest, mode, line year, focus, comparison, scenario, and selected settings; the app consumes and then clears them from the visible address bar.

Offline preparation reconstructs and validates data. Published files are served unchanged. Browser calculations include county sums, statewide sums, regions, comparisons, shifts, scenarios, and styling. District reconstruction is normally **not** performed from scratch in the browser; production district totals arrive in precomputed slices.

---

## 5. Frontend startup

From opening `index.html` to an interactive county map:

1. The page loads Mapbox GL JS 3.0.1, Turf 6.5.0, Papa Parse 5.4.1, the stylesheet, and the `atlas-*.js` helpers. Mapbox draws and interacts with vector/GeoJSON maps, Turf computes bounding boxes for zooming, and Papa Parse reads CSV fallbacks and auxiliary files. Papa Parse is included twice in the current HTML; this is redundant but not central to the data flow.
2. `js/atlas-data.js` supplies base-path detection. On a `github.io` host it prefixes local paths with the repository segment; locally it uses relative paths.
3. `withCacheBuster()` appends the current `DATA_CACHE_BUSTER` query value to requests that do not already have one. This helps browsers and CDNs fetch refreshed static files.
4. The `CONFIG` object defines county, precinct, district, demographic, CVAP, contest, manifest, report, and crosswalk paths; initial center/zoom; statewide bounds; and the precinct polygon zoom threshold.
5. The browser creates a Mapbox map using the Light v11 basemap, North Carolina center, and drawing-buffer support for exports.
6. Load/style-load/window-load listeners and a short style poll all call `startAtlasOnce()`. Its guard ensures `init()` runs only once and only after the style is ready.
7. `init()` loads county GeoJSON (`data/census/tl_2020_37_county20.geojson`, with a local-layout fallback), adds the county source and layers, wires search, map events, quick regions, accessibility, and mobile controls, and fits North Carolina bounds.
8. The atlas deliberately defers heavy hydration. The county shell becomes interactive before manifests, all district sources, demographics, and auxiliary information finish loading.
9. `scheduleDeferredAtlasHydration()` waits for map idle or a timeout, then calls `hydrateAtlasDataAndDistrictSources()`.
10. Hydration loads `data/contests/manifest.json` and the 2022, 2024, and 2026 district manifests in parallel. It builds the contest picker from available entries, loads optional district descriptions and demographics, and then loads district GeoJSON and descriptive CSVs.
11. `restoreUIState()` applies a shared URL if present. Otherwise the picker remains ready for the user's selection; manifests enable lazy loading rather than forcing all contest results into memory.
12. `finalizeAppPostHydration()` applies opacity settings, starts nonblocking preloads for common contest slices and modeled-Senate inputs, and leaves large precinct polygons lazy until the overlay and zoom level require them.

This progressive sequence matters because downloading every precinct polygon, contest, trend, and district file before showing the map would make a static civic site feel broken on slower connections.

---

## 6. Frontend organization

The local modules have focused roles:

- `js/atlas-core.js`: county/precinct token normalization, alias candidates, county-scoped crosswalk indexes, signed-margin arithmetic, and total-preserving vote rescaling.
- `js/atlas-data.js`: base paths, cache-buster URLs, retrying fetches, resolved/in-flight cache behavior, and mapping contest payload rows into the older dynamic-column shape used by `index.html`.
- `js/atlas-display.js`: stable rounding, close-race precision, percentages, margin display, compact totals, signed deltas, and HTML escaping.
- `js/atlas-election.js`: vote-set finalization, swing adjustments, contest-key parsing, winner from signed margin, and flip detection.
- `js/atlas-legend.js`: deterministic legend category definitions and HTML for margins, winners, flips, shifts, comparisons, demographics, and population change.
- `js/atlas-manifest.js`: filters invalid/uncontested entries and connects old named judicial contests to stable seat families.
- `js/atlas-classification.js`: political trajectory labels, long- and short-term direction, and county growth-type labels.
- `js/atlas-comparison.js`: parses contest IDs, calculates signed margins, performs primary-minus-comparison subtraction, rounds displayed comparisons, and chooses a default comparator.
- `js/atlas-regions.js`: normalizes county sets and sums region totals, preferring attached official county totals where available.
- `js/atlas-trends.js`: sorts histories and computes long-term, recent, and cycle-to-cycle changes.
- `js/atlas-turnout.js`: creates turnout quantiles and Mapbox opacity expressions for counties, districts, and precincts.
- `js/atlas-modeling.js`: reusable statistical helpers for synthetic contest baselines, reliability, shrinkage, turnout, candidate effects, and reconciliation.
- `js/atlas-provenance.js`: turns metadata into reader-facing authority and confidence descriptions and comparison cautions.
- `js/atlas-url-state.js`: validates and parses share-link parameters.
- `js/atlas-custom-region.js`: validates a saved county group and derives its map bounds.

This is not React, Vue, Svelte, or another component framework. It is a conventional HTML page with globals, DOM handlers, Mapbox layers, and extracted helper modules. `index.html` remains the orchestration center and is currently much larger than any module.

---

## 7. Frontend state and interaction flow

Important state in `index.html` includes `currentView`, `currentContestMeta`, `currentVizMode`, `currentDistrictLinesYear`, `precinctsEnabled`, pinned/focused geography, `comparisonContestValue`, `scenarioSwingPct`, modeled-contest overrides, the custom region, colorblind/demographic/opacity settings, slice caches, geometry caches, and URL restoration state.

### What common actions do

1. **Select an election.** The selector increments a selection sequence and calls `applyContest()`. The key is split at its last underscore into contest type and year. County view calls `applyCountyContest()`; district views call `applyDistrictContest()`. The layer gets a new Mapbox color expression, and summaries, hover data, trends, provenance, and optional precinct detail are refreshed.
2. **Switch Counties to a district view.** `setMapView()` removes the prior primary fill/stroke layers, adds the chosen district layers, repopulates the picker from the active district manifest, preserves the contest when it exists on the new view, and can carry a pinned selection across scopes through a crosswalk. If 2026 lines are selected and the user enters House or Senate, the line year falls back to 2024 because only congressional 2026 data is production-supported.
3. **Enable precincts.** The app first uses centroids at statewide/low zoom. At or above the polygon threshold, `ensurePrecinctSourceLoaded()` lazily fetches `data/2026Voting_Precincts.geojson`. `updatePrecinctVisibility()` decides whether dots or polygons are visible.
4. **Choose a visualization mode.** `switchVizMode()` changes `currentVizMode`, rebuilds the legend, clears stale comparison cards when appropriate, and reapplies the current contest. Margins, Winners, Shift, Flips, Compare, Demographics, and Population Change each route to different color logic.
5. **Hover.** Pointer handlers query the active layer, apply a feature-state or filter outline, and populate the compact tooltip. Pointer work is throttled with animation frames/timers to reduce flicker.
6. **Pin/select.** A county or district click records the focus, builds deeper sidebar/pinned cards, and loads trend or comparison context. Precinct clicking is intentionally passive in current precinct mode; hover is the main interaction, although search/share restoration can still focus precincts.
7. **Change district-line year.** `setDistrictLinesMode()` loads or reuses line-specific geometry, changes the active manifest/directory, keeps line-year-keyed district caches warm, and reapplies the selected contest. The 2026 option uses `data/district_contests_2026_lines` for Congress and 2024 production slices for legislative chambers.
8. **Copy a share link.** `collectURLStateFromUI()` serializes nondefault state. `writeURLStateFromUI()` generates a URL without rewriting the visible address during ordinary browsing. Clipboard API and a textarea fallback are supported.
9. **Export CSV or JSON.** `buildActiveExportRows()` converts the active county or comparison snapshot to records. `downloadActiveExport()` creates a Blob and browser download; there is no server export endpoint. District non-comparison export can be more limited, as the code notes when only turnout totals are available.

### Protection against stale asynchronous work

The page uses several complementary safeguards:

- `contestSelectionSeq` and an `isStaleSelection()` callback stop an older contest request after the user chooses a newer one.
- `comparisonRequestId`, `districtHoverRequestId`, `districtSidebarRequestId`, `bellwetherRequestId`, `analyticsPanelsRequestId`, and similar counters make late responses harmless.
- Resolved caches avoid refetching; in-flight Promise maps deduplicate concurrent requests for the same path or slice.
- Cache keys include view, mode, line year, palette, precinct state, overlays, and model/scenario signatures so one configuration is not reused as another.
- `lastContestApplySig` provides a fast path for a genuinely identical selection.

These are important in a map because a fast click can otherwise let a slow old fetch repaint the screen after a newer choice.

---

## 8. Data discovery and loading

### Production catalogs and files

- `data/contests/<contest_type>_<year>.json`: precinct-keyed rows for one contest and year, often with metadata and an optional `county_totals` sidecar.
- `data/contests/manifest.json`: production catalog for county/precinct choices.
- `data/district_contests/<scope>_<contest_type>_<year>.json`: production results on 2022 lines.
- `data/district_contests/manifest.json`: 2022-line catalog.
- `data/district_contests_2024_lines/`: production 2024-line slices and manifest.
- `data/district_contests_2026_lines/`: production congressional 2026-line slices and manifest.
- `data/nc_elections_aggregated.json`: large legacy/fallback aggregate, not the preferred normal contest-switch path.
- `data/county_demographics_2020_2024_cvap.json`, `data/precinct_demographics_2020_vap.csv`, and `data/cvap_aggregates/`: demographic context.
- `data/census/`, `data/tileset/`, and `data/2026Voting_Precincts.geojson`: geometry.

`loadContestSlice()` is manifest-aware: it finds the recorded filename, fetches the payload, maps rows into dynamic keys, attaches official county totals when present, and caches the result. If a presidential JSON fast path fails, it can parse the configured OpenElections CSV fallback. If manifests are unavailable, the large aggregated data remains a compatibility fallback.

`loadCountyContestSlice()` intentionally calls the full precinct slice for real contests. `data/county_contests/` is not the production authority, despite its presence in the repository and configuration. Modeled contests are the exception: they generate compact county outputs in memory.

`loadDistrictSlice()` chooses line-specific candidate paths, caches by `linesYear|scope_contest_year`, and normally returns a prebuilt payload. For 2022-line congressional contests from 2020 onward, `getPreferredDistrictSlicePaths()` first attempts the configured calibrated directory `data/district_contests_2020_2024/`; that directory is not present in the current checkout, so the loader continues to the normal `data/district_contests/` slice. For 2022 lines only, it can then lazily fall back to `data/nc_district_results_2022_lines.json` if no slice loads.

Candidate names normally travel in rows. `getContestCandidates()` loads a precinct slice as a fallback when an older district file has blank candidate metadata. Manifests and slice `meta` also carry coverage, sources, allocation methods, and calibration notes.

Directories such as `data/district_contests_dra_review`, rebuild staging folders, `data/district_contests_urban_sf1_*`, and most of `data/reports/` are audits, experiments, or promotion candidates. They are not live inputs unless `CONFIG` or loading code explicitly points to them. This separation is essential: an audit output can conserve votes and still fail geographic review.

---

## 9. Election aggregation

### A. Raw-result normalization

OpenElections/NCSBE-style source rows identify year, office, county, precinct, candidate, party, and votes. `scripts/build_nc_elections_aggregated.py` filters known offices, groups by county and precinct, sums Democratic, Republican, and all other parties, captures candidate names, and calculates total, raw R−D margin, signed percent margin, winner, and a legacy color. `scripts/build_district_contests_from_batch_shatter.py` handles the more complete current slice pipeline, including office aliases, judicial party overrides, precinct aliases, non-geographic rows, and district allocation.

The old `scripts/aggregate_elections.py` simply merges separate race JSON files into `nc_elections_aggregated.json`. It is a legacy consolidation path, not the preferred manifest/slice builder.

### B. Precinct contest slices

The durable row key is `COUNTY - PRECINCT`. County is part of identity because codes repeat across counties. `build_precinct_contest_payload()` rounds allocated precinct floats while preserving each county/party total through largest-remainder rounding, then emits votes, total, candidates, raw margin, percent margin, winner, and color. `update_contests_manifest()` records the file, year, contest type, row count, totals, and whether both major-party buckets are present.

One small JSON slice is much faster for the browser than loading a statewide all-years aggregate and scanning it for every click.

### C. Browser-side county aggregation

`buildCountyAggregateBundleFromSliceRows()` groups every selected precinct row by the county portion before ` - `. It sums D, R, Other, and total; computes each county's signed margin; and sums a statewide result. If the slice includes authoritative `county_totals`, those replace the corresponding precinct sums. `ensureCountyAggregateBundle()` caches this bundle by contest and year.

The same arithmetic supports statewide cards, trends, Compare, named regions, and custom county regions. This is grouping and addition. It does not reconstruct district geography.

### D. Offline district aggregation and “shattering”

Production district results are generally prepared before deployment:

```text
election-vintage precinct result
        ↓
precinct-name normalization and alias matching
        ↓
election-vintage precinct-to-block relationship
        ↓
VAP-weighted shattering of split precincts
        ↓
block-to-selected-district assignment
        ↓
district totals
        ↓
district JSON slice + manifest
```

“Shattering” means dividing a precinct total among smaller geographic pieces. `scripts/shatter_precinct_votes_vap.py` gives each block the precinct's votes multiplied by that block's share of precinct VAP. It uses Decimal arithmetic, retains fractional votes through block allocation, assigns any tiny arithmetic residual to the largest-weight block, audits the precinct sum, and rounds only when aggregating districts.

This does **not** locate individual voters or ballots. It estimates the geographic distribution of a pooled precinct result using population weights.

`scripts/build_district_contests_from_batch_shatter.py` applies that machinery separately to Democratic, Republican, and Other totals, adds unmatched fallbacks, creates metadata such as match coverage and line vintage, and writes scope-specific slices.

### E. Changing boundary vintages

Different election eras require different bridges. `VINTAGE_MATCH_CROSSWALKS` selects the closest practical source: SBE 2006 and Census 2000/NHGIS bridges for early years; SBE 2012/2014/2016/2017 vintages for the middle years; SBE 2020, 2022, and 2024 for modern years; and the December 2025 OneMap basis for current normalization.

Keep these concepts separate:

- **Election-year precinct geography:** the units used to report that election.
- **Historical SBE/VTD geography:** official or Census approximations used to interpret older keys.
- **Canonical allocation basis:** December 2025 OneMap/SBE precincts connected through `data/crosswalks/block20_to_onemap_2025_12.csv`.
- **Live precinct display geometry:** the August 2026 SBE file `data/2026Voting_Precincts.geojson`, reached with `precinct_stable_to_sbe_2026_08_24_best_old_to_new.csv`.
- **District boundaries:** separate 2022, 2024, and congressional 2026 block assignments and GeoJSON.
- **NHGIS bridges:** 2000-block → 2010-block → 2020-block relationships used to carry early geography forward.

For especially difficult 2000–2004 urban allocations, a separate SF1/historical-plan process uses Census 2000 VTD/VAP, official historical plan block assignments, voter-history code evidence, plan cells, and carefully documented aliases. Its builders and audits live around `scripts/build_urban_sf1_historical_legislative_weights.py`, `scripts/audit_urban_sf1_*`, and `data/reports/urban_sf1_historical/`. These are specialized historical treatments, not the generic path for every election.

### F. Non-geographic votes

Election exports can include absentee, one-stop/early, provisional, curbside, transfer, mail, and administrative buckets. A label such as `ABSENTEE` is a method or reporting bucket, not a polygon.

`is_non_geographic_precinct()` identifies these rows. The default `precinct_candidate` method in `allocate_non_geo_by_candidate()` distributes a candidate's non-geographic county votes across that candidate's geographic precinct performance shares within the same county. If those shares are unavailable, it can fall back to county geographic shares. The alternate `county_weights` mode carries non-geographic party totals separately and allocates them to districts using county/district population weights.

These methods preserve votes within the relevant county and are marked in provenance, but they remain estimates.

### G. Conservation, calibration, and validation

**Vote conservation** asks whether all input votes are still present after allocation. `shatter_votes()` has a precinct zero-sum audit. County-preserving largest-remainder rounding distributes leftover whole votes to the largest fractional remainders so integer rows match the rounded county target.

**County constraints** stop a crosswalk or fallback from leaking votes across county lines. Recent bridge work clamps OneMap shares to source counties.

**Calibration** adjusts or replaces estimated district rows using trusted official targets such as NCGA StatPacks or NCSBE precinct-sort plan reports. A calibrated estimate can match an official district benchmark while still depending on allocation for other contexts.

**Match coverage** reports the share of source precinct keys matched before allocation. It is not a probability that every vote is correct. Unmatched reports identify keys and counties that needed fallbacks.

**Geographic sanity checks** inspect whether plausible local patterns and known components land in the right districts. This is why statewide conservation alone is insufficient: every vote can be preserved while being assigned to the wrong side of a district boundary.

---

## 10. Rendering results

The browser combines three different kinds of information:

- **Election-result data:** how many votes each bucket received.
- **Geometry data:** where the polygon or point is drawn.
- **Crosswalk data:** how identifiers or geographic pieces relate across systems.

For counties, `applyCountyContest()` loads rows, applies any model/swing adjustments, builds county and statewide totals, optionally builds precinct lookups, fetches prior data for Shift/Flips, and creates a Mapbox `match` expression assigning a color to each county name. For district views, `applyDistrictContest()` loads a precomputed line-specific node and creates a district-number expression.

The rendering sequence is:

1. Read D, R, Other, and total.
2. Calculate shares and signed R−D margin using the available total.
3. Identify R, D, or tie.
4. Round the display margin and classify its absolute value.
5. Choose the active mode's standard or accessible color.
6. Install a Mapbox fill-color expression on the county, precinct, congressional, House, or Senate layer.
7. Apply turnout/overlay opacity separately.
8. Keep stroke, casing, hover, and selected outlines above the fill.
9. Rebuild the legend and statewide summary.
10. Use the same underlying record for hover, pinned details, trends, flips, and comparisons.

---

## 11. Worked example: 2024 President

### Counties view

1. `data/contests/manifest.json` contains `{ year: 2024, contest_type: "president", file: "president_2024.json" }`.
2. Selecting `president_2024` calls `applyContest()`, which parses `president` and `2024` and routes to `applyCountyContest()`.
3. `loadCountyContestSlice()` calls manifest-aware `loadContestSlice()` and fetches `data/contests/president_2024.json`.
4. `AtlasData.mapContestPayloadRows()` maps each row to the dynamic fields expected by the large inline application. The slice metadata records an SBE-2024-to-OneMap-2025-12 VAP bridge and county-party geographic allocation for non-geographic votes.
5. `buildCountyAggregateBundleFromSliceRows()` groups `COUNTY - PRECINCT` rows into 100 county totals. The slice's `county_totals` object, when attached, supplies the authoritative county override.
6. County totals are summed into statewide D, R, Other, and total values.
7. `signedMarginPctFromVotes()` calculates `(R − D) / total × 100`; `marginPctDisplayValue()` provides reader-facing precision.
8. `competitivenessMarginValue()` rounds the displayed absolute margin and the category functions assign Tossup through Annihilation.
9. `colorForMarginMode()` calls the current compromise or accessible palette.
10. A Mapbox `match` expression updates `county-fill`; separate layers draw labels and outlines.
11. Hover and pinned panels read the county record, candidate names, statewide context, trends, provenance, and any previous-cycle comparison.

### State House view

1. `setMapView('state_house')` adds the State House geometry for the chosen line year and rebuilds the picker from the district manifest.
2. The same contest key routes `applyContest()` to `applyDistrictContest()`.
3. `loadDistrictSlice('state_house', 'president', 2024, linesYear)` loads, for example, `data/district_contests/state_house_president_2024.json` on 2022 lines or the same filename under `data/district_contests_2024_lines/` on 2024 lines.
4. That file already contains district totals under `general.results`; the browser does not re-shatter all precincts and blocks.
5. The slice metadata explains the source crosswalk, target crosswalk, coverage, non-geographic allocation, selected line year, and calibration.
6. District-number expressions apply margins, winners, shifts, flips, comparison, or demographics to the correct polygons.

The critical difference is that Counties view commonly sums precinct rows in the browser, while State House view normally reads an offline-generated district slice aligned to the selected boundary set.

---

## 12. Interpreting the atlas responsibly

The main limitations are not reasons to avoid the atlas; they are reasons to use its metadata and audits.

- Historical names and abbreviations can match imperfectly.
- A precinct can split, merge, or change footprint between elections.
- An unmatched key may require a precinct-bucket or county fallback.
- VAP assumes geographic distribution, not actual ballot locations.
- Non-geographic vote distribution is modeled from available geographic patterns or population shares.
- Putting an old election on new lines answers a counterfactual boundary question.
- Older district slices may lack candidate labels even when votes are present.
- The 2026 modeled contests are synthetic scenarios, not forecasts certified by an authority.
- Coverage varies by year, office, geographic scope, and line vintage.

Use this authority ladder:

1. **Certified or official source totals.** The strongest direct evidence for the geography the authority published.
2. **Browser-calculated sums.** Exact arithmetic over the available rows, but only as authoritative as those rows and their geographic identity.
3. **Geographically reallocated estimates.** Useful approximations built with crosswalks and weights, not ballot-level facts.
4. **Calibrated estimates.** Geographic estimates reconciled to an official target; stronger on the calibrated total, but not proof that every internal allocation is exact.
5. **Synthetic modeled scenarios.** Deliberately hypothetical results produced from assumptions and historical anchors.

Do not treat these as equally authoritative. `js/atlas-provenance.js` encodes the same distinction, and comparison cards warn when modeled, low-confidence, or geographically allocated sources are involved.

---

## 13. Extending and testing the project

### Adding data safely

1. **Add an election source.** Place or reference a normalized OpenElections/NCSBE-style file with year, office, county, precinct, candidate, party, and votes. Document its source.
2. **Generate a precinct slice.** Use the appropriate current path in `scripts/build_district_contests_from_batch_shatter.py` with `--write-contests`/contest-only options, or a narrowly applicable builder. Inspect candidate-party handling and non-geographic allocation before writing.
3. **Update the manifest.** Let the builder update `data/contests/manifest.json`, or use the split script designed for that output. Confirm the filename, year, contest type, row count, totals, and contested status.
4. **Rebuild district slices.** Use election-vintage matching, correct VAP, and block assignments for each target line set. Do not copy a 2022-line file into a 2024-line directory merely to make the picker populate.
5. **Add a line vintage.** Add block assignments, geometry/tileset source, production directory and manifest, and extend `CONFIG`, `getActiveDistrictContestsDir()`, `getDistrictGeometryPath()`, and URL validation deliberately.
6. **Add a visualization mode.** Extend `AtlasURLState.MODE_VALUES`, controls, legend rendering, contest application for every supported geography, hover/sidebar semantics, export behavior, accessibility palette, and regression tests.

### Validate before publishing

Run:

```powershell
npm run validate:data
npm run test:core
npm test
```

`npm run validate:data` checks every production manifest target, identity fields, safe filenames, nonnegative integer votes, and `D + R + Other = total`. Core tests cover the extracted modules. Playwright tests cover the live map, controls, accessibility, and palette behavior.

Then inspect the data-specific evidence:

- `data/reports/unmatched_precinct_examples.csv` and related match-health summaries.
- Shatter precinct zero-sum audit output.
- County and statewide conservation before/after tables.
- Calibration apply reports and their official-source references.
- Urban SF1 `validation.json`, precinct linkage, weight detail, and district outlier audits for early elections.
- Geographic spot checks in split urban counties, not only statewide totals.

Write to production directories only after these checks. Review folders are intentionally a staging boundary.

---

## 14. Student exploration guide

### Five things to remember

1. The atlas connects election results to geography; votes, shapes, and crosswalks are different data.
2. The usual live margin is signed R−D divided by reported total, with Other included when present.
3. Color meaning changes by mode, and darkness is not turnout unless turnout opacity is explicitly enabled.
4. County totals are often summed in the browser; district totals are normally built offline through geographic allocation.
5. An old election displayed on new district lines is a useful estimate of a hypothetical boundary question, not the original historical district result.

### Five questions to investigate

1. Which counties shifted most between two presidential elections, and did the winner change?
2. Where was ticket splitting between President and Governor strongest in the same year?
3. How does the same election look on the 2022, 2024, and available 2026 district lines?
4. Which counties or districts fall in Tossup, Tilt, or Lean categories, and how sensitive are they to a one-point change?
5. Which early-year or split-precinct estimates have lower match coverage or special provenance that deserves extra caution?

### Three interpretation cautions

1. Never infer voter count or influence from darkness or land area alone.
2. Treat reallocated district results as documented geographic estimates, even when every statewide vote is conserved.
3. Treat 2026 model entries and user swing scenarios as explorations, not observed or certified elections.

---

## Repository map for further study

Start with `README.md` and `CHANGELOG.md`, then follow the active path through `index.html`, `css/atlas-main.css`, `js/atlas-*.js`, `data/contests/manifest.json`, and the three production district manifests. For the build path, read `scripts/build_district_contests_from_batch_shatter.py` beside `scripts/shatter_precinct_votes_vap.py`; use `scripts/build_nc_elections_aggregated.py` and `scripts/aggregate_elections.py` to understand older aggregate formats. Finally, read the relevant crosswalk builder, calibration report, unmatched-key report, and geographic audit for the election era you plan to change.

The central habit is simple: **follow one contest from its source rows, through its geographic assumptions, into its manifest and slice, and finally into the browser function that colors the map.** That is how a civic map becomes understandable, testable, and trustworthy.

---

## Appendix A. Formula and denominator reference

The most common interpretation error is mixing formulas that sound similar. This table records the current implementation rather than assuming every number is two-party.

| Quantity | Current formula | Normal denominator | Important qualification |
| --- | --- | --- | --- |
| Democratic share | `D / total × 100` | D + R + Other | Implemented by `partyPctValue()` and inline equivalents |
| Republican share | `R / total × 100` | D + R + Other | Same denominator as Democratic share |
| Signed margin | `(R − D) / total × 100` | D + R + Other | Positive is Republican; negative is Democratic |
| Absolute margin | `abs(R − D) / total × 100` | D + R + Other | Used for competitiveness categories |
| Raw vote lead | `abs(R − D)` | None | A count of votes, not a percentage |
| Shift | `new signed margin − old signed margin` | Each contest's own reported total | Positive means movement toward R |
| Compare | `primary signed margin − comparison signed margin` | Each contest's own reported total | UI describes the route as comparison → primary |
| Scenario swing | Vote transfer between D and R | Uses total votes to calculate the transfer | `shiftVotesBySwingPct()` preserves the original two-party vote pool and Other |
| Turnout | `total_votes` | Not a percentage unless normalized elsewhere | Must not be confused with population or VAP |
| Population change % | `(new population − old population) / old population × 100` | Earlier population | Not a partisan shift |

`AtlasComparison.signedMarginPct()` is the main exception worth memorizing: it uses the supplied positive `total_votes`, but falls back to `D + R` if the total is absent or invalid. That fallback makes comparison code robust; it does not change the normal slice convention.

### Why “percentage points” matters

If Democratic share rises from 50% to 55%, it rose by **5 percentage points**. Relative percentage change is `(55 − 50) / 50 = 10%`. Election margins and shifts in the atlas use percentage points, not relative percent growth.

### Display rounding and classification

The application does not simply round every close result to one decimal place. `js/atlas-display.js` preserves two decimals for normal margins and a third decimal for extremely close values that would otherwise disappear. `competitivenessMarginValue()` then classifies the same two-decimal value presented to the reader. This prevents, for example, a displayed D+0.96 result from being rounded to 1.0 and incorrectly labeled Lean rather than Tilt.

---

## Appendix B. Complete visual-encoding reference

### Why the current partisan ramp is a better default

The finalized scale solves a categorical perception problem, not merely an aesthetic preference. If adjacent categories look alike, the map implies less difference than the labels claim.

It also resolves the opposite problem revealed by the optional DRA experiment. The DRA-inspired colors separated tiers very clearly, but their highly saturated reds and blues were visually too strong for the finished atlas. According to the project creator, that excessive intensity is why the final design became a compromise palette: preserve the original Atlas identity and dark endpoints, borrow the stronger category separation learned from the DRA version, and moderate the middle colors so they support the election data instead of overpowering the basemap and interface.

On the Democratic side, the original Lean `#c6dbef` was almost indistinguishable from Tilt `#e1f5fe` on some displays. The final scale effectively reassigned the old Lean shade to Tilt (`#c7ddf0`) and moved each middle tier downward in lightness:

```text
Tilt       #c7ddf0
Lean       #9ecae1   (the original Likely color)
Likely     #5b9fd0
Safe       #3f8fc9
Stronghold #2876b5
```

This makes the political concept match the visual grammar: a Likely result looks clearly stronger than a Lean result, and Safe is established without becoming indistinguishable from Stronghold.

Republican colors needed less reconstruction. The original ramp already separated Lean, Likely, and Safe reasonably well, but original Tilt `#fee8c8` could look cream or peach rather than partisan red. The final `#f4c9c5` is more consistently read as pale red. Likely changed from `#fb6a4a` to `#f7634b`, and Safe from `#ef3b2c` to `#e93a2d`; both changes reduce the orange cast and balance the apparent strength of the darker Democratic middle tiers.

### Colorblind Shift and Compare scale

In colorblind mode, Republican-direction movement uses orange and Democratic-direction movement uses blue:

| Change magnitude | Republican direction | Democratic direction |
| ---: | --- | --- |
| Below 0.50 | `#f8fafc` | `#f8fafc` |
| 0.50–0.99 | `#ffedd5` | `#e0f2fe` |
| 1.00–4.99 | `#fed7aa` | `#bae6fd` |
| 5.00–9.99 | `#fdba74` | `#7dd3fc` |
| 10.00–14.99 | `#f58a2a` | `#38bdf8` |
| 15.00–19.99 | `#e66a00` | `#0284c7` |
| 20.00–24.99 | `#b54708` | `#0072b2` |
| 25.00+ | `#7c2d12` | `#063f5c` |

### Demographic colors

Demographics mode classifies the largest reported race/ethnicity share. A majority means at least 50%; a plurality means the group is largest but below 50%. If the top two shares are within 0.15 point, the result is Mixed. A special narrow-majority treatment applies when the leading group is 50–54.99% and the second group is at least 35%.

| Classification | Plurality color | Majority color | High-contrast plurality | High-contrast majority |
| --- | --- | --- | --- | --- |
| White | `#94a3b8` | `#334155` | `#64748b` | `#111827` |
| Black | `#93c5fd` | `#1d4ed8` | `#60a5fa` | `#1e40af` |
| Hispanic | `#fdba74` | `#c2410c` | `#fb923c`* | `#9a3412`* |
| Native | `#d8b4fe` | `#9333ea` | `#c084fc` | `#6b21a8` |
| Asian | `#86efac` | `#15803d` | `#4ade80` | `#166534` |
| Pacific Islander | `#67e8f9` | `#0e7490` | `#22d3ee` | `#155e75` |
| Multiracial | `#f9a8d4` | `#be185d` | `#f472b6` | `#9d174d` |
| Mixed | `#0f766e` | — | `#065f46` | — |
| Unknown | `#64748b` | — | `#475569` | — |

\*In colorblind plus high-contrast mode, Hispanic plurality is `#fbbf24` and Hispanic majority is `#b45309`.

Narrow-majority colors depend on the leading and second-place groups and are defined in the palette objects inside `colorForDemographicsMode()`. Their purpose is to avoid presenting a narrow, diverse majority with the same color as an overwhelming majority.

### Population Change colors

Percent mode uses this scale:

| 2020–2025 change | Color | Meaning |
| ---: | --- | --- |
| ≤−30% | `#24150d` | Extreme decline |
| −29.99 to −20% | `#321e12` | Very large decline |
| −19.99 to −10% | `#3f2818` | Large decline |
| −9.99 to −5% | `#5a3b1f` | Clear decline |
| −4.99 to −2% | `#8c613c` | Moderate decline |
| −1.99 to −0.5% | `#b08968` | Small decline |
| −0.49 to +0.99% | `#f8fafc` | Little change |
| +1.00 to +1.99% | `#a9d6a5` | Small growth |
| +2.00 to +4.99% | `#52b788` | Moderate growth |
| +5.00 to +9.99% | `#1b7f4a` | Clear growth |
| +10.00 to +19.99% | `#146b42` | Large growth |
| +20.00 to +29.99% | `#075c37` | Very large growth |
| ≥+30% | `#043b27` | Extreme growth |

Absolute-count mode uses the same colors at −150,000, −100,000, −50,000, −25,000, −10,000, −2,500, +2,500, +10,000, +25,000, +50,000, +100,000, and +150,000 breakpoints. The scale is county-oriented; an absolute change naturally favors populous counties, while percentage change emphasizes proportional growth or decline.

### Layer order matters

Mapbox draws sources through multiple layers rather than one picture. A typical active geography has a fill, light casing, dark inner stroke, hover outline, and sometimes selected outline. Precinct dots and polygons switch by zoom. The basemap remains beneath election overlays, while labels are reinforced with halos. This is why a fill color can change without removing boundaries or place names.

---

## Appendix C. Reading a contest file

Consider `data/contests/president_2024.json`. Its top-level structure teaches the data model:

```text
year + contest_type
meta
county_totals (optional authority sidecar)
rows (precinct-keyed results)
```

The `meta` object says where the data came from, how non-geographic votes were treated, which bridge was used, and what totals should be conserved. A row contains the geography key, D/R/Other/total votes, candidate names, margin, winner, and a stored legacy color. The frontend recalculates its current live color rather than trusting that stored color.

A district slice such as `data/district_contests/state_house_president_2024.json` has:

```text
year + scope + contest_type
meta
general.results[district_number]
```

Its metadata is especially important. Fields such as `match_coverage_pct`, `match_crosswalk`, `target_crosswalk`, `district_lines_year`, `nongeo_allocation_mode`, and calibration flags explain how the apparently simple district totals were produced.

### Questions to ask before trusting a slice

1. Does its manifest point to the file?
2. Do D + R + Other equal total for every row?
3. Does the metadata identify the source and target geography?
4. Is the selected district-line year the one the file was built for?
5. How were non-geographic votes allocated?
6. What share of source precinct keys matched?
7. Were county and statewide totals conserved?
8. Was it calibrated, and to what official target?
9. Did someone check split-county geography rather than only totals?
10. Is the directory production, staging, review, or audit-only?

---

## Appendix D. A provenance decision tree

Use this quick sequence when a map result surprises you:

```text
Is this a 2026 model or user swing?
├─ Yes → synthetic scenario; inspect assumptions.
└─ No
   ↓
Is the displayed geography an official source geography?
├─ Yes → check for a certified/official total.
└─ No
   ↓
Was the result geographically reallocated?
├─ Yes → inspect crosswalk, coverage, non-geographic method, and line vintage.
└─ No → inspect the browser sum and its input rows.
   ↓
Was it calibrated to an official benchmark?
├─ Yes → benchmark total is strong; internal allocation may still be estimated.
└─ No → treat it as an uncalibrated geographic estimate.
```

If two plausible numbers disagree, do not immediately choose the one that looks more politically familiar. First determine whether they use different denominators, precinct vintages, district plans, non-geographic allocation methods, or calibration targets.

---

## Appendix E. Debugging and maintenance guide

### When a county total looks wrong

1. Open the relevant `data/contests/<contest>_<year>.json`.
2. Sum rows whose key starts with that county.
3. Compare the sum with `county_totals` and the source return.
4. Check whether an administrative row was treated as geographic or vice versa.
5. Look for aliases that caused two source keys to land on one display key.
6. Inspect `data/reports/unmatched_precinct_examples.csv` and county match-health reports.

### When a district looks wrong

1. Confirm the active line year and production directory.
2. Read the slice metadata, not only the district row.
3. Identify which counties or precincts compose the district.
4. Check whether the suspicious area is split by the district boundary.
5. Review the relevant block/VAP crosswalk and unmatched fallback.
6. Compare against an official NCGA/NCSBE benchmark when one exists.
7. Check neighboring districts: geographic misallocation often appears as equal-and-opposite errors.

### When a color looks wrong

1. Read the numeric margin in the hover card.
2. Confirm whether the mode is Margins, Shift, Flips, Compare, Demographics, or Population Change.
3. Check colorblind mode and turnout opacity.
4. Remember that categories use the rounded displayed absolute margin.
5. Verify that the map and legend both call the current color function.
6. Ignore a stale `color` field in JSON when diagnosing current live fills.

### Known documentation and implementation edges

- Older prose and changelog entries may use “two-party margin”; the live calculation divides the Republican-minus-Democratic vote difference by the reported total, including Other votes when present.
- An older changelog entry mentions an original/DRA palette toggle that is absent from the current application; the README now documents the compromise palette as the standard live palette.
- Several offline generators preserve older palette values. They are useful historical evidence but are not live frontend authority.
- `index.html` configures a preferred `data/district_contests_2020_2024/` directory for some congressional loads, but that directory is absent in the current checkout; the loader falls through to production slices.
- Review and staged directories can contain plausible, vote-conserving outputs that have not passed geographic promotion review.

These edges are not merely cleanup trivia. Clear documentation prevents a future contributor from “fixing” the live application to match a stale comment or promoting an audit file because its statewide total happens to balance.

---

## Appendix F. Suggested learning path

For a student:

1. Start in Counties, 2024 President, Margins.
2. Compare candidate shares and the margin in three differently sized counties.
3. Turn on Shift and explain why its color can differ from the winner.
4. Compare President with Governor and state the subtraction direction.
5. Switch to State House and explain why the result is now geographically allocated.
6. Change the district-line vintage and describe the question that changed.
7. Inspect a provenance note before reaching a conclusion.

For a new contributor:

1. Run `npm run validate:data` and `npm run test:core` before changing anything.
2. Trace `president_2024` from manifest to slice to `loadContestSlice()` to `applyCountyContest()`.
3. Trace the State House version through `loadDistrictSlice()` and its metadata.
4. Read the shatter script and one zero-sum audit.
5. Read one unmatched-key report and one calibration report.
6. Make a small test-backed helper change before editing the large inline orchestration code.
7. Run Playwright and visually verify map, legend, hover, keyboard focus, mobile layout, and both standard and colorblind palettes.
