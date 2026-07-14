#!/usr/bin/env python3
"""
Build area-overlap crosswalks from vintage VTDs (VTD00 / VTD10) onto modern
NCOneMap Voting_Precincts geometry.

Pre-2012 election exports often use era VTD codes/names (e.g. ALEXANDER - G1 /
"GWALTNEY #1"). Modern geometry frequently merges those units (G1G2, LRSL).
Spatial best-match bridges close that keyspace gap without inventing votes.

Outputs (default prefix data/crosswalks/vtd00_to_nconemap):
  *_detail.csv
  *_best_old_to_new.csv
  *_best_new_to_old.csv
  *_county_summary.csv
  *_summary.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from build_district_results_2024_lines import NC_COUNTY_FIPS  # noqa: E402
from build_precinct_geometry_crosswalks import (  # noqa: E402
    TARGET_CRS,
    build_crosswalk,
    load_precincts,
    write_summary_json,
)

import geopandas as gpd
import pandas as pd

RE_WS = re.compile(r"\s+")


def norm_text(value: object) -> str:
    return RE_WS.sub(" ", str(value or "")).strip().upper()


def load_vtd(
    path: Path,
    *,
    source_label: str,
    county_col: str,
    code_col: str,
    name_col: str,
) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    for col in (county_col, code_col):
        if col not in gdf.columns:
            raise ValueError(f"{path} missing required column {col}")

    keep = [county_col, code_col, "geometry"]
    if name_col in gdf.columns:
        keep.append(name_col)
    out = gdf[keep].copy()
    out = out.rename(
        columns={
            county_col: "county_raw",
            code_col: "precinct_id",
            **({name_col: "precinct_name"} if name_col in keep else {}),
        }
    )
    if "precinct_name" not in out.columns:
        out["precinct_name"] = ""

    def county_name(raw: object) -> str:
        s = str(raw or "").strip()
        if s.isdigit():
            return NC_COUNTY_FIPS.get(s.zfill(3), "")
        return norm_text(s)

    out["county"] = out["county_raw"].map(county_name)
    out["precinct_id"] = out["precinct_id"].map(norm_text)
    out["precinct_name"] = out["precinct_name"].map(norm_text)
    out = out[(out["county"] != "") & (out["precinct_id"] != "")].copy()
    out["precinct_key"] = out["county"] + " - " + out["precinct_id"]
    out["source_label"] = source_label
    return out[["county", "precinct_id", "precinct_name", "precinct_key", "source_label", "geometry"]]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build VTD vintage → modern NCOneMap precinct overlap crosswalks."
    )
    ap.add_argument(
        "--vtd",
        type=Path,
        default=Path("data/census/tl_2008_37_vtd00_merged.geojson"),
        help="Vintage VTD GeoJSON/shapefile",
    )
    ap.add_argument("--county-col", default="COUNTYFP00")
    ap.add_argument("--code-col", default="VTDST00")
    ap.add_argument("--name-col", default="NAME00")
    ap.add_argument("--vtd-label", default="vtd00")
    ap.add_argument(
        "--modern",
        type=Path,
        default=Path("data/Voting_Precincts.geojson"),
        help="Modern Voting_Precincts GeoJSON",
    )
    ap.add_argument("--modern-label", default="nconemap")
    ap.add_argument("--min-share", type=float, default=0.01)
    ap.add_argument(
        "--out-prefix",
        type=Path,
        default=Path("data/crosswalks/vtd00_to_nconemap"),
    )
    args = ap.parse_args()

    vtd_path = args.vtd if args.vtd.is_absolute() else ROOT / args.vtd
    modern_path = args.modern if args.modern.is_absolute() else ROOT / args.modern
    out_prefix = args.out_prefix if args.out_prefix.is_absolute() else ROOT / args.out_prefix

    old_gdf = load_vtd(
        vtd_path,
        source_label=args.vtd_label,
        county_col=args.county_col,
        code_col=args.code_col,
        name_col=args.name_col,
    )
    new_gdf = load_precincts(modern_path, args.modern_label)

    detail_df, best_old, best_new, county_df = build_crosswalk(
        old_gdf=old_gdf,
        new_gdf=new_gdf,
        min_share=args.min_share,
    )

    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    detail_path = out_prefix.with_name(out_prefix.name + "_detail.csv")
    best_old_path = out_prefix.with_name(out_prefix.name + "_best_old_to_new.csv")
    best_new_path = out_prefix.with_name(out_prefix.name + "_best_new_to_old.csv")
    county_path = out_prefix.with_name(out_prefix.name + "_county_summary.csv")
    summary_path = out_prefix.with_name(out_prefix.name + "_summary.json")

    detail_df.sort_values(
        ["county", "old_precinct_key", "intersection_area_m2"],
        ascending=[True, True, False],
    ).to_csv(detail_path, index=False)
    best_old.sort_values(["county", "old_precinct_key"]).to_csv(best_old_path, index=False)
    best_new.sort_values(["county", "new_precinct_key"]).to_csv(best_new_path, index=False)
    county_df.to_csv(county_path, index=False)
    write_summary_json(
        summary_path,
        old_path=vtd_path,
        new_path=modern_path,
        old_label=args.vtd_label,
        new_label=args.modern_label,
        min_share=args.min_share,
        detail_df=detail_df,
        best_old=best_old,
        best_new=best_new,
        county_df=county_df,
    )

    high_confidence = 0
    if not best_old.empty and "old_share" in best_old.columns:
        high_confidence = int((pd.to_numeric(best_old["old_share"], errors="coerce").fillna(0) >= 0.85).sum())

    print(f"Wrote {detail_path}")
    print(f"Wrote {best_old_path}")
    print(f"Wrote {best_new_path}")
    print(f"Wrote {county_path}")
    print(f"Wrote {summary_path}")
    print(
        json.dumps(
            {
                "overlap_rows": int(len(detail_df)),
                "matched_old_vtds": int(best_old["old_precinct_key"].nunique()) if not best_old.empty else 0,
                "matched_new_precincts": int(best_new["new_precinct_key"].nunique()) if not best_new.empty else 0,
                "high_confidence_old_share_ge_0_85": high_confidence,
            }
        )
    )


if __name__ == "__main__":
    main()
