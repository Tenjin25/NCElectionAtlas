# CVAP aggregates (generated)

This folder is intended for outputs generated from Redistricting Data Hub’s **block-level CVAP** file:

- Input: `data/nc_cvap_2024_2020_b_csv/nc_cvap_2024_2020_b.csv`
- Generator: `scripts/build_cvap_aggregates.py`

The script aggregates block-level CVAP (and citizen estimates) onto atlas geographies using the `data/crosswalks/block20_to_*.csv` crosswalks.

Notes:
- The generator accepts either the original RDH headers (`GEOID20`, `CVAP_TOT24`, etc.) or the optional snake_case headers produced by `scripts/slice_cvap_csv.*` (`block_geoid20`, `cvap_total_24`, etc.).
- `--fields` can be specified in either style; outputs use exactly the names you pass in `--fields`.

## Build

From the repo root:

```bash
py scripts/build_cvap_aggregates.py
```

County-only (fast; avoids loading big crosswalk CSVs):

```bash
py scripts/build_cvap_aggregates.py --targets county
```

Optional:

```bash
py scripts/build_cvap_aggregates.py --fields CVAP_TOT24,CVAP_HSP24,CVAP_WHT24,CVAP_BLA24
```

## Outputs

The script writes files like:

- `data/cvap_aggregates/county_2020__cvap24.csv`
- `data/cvap_aggregates/precinct_2020__cvap24.csv`
- `data/cvap_aggregates/cd118_2022_lines__cvap24.csv`
- `data/cvap_aggregates/cd119_2024_lines__cvap24.csv`
- `data/cvap_aggregates/state_house_2022_lines__cvap24.csv`
- `data/cvap_aggregates/state_house_2024_lines__cvap24.csv`
- `data/cvap_aggregates/state_senate_2022_lines__cvap24.csv`
- `data/cvap_aggregates/state_senate_2024_lines__cvap24.csv`

These outputs are not automatically used by `index.html` until you wire them into the demographics UI / loaders.
