# Reports Folder Guide

This folder keeps the current, operational report files for precinct-key remediation.
Older intermediate artifacts are moved to `data/reports/archive/`.

## Core Status Files

- `unmatched_precinct_summary.csv`  
  Current year-by-year resolver status totals (`matched`, `unmatched`, `ambiguous`, `non_geographic`).

- `unmatched_precinct_examples.csv`  
  Current unresolved example keys by year/status with counts. Use this as the primary work queue source.

- `precinct_match_health_summary_latest.csv`  
  Consolidated before/after health summary by year from the latest remediation pass.

## Active Review Queues

- `manual_review_pack_2016_by_county.csv`  
  County-prioritized manual review pack for 2016 unresolved keys.

- `county_source_backed_packet_2016_top10.csv`  
  Source-backed candidate packet for top unresolved 2016 counties.

- `county_source_backed_packet_2016_top20.csv`  
  Expanded source-backed packet for top unresolved 2016 counties.

- `county_source_backed_packet_2008_top20.csv`  
  Source-backed packet for 2008 unresolved counties.

- `county_source_backed_packet_2010_top20.csv`  
  Source-backed packet for 2010 unresolved counties.

## QA Summaries

- `qa_2008_added_overrides_summary.csv`  
  Summary QA metrics for 2008 rewrite/applied override batches.

- `qa_2010_added_overrides_summary.csv`  
  Summary QA metrics for 2010 rewrite/applied override batches.

## 2008 Name-Only Salvage (VTD00)

2008 NCSBE `results_pct` exports drop `precinct_abbrv` and keep display names only.
Salvage path:

1. Build `data/crosswalks/vtd00_to_nconemap_*` via `scripts/build_vtd_to_modern_precinct_crosswalk.py`
2. Generate/apply overrides with `scripts/salvage_2008_overrides_from_vtd00.py --apply-to-overrides`
3. Re-run `scripts/report_unmatched_precincts.py`

Artifacts:
- `precinct_key_overrides_2008_vtd00_suggestions.csv`
- `precinct_key_overrides_2008_vtd00_auto.csv`
- `qa_2008_vtd00_salvage_summary.json`

## Recommended Workflow

1. Read `unmatched_precinct_summary.csv` to choose the next year/county target.
2. Use `unmatched_precinct_examples.csv` to identify specific unresolved keys.
3. Work from a county packet (`county_source_backed_packet_*`) or review pack.
4. Apply approved overrides into `data/mappings/precinct_key_overrides.csv`.
5. Re-run diagnostics and verify impact in:
   - `unmatched_precinct_summary.csv`
   - `precinct_match_health_summary_latest.csv`
6. Archive large intermediate files in `data/reports/archive/` to keep this folder clean.
