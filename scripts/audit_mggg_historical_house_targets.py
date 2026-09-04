#!/usr/bin/env python3
"""Project MGGG's 2008-2016 NC VTD elections onto modern House plans."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import shapefile


ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"108", "109", "110"}
CONTESTS = {
    "governor_2008": ("EL08G_GV_D", "EL08G_GV_R", ["EL08G_GV_L"]),
    "us_senate_2008": ("EL08G_USS_", "EL08G_US_1", ["EL08G_US_2", "EL08G_US_3"]),
    "us_senate_2010": ("EL10G_USS_", "EL10G_US_1", ["EL10G_US_2", "EL10G_US_3"]),
    "governor_2012": ("EL12G_GV_D", "EL12G_GV_R", ["EL12G_GV_L", "EL12G_GV_W", "EL12G_GV_1"]),
    "president_2012": ("EL12G_PR_D", "EL12G_PR_R", ["EL12G_PR_L", "EL12G_PR_W", "EL12G_PR_1"]),
    "us_senate_2014": ("EL14G_US_1", "EL14G_USS_", ["EL14G_US_2", "EL14G_US_3"]),
    "governor_2016": ("EL16G_GV_D", "EL16G_GV_R", ["EL16G_GV_L"]),
    "president_2016": ("EL16G_PR_D", "EL16G_PR_R", ["EL16G_PR_L", "EL16G_PR_W"]),
    "us_senate_2016": ("EL16G_US_1", "EL16G_USS_", ["EL16G_US_2"]),
}


def load_dbf(shapefile_path: Path) -> pd.DataFrame:
    reader = shapefile.Reader(str(shapefile_path))
    fields = [field[0] for field in reader.fields[1:]]
    return pd.DataFrame((dict(zip(fields, record)) for record in reader.records()))


def load_weights(assignment_path: Path, *, assignment_block: str, assignment_district: str) -> pd.DataFrame:
    vtd = pd.read_csv(ROOT / "data/crosswalks/block20_to_vtd10.csv", dtype=str)
    vtd = vtd.rename(columns={"block_geoid20": "block"})[["block", "precinct_id"]]
    vtd["vtd_name"] = vtd["precinct_id"].str.split(" - ", n=1).str[-1].str.strip()
    vtd["vtd_key"] = vtd["block"].str[:5] + vtd["vtd_name"]

    vap = pd.read_csv(ROOT / "data/census/block_vap_2020_nc.csv", dtype={"block_geoid20": str})
    vap = vap.rename(columns={"block_geoid20": "block"})[["block", "vap_count"]]
    vap["vap_count"] = pd.to_numeric(vap["vap_count"], errors="coerce").fillna(0.0)

    assignments = pd.read_csv(assignment_path, dtype=str)
    assignments = assignments.rename(
        columns={assignment_block: "block", assignment_district: "district"}
    )[["block", "district"]]
    assignments["block"] = assignments["block"].str.zfill(15)
    assignments["district"] = assignments["district"].astype(str).str.lstrip("0").replace("", "0")

    joined = vtd.merge(vap, on="block", how="left").merge(assignments, on="block", how="inner")
    grouped = joined.groupby(["vtd_key", "district"], as_index=False)["vap_count"].sum()
    totals = grouped.groupby("vtd_key")["vap_count"].transform("sum")
    grouped["share"] = (grouped["vap_count"] / totals).where(totals > 0, 0.0)
    return grouped[["vtd_key", "district", "share"]]


def project(vtd_elections: pd.DataFrame, weights: pd.DataFrame) -> dict[str, dict[str, dict[str, float | int]]]:
    joined = weights.merge(vtd_elections, left_on="vtd_key", right_on="VTD_Key", how="inner")
    output: dict[str, dict[str, dict[str, float | int]]] = {}
    for contest, (dem_col, rep_col, other_cols) in CONTESTS.items():
        joined["dem_alloc"] = pd.to_numeric(joined[dem_col], errors="coerce").fillna(0) * joined["share"]
        joined["rep_alloc"] = pd.to_numeric(joined[rep_col], errors="coerce").fillna(0) * joined["share"]
        joined["other_alloc"] = sum(
            pd.to_numeric(joined[col], errors="coerce").fillna(0) for col in other_cols
        ) * joined["share"]
        grouped = joined.groupby("district")[["dem_alloc", "rep_alloc", "other_alloc"]].sum()
        rows: dict[str, dict[str, float | int]] = {}
        for district in sorted(TARGETS, key=int):
            if district not in grouped.index:
                continue
            row = grouped.loc[district]
            dem = float(row["dem_alloc"])
            rep = float(row["rep_alloc"])
            other = float(row["other_alloc"])
            total = dem + rep + other
            rows[district] = {
                "dem_votes_float": round(dem, 3),
                "rep_votes_float": round(rep, 3),
                "other_votes_float": round(other, 3),
                "total_votes_float": round(total, 3),
                "margin_pct": round(((rep - dem) / total) * 100.0, 2) if total else 0.0,
            }
        output[contest] = rows
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shapefile", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    elections = load_dbf(args.shapefile)

    plans = {
        "2022_lines": load_weights(
            ROOT / "data/tmp/block_assign_extract/SL 2022-4.csv",
            assignment_block="Block",
            assignment_district="District",
        ),
        "2024_lines": load_weights(
            ROOT / "data/crosswalks/block20_to_2024_state_house.csv",
            assignment_block="block_geoid20",
            assignment_district="district",
        ),
    }
    payload = {
        "schema": "mggg_historical_house_targets.v1",
        "source": "https://github.com/mggg-states/NC-shapefiles",
        "method": "2020-VAP-weighted 2010-VTD allocation to official block assignments",
        "target_districts": sorted(TARGETS, key=int),
        "plans": {name: project(elections, weights) for name, weights in plans.items()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "plans": list(plans)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
