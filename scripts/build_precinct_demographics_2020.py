"""
Build precinct-level 2020 VAP demographics by aggregating block-level data.

Default inputs:
  - data/crosswalks/block20_to_precinct.csv
  - data/census/nhgis0004_csv/nhgis0004_csv/nhgis0004_ds248_2020_block.csv

Default NHGIS columns (ds248 P3, 18+):
  - U7D001: total 18+ (VAP total)
  - U7D003: white alone 18+
  - U7D004: black alone 18+

Hispanic VAP is optional because many block files (including ds248 P3) do not
include it. If available, pass --hispanic-col (and optionally
--hispanic-block-csv / --hispanic-geoid-col).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def _coerce_block_geoid(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.zfill(15)


def _read_block_metric(path: Path, geoid_col: str, metric_col: str, out_col: str) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=[geoid_col, metric_col], dtype=str)
    df = df.rename(columns={geoid_col: "block_geoid20", metric_col: out_col})
    df["block_geoid20"] = _coerce_block_geoid(df["block_geoid20"])
    df[out_col] = pd.to_numeric(df[out_col], errors="coerce").fillna(0)
    return df


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build precinct-level demographics from block-level VAP data.")
    p.add_argument("--crosswalk", type=Path, default=Path("data/crosswalks/block20_to_precinct.csv"))
    p.add_argument(
        "--race-block-csv",
        type=Path,
        default=Path("data/census/nhgis0004_csv/nhgis0004_csv/nhgis0004_ds248_2020_block.csv"),
    )
    p.add_argument("--race-geoid-col", default="GEOCODE")
    p.add_argument("--total-col", default="U7D001", help="Total 18+ (VAP total) block column.")
    p.add_argument("--white-col", default="U7D003", help="White 18+ block column.")
    p.add_argument("--black-col", default="U7D004", help="Black 18+ block column.")

    p.add_argument("--hispanic-block-csv", type=Path, default=None)
    p.add_argument(
        "--hispanic-geoid-col",
        default=None,
        help="Defaults to --race-geoid-col when --hispanic-block-csv is not provided.",
    )
    p.add_argument(
        "--hispanic-col",
        default="",
        help="Optional Hispanic 18+ block column (for example V_20_VAP_Hispanic in DRA demographic files).",
    )

    p.add_argument("--output", type=Path, default=Path("data/precinct_demographics_2020_vap.csv"))
    p.add_argument("--round-pct", type=int, default=2)
    return p.parse_args()


def main() -> int:
    args = parse_args()

    cw = pd.read_csv(args.crosswalk, usecols=["block_geoid20", "precinct_id"], dtype=str)
    cw["block_geoid20"] = _coerce_block_geoid(cw["block_geoid20"])
    cw["precinct_id"] = cw["precinct_id"].astype(str).str.strip()
    cw = cw[cw["precinct_id"] != ""].copy()

    total_df = _read_block_metric(args.race_block_csv, args.race_geoid_col, args.total_col, "vap_18plus")
    white_df = _read_block_metric(args.race_block_csv, args.race_geoid_col, args.white_col, "white_vap")
    black_df = _read_block_metric(args.race_block_csv, args.race_geoid_col, args.black_col, "black_vap")

    demo = total_df.merge(white_df, on="block_geoid20", how="outer")
    demo = demo.merge(black_df, on="block_geoid20", how="outer")

    has_hispanic = bool(str(args.hispanic_col or "").strip())
    if has_hispanic:
        hispanic_src = args.hispanic_block_csv or args.race_block_csv
        hispanic_geoid_col = args.hispanic_geoid_col or args.race_geoid_col
        hispanic_df = _read_block_metric(
            hispanic_src,
            hispanic_geoid_col,
            str(args.hispanic_col).strip(),
            "hispanic_vap",
        )
        demo = demo.merge(hispanic_df, on="block_geoid20", how="left")
        demo["hispanic_vap"] = pd.to_numeric(demo["hispanic_vap"], errors="coerce").fillna(0)

    merged = cw.merge(demo, on="block_geoid20", how="left")
    merged["vap_18plus"] = pd.to_numeric(merged["vap_18plus"], errors="coerce").fillna(0)
    merged["white_vap"] = pd.to_numeric(merged["white_vap"], errors="coerce").fillna(0)
    merged["black_vap"] = pd.to_numeric(merged["black_vap"], errors="coerce").fillna(0)
    if has_hispanic:
        merged["hispanic_vap"] = pd.to_numeric(merged["hispanic_vap"], errors="coerce").fillna(0)

    sum_cols = ["vap_18plus", "white_vap", "black_vap"] + (["hispanic_vap"] if has_hispanic else [])
    out = merged.groupby("precinct_id", as_index=False)[sum_cols].sum()
    out = out.sort_values("precinct_id").reset_index(drop=True)

    denom = out["vap_18plus"].replace(0, pd.NA)
    out["white_vap_pct"] = (out["white_vap"] / denom * 100).fillna(0).round(args.round_pct)
    out["black_vap_pct"] = (out["black_vap"] / denom * 100).fillna(0).round(args.round_pct)
    if has_hispanic:
        out["hispanic_vap_pct"] = (out["hispanic_vap"] / denom * 100).fillna(0).round(args.round_pct)
    else:
        out["hispanic_vap"] = pd.NA
        out["hispanic_vap_pct"] = pd.NA

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)

    print(f"Wrote {len(out):,} precinct rows -> {args.output}")
    print(
        "Columns: precinct_id, vap_18plus, white_vap, black_vap, hispanic_vap, "
        "white_vap_pct, black_vap_pct, hispanic_vap_pct"
    )
    print(f"Hispanic source applied: {'yes' if has_hispanic else 'no (columns left blank)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

