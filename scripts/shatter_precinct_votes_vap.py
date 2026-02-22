"""
Shatter precinct-level votes to blocks using VAP weights, then optionally
aggregate to districts.

Core allocation:
  block_votes = precinct_votes * (block_vap / precinct_total_vap)

Design choices for stability:
- Uses Decimal arithmetic for intermediate math.
- Enforces a precinct-level zero-sum guard by assigning residual to the
  largest-weight block in each precinct.
- Keeps fractional votes through block output and only rounds at the
  district aggregation stage (optional).
"""
from __future__ import annotations

import argparse
from decimal import Decimal, getcontext
from pathlib import Path

import pandas as pd


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value).strip())


def load_results(path: Path, precinct_col: str, votes_col: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={precinct_col: str})
    if precinct_col not in df.columns or votes_col not in df.columns:
        raise ValueError(f"Results CSV missing columns: {precinct_col}, {votes_col}")
    out = df[[precinct_col, votes_col]].copy()
    out.columns = ["precinct_id", "votes"]
    out["precinct_id"] = out["precinct_id"].astype(str).str.strip()
    out = out[out["precinct_id"] != ""].copy()
    out["votes"] = out["votes"].map(_to_decimal)
    return out


def load_crosswalk(path: Path, precinct_col: str, block_col: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={precinct_col: str, block_col: str})
    if precinct_col not in df.columns or block_col not in df.columns:
        raise ValueError(f"Crosswalk CSV missing columns: {precinct_col}, {block_col}")
    out = df[[block_col, precinct_col]].copy()
    out.columns = ["block_geoid20", "precinct_id"]
    out["block_geoid20"] = out["block_geoid20"].astype(str).str.strip().str.zfill(15)
    out["precinct_id"] = out["precinct_id"].astype(str).str.strip()
    out = out[(out["block_geoid20"] != "") & (out["precinct_id"] != "")].copy()
    return out


def load_vap(path: Path, block_col: str, vap_col: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={block_col: str})
    if block_col not in df.columns or vap_col not in df.columns:
        raise ValueError(f"VAP CSV missing columns: {block_col}, {vap_col}")
    out = df[[block_col, vap_col]].copy()
    out.columns = ["block_geoid20", "vap_count"]
    out["block_geoid20"] = out["block_geoid20"].astype(str).str.strip().str.zfill(15)
    out["vap_count"] = out["vap_count"].map(_to_decimal)
    out = out[(out["block_geoid20"] != "") & (out["vap_count"] >= 0)].copy()
    return out


