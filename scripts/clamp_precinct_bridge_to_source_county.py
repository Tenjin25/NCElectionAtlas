#!/usr/bin/env python3
"""Clamp precinct->OneMap VAP bridges so shares never cross county lines.

Block-based VAP joins can place a small share of an SBE precinct onto a
neighboring county's OneMap polygon. That preserves statewide totals while
inflating/deflating county margins when contest rows are summed — which forced
canonical county_totals / county_contests workarounds.

This script drops cross-county bridge edges and renormalizes remaining shares.
Sources that only had cross-county targets become unmapped (0 rows); remappers
then pass the source key through, keeping votes in the source county.

Usage:
  python scripts/clamp_precinct_bridge_to_source_county.py
  python scripts/clamp_precinct_bridge_to_source_county.py --write
  python scripts/clamp_precinct_bridge_to_source_county.py --write --glob "precinct_sbe_*_to_onemap_2025_12_vap.csv"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CROSSWALK_DIR = ROOT / "data" / "crosswalks"
DEFAULT_GLOB = "precinct_sbe_*_to_onemap_*_vap.csv"


def county_of(key: object) -> str:
    value = str(key or "").strip().upper()
    if " - " not in value:
        return value
    return value.split(" - ", 1)[0].strip()


def clamp_bridge(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    required = {"sbe_precinct_id", "onemap_precinct_id", "share"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"bridge missing columns: {sorted(missing)}")

    work = df.copy()
    work["sbe_precinct_id"] = work["sbe_precinct_id"].astype(str).str.strip().str.upper()
    work["onemap_precinct_id"] = work["onemap_precinct_id"].astype(str).str.strip().str.upper()
    work["share"] = pd.to_numeric(work["share"], errors="coerce").fillna(0.0)
    if "vap_weight" in work.columns:
        work["vap_weight"] = pd.to_numeric(work["vap_weight"], errors="coerce").fillna(0.0)
    if "block_count" in work.columns:
        work["block_count"] = pd.to_numeric(work["block_count"], errors="coerce").fillna(0).astype(int)

    src_county = work["sbe_precinct_id"].map(county_of)
    tgt_county = work["onemap_precinct_id"].map(county_of)
    same = src_county == tgt_county
    cross_rows = int((~same).sum())
    cross_sources = int(work.loc[~same, "sbe_precinct_id"].nunique())

    kept = work.loc[same].copy()
    before_sources = int(work["sbe_precinct_id"].nunique())
    after_sources = int(kept["sbe_precinct_id"].nunique())
    orphan_sources = before_sources - after_sources

    weight_col = "vap_weight" if "vap_weight" in kept.columns else None
    if weight_col:
        totals = kept.groupby("sbe_precinct_id", as_index=False)[weight_col].sum().rename(
            columns={weight_col: "_src_total"}
        )
        kept = kept.merge(totals, on="sbe_precinct_id", how="left")
        kept["share"] = kept[weight_col] / kept["_src_total"].where(kept["_src_total"] > 0, 1.0)
        # Zero-weight leftovers: fall back to equal block / row weights.
        zero_mask = kept["_src_total"] <= 0
        if zero_mask.any():
            if "block_count" in kept.columns:
                blk = kept.groupby("sbe_precinct_id")["block_count"].transform("sum")
                kept.loc[zero_mask, "share"] = kept.loc[zero_mask, "block_count"] / blk.loc[zero_mask].where(
                    blk.loc[zero_mask] > 0, 1.0
                )
            else:
                counts = kept.groupby("sbe_precinct_id")["share"].transform("size")
                kept.loc[zero_mask, "share"] = 1.0 / counts.loc[zero_mask]
        if "src_vap_total" in kept.columns:
            kept["src_vap_total"] = kept["_src_total"]
        if "sbe_vap_total" in kept.columns:
            kept["sbe_vap_total"] = kept["_src_total"]
        kept = kept.drop(columns=["_src_total"])
    else:
        totals = kept.groupby("sbe_precinct_id")["share"].transform("sum")
        kept["share"] = kept["share"] / totals.where(totals > 0, 1.0)

    kept = kept.sort_values(["sbe_precinct_id", "share"], ascending=[True, False]).reset_index(drop=True)
    stats = {
        "rows_before": int(len(work)),
        "rows_after": int(len(kept)),
        "cross_county_rows_removed": cross_rows,
        "cross_county_sources": cross_sources,
        "sources_before": before_sources,
        "sources_after": after_sources,
        "sources_unmapped_after_clamp": orphan_sources,
    }
    return kept, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Overwrite bridge CSVs in place.")
    parser.add_argument(
        "--glob",
        default=DEFAULT_GLOB,
        help=f'Glob under data/crosswalks (default: {DEFAULT_GLOB}).',
    )
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Optional explicit bridge CSV path(s). Repeatable.",
    )
    args = parser.parse_args()

    paths: list[Path] = []
    if args.path:
        paths.extend(Path(p) if Path(p).is_absolute() else ROOT / p for p in args.path)
    else:
        paths.extend(sorted(CROSSWALK_DIR.glob(args.glob)))

    summary = {"write": args.write, "files": []}
    for path in paths:
        if not path.exists():
            summary["files"].append({"path": str(path), "error": "missing"})
            continue
        df = pd.read_csv(path, dtype=str)
        clamped, stats = clamp_bridge(df)
        item = {
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            **stats,
            "changed": stats["rows_before"] != stats["rows_after"]
            or stats["cross_county_rows_removed"] > 0,
        }
        if args.write and item["changed"]:
            clamped.to_csv(path, index=False)
            item["written"] = True
        summary["files"].append(item)

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
