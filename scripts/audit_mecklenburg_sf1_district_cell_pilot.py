#!/usr/bin/env python3
"""Validate the Mecklenburg 2000 election-district-cell/SF1 pilot."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_mecklenburg_2000_vap_legislative_weights as weights  # noqa: E402


SF1 = ROOT / "data/reports/mecklenburg_block_vap_2000_sf1.csv"
RESULT_2022 = (
    ROOT
    / "data/district_contests_mecklenburg_vap2000_2022_lines/state_house_president_2000.json"
)
RESULT_2024 = (
    ROOT
    / "data/district_contests_mecklenburg_vap2000_2024_lines/state_house_president_2000.json"
)
OUT_CSV = ROOT / "data/reports/mecklenburg_2024_hd98_sf1_place_composition.csv"
OUT_JSON = ROOT / "data/reports/mecklenburg_sf1_district_cell_pilot_validation.json"
CHARLOTTE_PLACE_FIPS = "12000"
PLACE_NAMES = {
    "12000": "Charlotte",
    "14700": "Cornelius",
    "16400": "Davidson",
    "33120": "Huntersville",
    "99999": "Remainder/unincorporated",
}


def hd98_result(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ((payload.get("general") or {}).get("results") or {}).get("98") or {}


def main() -> None:
    vap = pd.read_csv(SF1, dtype=str).fillna("")
    vap["blk2000ge"] = weights.clean_geoid(vap["block_geoid00"])
    vap["vap_count_2000"] = pd.to_numeric(
        vap["vap_count_2000"], errors="coerce"
    ).fillna(0.0)
    election_cells = weights.load_election_cells(
        weights.ROOT / "data/2000/20001107__nc__general__precinct.csv",
        weights.ROOT
        / "data/reports/mecklenburg_2000_2002_alias_experiment_precinct_overrides.csv",
    )
    sf_cells = set(
        "H"
        + vap["sldl_2000"].map(weights.clean_district)
        + "|S"
        + vap["sldu_2000"].map(weights.clean_district)
        + "|C"
        + vap["cd106_2000"].map(weights.clean_district)
    )
    missing_cells = sorted(set(election_cells["cell_id"]) - sf_cells)

    bridge = weights.load_fractional_bridge(
        weights.ROOT
        / "data/census/nhgis_blk2000_blk2010_37/nhgis_blk2000_blk2010_37.csv",
        weights.ROOT
        / "data/census/nhgis_blk2010_blk2020_37/nhgis_blk2010_blk2020_37.csv",
    )
    assignment = weights.load_assignment(
        weights.ROOT / "data/crosswalks/block20_to_2024_state_house.csv"
    )
    flow = (
        bridge.merge(assignment, on="blk2020ge", how="inner")
        .merge(
            vap[["blk2000ge", "place_fips_2000", "vap_count_2000"]],
            on="blk2000ge",
            how="inner",
        )
    )
    flow = flow[
        flow["district"].astype(str).str.lstrip("0").replace("", "0") == "98"
    ].copy()
    flow["vap_flow"] = flow["vap_count_2000"] * flow["weight"]
    composition = (
        flow.groupby("place_fips_2000", as_index=False)["vap_flow"]
        .sum()
        .sort_values("vap_flow", ascending=False)
    )
    total = float(composition["vap_flow"].sum())
    composition["place_name"] = composition["place_fips_2000"].map(PLACE_NAMES).fillna(
        "Other place"
    )
    composition["share_pct"] = (
        100.0 * composition["vap_flow"] / total if total else 0.0
    )
    composition = composition[
        ["place_fips_2000", "place_name", "vap_flow", "share_pct"]
    ]
    composition.to_csv(OUT_CSV, index=False, float_format="%.6f")

    charlotte_vap = float(
        composition.loc[
            composition["place_fips_2000"] == CHARLOTTE_PLACE_FIPS, "vap_flow"
        ].sum()
    )
    result22 = hd98_result(RESULT_2022)
    result24 = hd98_result(RESULT_2024)
    summary = {
        "schema": "mecklenburg_sf1_district_cell_pilot_validation.v1",
        "method": "2000 election House/Senate/CD cells matched to SF1 block fields, then VAP-weighted fractional block flow",
        "election_precincts_with_complete_unique_cells": int(
            election_cells["precinct_id"].nunique()
        ),
        "election_district_cells": int(election_cells["cell_id"].nunique()),
        "election_cells_missing_from_sf1": missing_cells,
        "cell_join_complete": not missing_cells,
        "hd98_2024_sf1_vap_flow": round(total, 6),
        "hd98_2024_charlotte_sf1_vap_flow": round(charlotte_vap, 6),
        "hd98_2024_charlotte_share_pct": round(
            100.0 * charlotte_vap / total if total else 0.0, 6
        ),
        "hd98_geography_sanity_passed": total > 0 and charlotte_vap == 0,
        "hd98_2022_president": {
            key: result22.get(key)
            for key in ("dem_votes", "rep_votes", "total_votes", "margin_pct", "winner")
        },
        "hd98_2024_president": {
            key: result24.get(key)
            for key in ("dem_votes", "rep_votes", "total_votes", "margin_pct", "winner")
        },
        "production_safe": False,
        "production_safe_reason": (
            "The district-cell method fixes the known HD98 geography error but "
            "remains a coarse allocation within each 2000 House/Senate/CD cell."
        ),
        "place_composition_csv": str(OUT_CSV.relative_to(ROOT)).replace("\\", "/"),
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Wrote {OUT_CSV}")
    print(f"Wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