def shatter_votes(
    results_df: pd.DataFrame,
    crosswalk_df: pd.DataFrame,
    vap_df: pd.DataFrame,
    precision: int = 28,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    getcontext().prec = precision

    blocks = crosswalk_df.merge(vap_df, on="block_geoid20", how="left")
    blocks["vap_count"] = blocks["vap_count"].fillna(Decimal(0))

    precinct_vap = (
        blocks.groupby("precinct_id", as_index=False)["vap_count"]
        .sum()
        .rename(columns={"vap_count": "total_precinct_vap"})
    )
    blocks = blocks.merge(precinct_vap, on="precinct_id", how="left")

    shattered = blocks.merge(results_df, on="precinct_id", how="inner")
    if shattered.empty:
        raise ValueError("No matched precincts between results and crosswalk.")

    def _calc_weight(row: pd.Series) -> Decimal:
        den = row["total_precinct_vap"]
        if den == 0:
            return Decimal(0)
        return row["vap_count"] / den

    shattered["block_weight"] = shattered.apply(_calc_weight, axis=1)
    shattered["block_votes_raw"] = shattered["votes"] * shattered["block_weight"]

    # Zero-sum guard: enforce sum(block_votes) == precinct votes exactly.
    def _rebalance(group: pd.DataFrame) -> pd.DataFrame:
        g = group.copy()
        target = g["votes"].iloc[0]
        current = g["block_votes_raw"].sum()
        residual = target - current
        if residual != 0 and len(g) > 0:
            idx = g["block_weight"].astype(float).idxmax()
            g.loc[idx, "block_votes_raw"] = g.loc[idx, "block_votes_raw"] + residual
        return g

    shattered = (
        shattered.groupby("precinct_id", group_keys=False)
        .apply(_rebalance)
        .reset_index(drop=True)
    )

    # Audit table by precinct.
    precinct_audit = (
        shattered.groupby("precinct_id", as_index=False)
        .agg(
            precinct_votes=("votes", "first"),
            block_votes_sum=("block_votes_raw", "sum"),
            total_precinct_vap=("total_precinct_vap", "first"),
        )
    )
    precinct_audit["delta"] = precinct_audit["precinct_votes"] - precinct_audit["block_votes_sum"]

    return shattered, precinct_audit


def aggregate_to_districts(
    shattered_df: pd.DataFrame,
    district_crosswalk_csv: Path,
    block_col: str,
    district_col: str,
) -> pd.DataFrame:
    d = pd.read_csv(district_crosswalk_csv, dtype={block_col: str, district_col: str})
    d.columns = [str(c).strip() for c in d.columns]
    block_col = block_col.strip()
    district_col = district_col.strip()
    if block_col not in d.columns or district_col not in d.columns:
        raise ValueError(f"District crosswalk missing columns: {block_col}, {district_col}")
    d = d[[block_col, district_col]].copy()
    d.columns = ["block_geoid20", "district"]
    d["block_geoid20"] = d["block_geoid20"].astype(str).str.strip().str.zfill(15)
    d["district"] = d["district"].astype(str).str.strip()

    m = shattered_df.merge(d, on="block_geoid20", how="inner")
    if m.empty:
        raise ValueError("No matched blocks between shattered results and district crosswalk.")

    agg = m.groupby("district", as_index=False)["block_votes_raw"].sum()
    # Round only at district stage.
    agg["votes_rounded"] = agg["block_votes_raw"].map(lambda x: int(x.quantize(Decimal("1"))))
    return agg.sort_values("district")


def main() -> None:
    parser = argparse.ArgumentParser(description="DRA-style VAP shatter from precinct votes to blocks.")
    parser.add_argument("--results-csv", type=Path, required=True)
    parser.add_argument("--crosswalk-csv", type=Path, required=True)
    parser.add_argument("--vap-csv", type=Path, required=True)
    parser.add_argument("--out-block-csv", type=Path, required=True)
    parser.add_argument("--out-audit-csv", type=Path, required=True)
    parser.add_argument("--results-precinct-col", default="precinct_id")
    parser.add_argument("--results-votes-col", default="votes")
    parser.add_argument("--crosswalk-precinct-col", default="precinct_id")
    parser.add_argument("--crosswalk-block-col", default="block_geoid20")
    parser.add_argument("--vap-block-col", default="block_geoid20")
    parser.add_argument("--vap-count-col", default="vap_count")
    parser.add_argument("--precision", type=int, default=28)
    parser.add_argument("--district-crosswalk-csv", type=Path, default=None)
    parser.add_argument("--district-crosswalk-block-col", default="block_geoid20")
    parser.add_argument("--district-crosswalk-district-col", default="district")
    parser.add_argument("--out-district-csv", type=Path, default=None)
    args = parser.parse_args()

    results_df = load_results(args.results_csv, args.results_precinct_col, args.results_votes_col)
    crosswalk_df = load_crosswalk(args.crosswalk_csv, args.crosswalk_precinct_col, args.crosswalk_block_col)
    vap_df = load_vap(args.vap_csv, args.vap_block_col, args.vap_count_col)

    shattered, audit = shatter_votes(results_df, crosswalk_df, vap_df, precision=args.precision)

    out_blocks = shattered[
        ["precinct_id", "block_geoid20", "vap_count", "total_precinct_vap", "block_weight", "votes", "block_votes_raw"]
    ].copy()
    out_blocks["block_weight"] = out_blocks["block_weight"].map(str)
    out_blocks["votes"] = out_blocks["votes"].map(str)
    out_blocks["vap_count"] = out_blocks["vap_count"].map(str)
    out_blocks["total_precinct_vap"] = out_blocks["total_precinct_vap"].map(str)
    out_blocks["block_votes_raw"] = out_blocks["block_votes_raw"].map(str)

    out_audit = audit.copy()
    out_audit["precinct_votes"] = out_audit["precinct_votes"].map(str)
    out_audit["block_votes_sum"] = out_audit["block_votes_sum"].map(str)
    out_audit["total_precinct_vap"] = out_audit["total_precinct_vap"].map(str)
    out_audit["delta"] = out_audit["delta"].map(str)

    args.out_block_csv.parent.mkdir(parents=True, exist_ok=True)
    args.out_audit_csv.parent.mkdir(parents=True, exist_ok=True)
    out_blocks.to_csv(args.out_block_csv, index=False)
    out_audit.to_csv(args.out_audit_csv, index=False)

    print(f"Wrote block-level shattered votes: {args.out_block_csv}")
    print(f"Wrote zero-sum audit: {args.out_audit_csv}")
    print(f"Shattered rows: {len(out_blocks):,}")
    print(f"Precincts audited: {len(out_audit):,}")

    if args.district_crosswalk_csv and args.out_district_csv:
        d = aggregate_to_districts(
            shattered_df=shattered,
            district_crosswalk_csv=args.district_crosswalk_csv,
            block_col=args.district_crosswalk_block_col,
            district_col=args.district_crosswalk_district_col,
        )
        d_out = d.copy()
        d_out["block_votes_raw"] = d_out["block_votes_raw"].map(str)
        args.out_district_csv.parent.mkdir(parents=True, exist_ok=True)
        d_out.to_csv(args.out_district_csv, index=False)
        print(f"Wrote district aggregation: {args.out_district_csv}")


if __name__ == "__main__":
    main()
