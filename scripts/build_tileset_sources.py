"""
Build Mapbox-uploadable district GeoJSON sources with precomputed color fields.

Outputs:
  - data/tileset/nc_state_house_2022_lines_tileset.geojson
  - data/tileset/nc_state_senate_2022_lines_tileset.geojson
  - data/tileset/nc_cd118_tileset.geojson
  - data/tileset/tileset_fields_manifest.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def norm_district_key(v: Any) -> str:
    s = str(v).strip()
    if not s:
        return ""
    if s.isdigit():
        return str(int(s))
    return s


def build_index(scope_data: dict) -> tuple[dict[str, dict[str, dict]], list[tuple[str, str]]]:
    """
    Returns:
      index[district_key][office_year] -> result row
      list of (office, year) seen
    """
    idx: dict[str, dict[str, dict]] = {}
    seen: set[tuple[str, str]] = set()

    for year, year_block in scope_data.items():
        for office, office_block in year_block.items():
            seen.add((office, year))
            results = office_block.get("general", {}).get("results", {}) or {}
            for district_key, row in results.items():
                dkey = norm_district_key(district_key)
                if not dkey:
                    continue
                if dkey not in idx:
                    idx[dkey] = {}
                idx[dkey][f"{office}_{year}"] = row

    return idx, sorted(seen, key=lambda x: (x[1], x[0]))


def add_result_props(
    feature: dict,
    district_idx: dict[str, dict[str, dict]],
    office_years: list[tuple[str, str]],
    match_meta: dict[str, dict[str, dict]],
) -> None:
    props = feature.setdefault("properties", {})
    raw_d = props.get("DISTRICT", "")
    dkey = norm_district_key(raw_d)

    # Keep a stable numeric id for promoteId usage in Mapbox style.
    props["district_id"] = dkey

    by_contest = district_idx.get(dkey, {})
    for office, year in office_years:
        k = f"{office}_{year}"
        row = by_contest.get(k)
        if not row:
            continue
        base = f"{office}_{year}"
        props[f"{base}_color"] = row.get("competitiveness", {}).get("color", "")
        props[f"{base}_winner"] = row.get("winner", "")
        props[f"{base}_margin_pct"] = row.get("margin_pct", 0)
        props[f"{base}_dem"] = row.get("dem_votes", 0)
        props[f"{base}_rep"] = row.get("rep_votes", 0)
        props[f"{base}_total"] = row.get("total_votes", 0)

        meta = match_meta.get(year, {}).get(office, {})
        if meta:
            props[f"{base}_match_cov"] = meta.get("match_coverage_pct", 0)


def build_scope_layer(
    *,
    boundary_path: Path,
    out_path: Path,
    results_scope: dict[str, dict],
) -> dict[str, Any]:
    gj = json.load(open(boundary_path, "r", encoding="utf-8"))

    # Reindex results by district and gather office/year pairs.
    idx, office_years = build_index(results_scope)

    # year->office->meta for coverage fields
    match_meta: dict[str, dict[str, dict]] = {}
    for year, year_block in results_scope.items():
        match_meta[year] = {}
        for office, office_block in year_block.items():
            match_meta[year][office] = office_block.get("meta", {}) or {}

    for f in gj.get("features", []):
        add_result_props(f, idx, office_years, match_meta)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(gj, f)

    sample_fields = []
    if gj.get("features"):
        sample_fields = sorted(gj["features"][0].get("properties", {}).keys())

    return {
        "output": str(out_path),
        "feature_count": len(gj.get("features", [])),
        "office_year_pairs": [f"{o}_{y}" for o, y in office_years],
        "sample_fields": sample_fields,
    }


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    data_dir = root / "data"
    tileset_dir = data_dir / "tileset"

    results = json.load(open(data_dir / "nc_district_results_2022_lines.json", "r", encoding="utf-8"))
    by_year = results.get("results_by_year", {})

    house_scope = {y: (b.get("state_house", {}) or {}) for y, b in by_year.items()}
    senate_scope = {y: (b.get("state_senate", {}) or {}) for y, b in by_year.items()}
    cd_scope = {y: (b.get("congressional", {}) or {}) for y, b in by_year.items()}

    manifest = {
        "state_house": build_scope_layer(
            boundary_path=data_dir / "nc_state_house_districts.geojson",
            out_path=tileset_dir / "nc_state_house_2022_lines_tileset.geojson",
            results_scope=house_scope,
        ),
        "state_senate": build_scope_layer(
            boundary_path=data_dir / "nc_state_senate_districts.geojson",
            out_path=tileset_dir / "nc_state_senate_2022_lines_tileset.geojson",
            results_scope=senate_scope,
        ),
        "cd118": build_scope_layer(
            boundary_path=data_dir / "nc_congressional_districts.geojson",
            out_path=tileset_dir / "nc_cd118_tileset.geojson",
            results_scope=cd_scope,
        ),
    }

    manifest_path = tileset_dir / "tileset_fields_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Wrote {manifest_path}")
    for k, v in manifest.items():
        print(f"{k}: {v['feature_count']} features -> {v['output']}")


if __name__ == "__main__":
    main()
