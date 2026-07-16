"""Build a VAP-weighted bridge from SBE 2024 precinct keys to OneMap 2025 precincts.

Election returns match SBE-style codes; the atlas current geography is
the configured modern OneMap block map (December 2025 by default).
This join uses shared 2020 Census blocks so the shatter chain can land on
the current OneMap layer without losing SBE key coverage.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
REINIT = ROOT / "NCPrecinctMap_reinit_2026-04-29"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--sbe-block-map",
        type=Path,
        default=REINIT / "data/crosswalks/block20_to_precinct_sbe_2024.csv",
    )
    p.add_argument(
        "--onemap-block-map",
        type=Path,
        default=ROOT / "data/crosswalks/block20_to_onemap_2025_12.csv",
    )
    p.add_argument(
        "--vap-csv",
        type=Path,
        default=ROOT / "data/census/block_vap_2020_nc.csv",
    )
    p.add_argument(
        "--out-csv",
        type=Path,
        default=ROOT / "data/crosswalks/precinct_sbe_2024_to_onemap_2025_12_vap.csv",
    )
    p.add_argument(
        "--allow-cross-county",
        action="store_true",
        help="Keep VAP shares that cross county lines (default: clamp to source county).",
    )
    return p.parse_args()


def _county_of(series: pd.Series) -> pd.Series:
    parts = series.astype(str).str.split(" - ", n=1, expand=True)
    return parts[0].fillna(series.astype(str)).str.strip().str.upper()


def main() -> None:
    args = parse_args()
    sbe = pd.read_csv(args.sbe_block_map, dtype=str)
    one = pd.read_csv(args.onemap_block_map, dtype=str)
    vap = pd.read_csv(args.vap_csv, dtype=str)

    sbe = sbe[["block_geoid20", "precinct_id"]].rename(columns={"precinct_id": "sbe_precinct_id"})
    one = one[["block_geoid20", "precinct_id"]].rename(columns={"precinct_id": "onemap_precinct_id"})
    for frame, col in ((sbe, "sbe_precinct_id"), (one, "onemap_precinct_id")):
        frame["block_geoid20"] = frame["block_geoid20"].astype(str).str.strip().str.zfill(15)
        frame[col] = frame[col].astype(str).str.strip().str.upper().str.replace(r"\s+", " ", regex=True)

    geoid_col = "block_geoid20" if "block_geoid20" in vap.columns else "GEOID20"
    vap_col = "vap_count" if "vap_count" in vap.columns else "vap20"
    vap = vap[[geoid_col, vap_col]].copy()
    vap.columns = ["block_geoid20", "vap_count"]
    vap["block_geoid20"] = vap["block_geoid20"].astype(str).str.strip().str.zfill(15)
    vap["vap_count"] = pd.to_numeric(vap["vap_count"], errors="coerce").fillna(0.0)

    joined = sbe.merge(one, on="block_geoid20", how="inner").merge(vap, on="block_geoid20", how="left")
    joined["vap_count"] = joined["vap_count"].fillna(0.0)

    if not args.allow_cross_county:
        same_county = _county_of(joined["sbe_precinct_id"]) == _county_of(joined["onemap_precinct_id"])
        dropped = int((~same_county).sum())
        joined = joined.loc[same_county].copy()
        print(f"Clamped cross-county block rows dropped: {dropped:,}")

    grouped = (
        joined.groupby(["sbe_precinct_id", "onemap_precinct_id"], as_index=False)
        .agg(vap_weight=("vap_count", "sum"), block_count=("block_geoid20", "nunique"))
    )
    # If an SBE precinct has zero VAP, fall back to equal block weights.
    zero = grouped.groupby("sbe_precinct_id")["vap_weight"].transform("sum") <= 0
    grouped.loc[zero, "vap_weight"] = grouped.loc[zero, "block_count"].astype(float)

    totals = grouped.groupby("sbe_precinct_id", as_index=False)["vap_weight"].sum().rename(
        columns={"vap_weight": "sbe_vap_total"}
    )
    grouped = grouped.merge(totals, on="sbe_precinct_id", how="left")
    grouped["share"] = grouped["vap_weight"] / grouped["sbe_vap_total"]
    grouped = grouped.sort_values(
        ["sbe_precinct_id", "share"], ascending=[True, False]
    ).reset_index(drop=True)

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    grouped.to_csv(args.out_csv, index=False)

    multi = int((grouped.groupby("sbe_precinct_id").size() > 1).sum())
    print(
        f"Wrote {len(grouped):,} rows -> {args.out_csv} "
        f"(sbe={grouped['sbe_precinct_id'].nunique():,}, "
        f"onemap={grouped['onemap_precinct_id'].nunique():,}, "
        f"split_sbe_precincts={multi})"
    )


if __name__ == "__main__":
    main()
