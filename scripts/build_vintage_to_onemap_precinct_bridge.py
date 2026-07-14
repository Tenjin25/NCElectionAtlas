"""Build a VAP-weighted precinct-vintage bridge onto current OneMap precincts."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-block-map", type=Path, required=True)
    p.add_argument(
        "--onemap-block-map",
        type=Path,
        default=ROOT / "data/crosswalks/block20_to_onemap_2025.csv",
    )
    p.add_argument("--vap-csv", type=Path, default=ROOT / "data/census/block_vap_2020_nc.csv")
    p.add_argument("--out-csv", type=Path, required=True)
    p.add_argument("--source-key-name", default="sbe_precinct_id")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    src = pd.read_csv(args.source_block_map, dtype=str)
    one = pd.read_csv(args.onemap_block_map, dtype=str)
    vap = pd.read_csv(args.vap_csv, dtype=str)

    src = src[["block_geoid20", "precinct_id"]].rename(
        columns={"precinct_id": args.source_key_name}
    )
    one = one[["block_geoid20", "precinct_id"]].rename(
        columns={"precinct_id": "onemap_precinct_id"}
    )
    def _norm_precinct_id(series: pd.Series) -> pd.Series:
        s = series.astype(str).str.strip().str.upper().str.replace(r"\s+", " ", regex=True)
        parts = s.str.split(" - ", n=1, expand=True)
        if parts.shape[1] < 2:
            return s
        county = parts[0].fillna("").str.replace("_", " ", regex=False).str.replace(r"\s+", " ", regex=True)
        prec = parts[1].fillna("").str.replace(r"\s+", " ", regex=True)
        out = county + " - " + prec
        return out.where(parts[1].notna(), s)

    for frame, col in ((src, args.source_key_name), (one, "onemap_precinct_id")):
        frame["block_geoid20"] = frame["block_geoid20"].astype(str).str.strip().str.zfill(15)
        frame[col] = _norm_precinct_id(frame[col])

    geoid_col = "block_geoid20" if "block_geoid20" in vap.columns else "GEOID20"
    vap_col = "vap_count" if "vap_count" in vap.columns else "vap20"
    vap = vap[[geoid_col, vap_col]].copy()
    vap.columns = ["block_geoid20", "vap_count"]
    vap["block_geoid20"] = vap["block_geoid20"].astype(str).str.strip().str.zfill(15)
    vap["vap_count"] = pd.to_numeric(vap["vap_count"], errors="coerce").fillna(0.0)

    joined = src.merge(one, on="block_geoid20", how="inner").merge(vap, on="block_geoid20", how="left")
    joined["vap_count"] = joined["vap_count"].fillna(0.0)
    src_col = args.source_key_name
    grouped = (
        joined.groupby([src_col, "onemap_precinct_id"], as_index=False)
        .agg(vap_weight=("vap_count", "sum"), block_count=("block_geoid20", "nunique"))
    )
    zero = grouped.groupby(src_col)["vap_weight"].transform("sum") <= 0
    grouped.loc[zero, "vap_weight"] = grouped.loc[zero, "block_count"].astype(float)
    totals = grouped.groupby(src_col, as_index=False)["vap_weight"].sum().rename(
        columns={"vap_weight": "src_vap_total"}
    )
    grouped = grouped.merge(totals, on=src_col, how="left")
    grouped["share"] = grouped["vap_weight"] / grouped["src_vap_total"]
    # Keep bridge schema compatible with remapper (expects sbe_precinct_id).
    if src_col != "sbe_precinct_id":
        grouped = grouped.rename(columns={src_col: "sbe_precinct_id"})
    grouped = grouped.sort_values(["sbe_precinct_id", "share"], ascending=[True, False])
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    grouped.to_csv(args.out_csv, index=False)
    multi = int((grouped.groupby("sbe_precinct_id").size() > 1).sum())
    print(
        f"Wrote {len(grouped):,} -> {args.out_csv} "
        f"(src={grouped['sbe_precinct_id'].nunique():,}, "
        f"onemap={grouped['onemap_precinct_id'].nunique():,}, splits={multi})"
    )


if __name__ == "__main__":
    main()
