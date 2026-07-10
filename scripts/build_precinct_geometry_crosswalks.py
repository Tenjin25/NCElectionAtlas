from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / ".python-vendor" / "geopandas"
if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))

import geopandas as gpd
import pandas as pd


TARGET_CRS = "EPSG:5070"
RE_WS = re.compile(r"\s+")


def norm_text(value: object) -> str:
    return RE_WS.sub(" ", str(value or "")).strip().upper()


def pick_column(columns: list[str], candidates: list[str]) -> str:
    lookup = {c.upper(): c for c in columns}
    for candidate in candidates:
        hit = lookup.get(candidate.upper())
        if hit:
            return hit
    raise ValueError(f"Missing expected column. Tried: {candidates}")


def load_precincts(path: Path, source_label: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    county_col = pick_column(
        list(gdf.columns),
        ["county_nam", "COUNTYNAME", "CountyName", "county", "COUNTY"],
    )
    precinct_col = pick_column(
        list(gdf.columns),
        ["prec_id", "PREC_ID", "precinct", "PRECINCT", "vtd", "VTD"],
    )

    desc_col = None
    for candidate in ["enr_desc", "ENR_DESC", "label", "LABEL", "name", "NAME"]:
        if candidate in gdf.columns:
            desc_col = candidate
            break

    keep = [county_col, precinct_col, "geometry"]
    if desc_col:
        keep.append(desc_col)
    out = gdf[keep].copy()
    out = out.rename(
        columns={
            county_col: "county",
            precinct_col: "precinct_id",
            **({desc_col: "precinct_name"} if desc_col else {}),
        }
    )
    if "precinct_name" not in out.columns:
        out["precinct_name"] = ""

    out["county"] = out["county"].map(norm_text)
    out["precinct_id"] = out["precinct_id"].map(norm_text)
    out["precinct_name"] = out["precinct_name"].map(norm_text)
    out = out[(out["county"] != "") & (out["precinct_id"] != "")].copy()
    out["precinct_key"] = out["county"] + " - " + out["precinct_id"]
    out["source_label"] = source_label
    return out


def build_crosswalk(
    old_gdf: gpd.GeoDataFrame,
    new_gdf: gpd.GeoDataFrame,
    min_share: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    old_proj = old_gdf.to_crs(TARGET_CRS).copy()
    new_proj = new_gdf.to_crs(TARGET_CRS).copy()
    old_proj["old_area_m2"] = old_proj.geometry.area
    new_proj["new_area_m2"] = new_proj.geometry.area

    detail_frames: list[pd.DataFrame] = []
    county_rows: list[dict[str, object]] = []

    for county in sorted(set(old_proj["county"]) | set(new_proj["county"])):
        old_county = old_proj[old_proj["county"] == county].copy()
        new_county = new_proj[new_proj["county"] == county].copy()
        if old_county.empty or new_county.empty:
            county_rows.append(
                {
                    "county": county,
                    "old_precincts": int(len(old_county)),
                    "new_precincts": int(len(new_county)),
                    "matched_old_precincts": 0,
                    "matched_new_precincts": 0,
                    "split_old_precincts": 0,
                    "split_new_precincts": 0,
                    "overlap_rows": 0,
                }
            )
            continue

        inter = gpd.overlay(old_county, new_county, how="intersection", keep_geom_type=False)
        if inter.empty:
            county_rows.append(
                {
                    "county": county,
                    "old_precincts": int(len(old_county)),
                    "new_precincts": int(len(new_county)),
                    "matched_old_precincts": 0,
                    "matched_new_precincts": 0,
                    "split_old_precincts": 0,
                    "split_new_precincts": 0,
                    "overlap_rows": 0,
                }
            )
            continue

        inter["intersection_area_m2"] = inter.geometry.area
        inter = inter[inter["intersection_area_m2"] > 0].copy()
        if inter.empty:
            continue

        inter["old_share"] = inter["intersection_area_m2"] / inter["old_area_m2"]
        inter["new_share"] = inter["intersection_area_m2"] / inter["new_area_m2"]
        inter["jaccard"] = inter["intersection_area_m2"] / (
            inter["old_area_m2"] + inter["new_area_m2"] - inter["intersection_area_m2"]
        )
        inter = inter[
            (inter["old_share"] >= min_share) | (inter["new_share"] >= min_share)
        ].copy()
        if inter.empty:
            continue

        detail = inter[
            [
                "county_1",
                "precinct_key_1",
                "precinct_id_1",
                "precinct_name_1",
                "old_area_m2",
                "precinct_key_2",
                "precinct_id_2",
                "precinct_name_2",
                "new_area_m2",
                "intersection_area_m2",
                "old_share",
                "new_share",
                "jaccard",
            ]
        ].copy()
        detail = detail.rename(
            columns={
                "county_1": "county",
                "precinct_key_1": "old_precinct_key",
                "precinct_id_1": "old_precinct_id",
                "precinct_name_1": "old_precinct_name",
                "precinct_key_2": "new_precinct_key",
                "precinct_id_2": "new_precinct_id",
                "precinct_name_2": "new_precinct_name",
            }
        )
        detail["rank_for_old"] = (
            detail.groupby("old_precinct_key")["intersection_area_m2"]
            .rank(method="first", ascending=False)
            .astype(int)
        )
        detail["rank_for_new"] = (
            detail.groupby("new_precinct_key")["intersection_area_m2"]
            .rank(method="first", ascending=False)
            .astype(int)
        )
        detail["is_best_for_old"] = detail["rank_for_old"] == 1
        detail["is_best_for_new"] = detail["rank_for_new"] == 1
        detail_frames.append(detail)

        county_rows.append(
            {
                "county": county,
                "old_precincts": int(old_county["precinct_key"].nunique()),
                "new_precincts": int(new_county["precinct_key"].nunique()),
                "matched_old_precincts": int(detail["old_precinct_key"].nunique()),
                "matched_new_precincts": int(detail["new_precinct_key"].nunique()),
                "split_old_precincts": int(
                    (detail.groupby("old_precinct_key")["new_precinct_key"].nunique() > 1).sum()
                ),
                "split_new_precincts": int(
                    (detail.groupby("new_precinct_key")["old_precinct_key"].nunique() > 1).sum()
                ),
                "overlap_rows": int(len(detail)),
            }
        )

    if detail_frames:
        detail_df = pd.concat(detail_frames, ignore_index=True)
    else:
        detail_df = pd.DataFrame(
            columns=[
                "county",
                "old_precinct_key",
                "old_precinct_id",
                "old_precinct_name",
                "old_area_m2",
                "new_precinct_key",
                "new_precinct_id",
                "new_precinct_name",
                "new_area_m2",
                "intersection_area_m2",
                "old_share",
                "new_share",
                "jaccard",
                "rank_for_old",
                "rank_for_new",
                "is_best_for_old",
                "is_best_for_new",
            ]
        )

    best_old = (
        detail_df.sort_values(
            ["old_precinct_key", "intersection_area_m2", "jaccard"],
            ascending=[True, False, False],
        )
        .drop_duplicates("old_precinct_key", keep="first")
        .reset_index(drop=True)
    )
    best_new = (
        detail_df.sort_values(
            ["new_precinct_key", "intersection_area_m2", "jaccard"],
            ascending=[True, False, False],
        )
        .drop_duplicates("new_precinct_key", keep="first")
        .reset_index(drop=True)
    )
    county_df = pd.DataFrame(county_rows).sort_values("county").reset_index(drop=True)
    return detail_df, best_old, best_new, county_df


def write_summary_json(
    out_path: Path,
    *,
    old_path: Path,
    new_path: Path,
    old_label: str,
    new_label: str,
    min_share: float,
    detail_df: pd.DataFrame,
    best_old: pd.DataFrame,
    best_new: pd.DataFrame,
    county_df: pd.DataFrame,
) -> None:
    payload = {
        "old_path": str(old_path),
        "new_path": str(new_path),
        "old_label": old_label,
        "new_label": new_label,
        "min_share": min_share,
        "overlap_rows": int(len(detail_df)),
        "old_precincts_with_match": int(best_old["old_precinct_key"].nunique()) if not best_old.empty else 0,
        "new_precincts_with_match": int(best_new["new_precinct_key"].nunique()) if not best_new.empty else 0,
        "counties_with_splits": county_df.loc[
            (county_df["split_old_precincts"] > 0) | (county_df["split_new_precincts"] > 0),
            "county",
        ].tolist()
        if not county_df.empty
        else [],
        "top_split_counties": county_df.sort_values(
            ["split_old_precincts", "split_new_precincts", "overlap_rows"],
            ascending=[False, False, False],
        )
        .head(25)
        .to_dict(orient="records")
        if not county_df.empty
        else [],
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build overlap crosswalks between two NC precinct GeoJSON files."
    )
    parser.add_argument("--old", required=True, help="Baseline/stable precinct GeoJSON")
    parser.add_argument("--new", required=True, help="Refreshed/current precinct GeoJSON")
    parser.add_argument("--old-label", default="old", help="Label for the baseline geometry")
    parser.add_argument("--new-label", default="new", help="Label for the refreshed geometry")
    parser.add_argument(
        "--min-share",
        type=float,
        default=0.01,
        help="Keep overlaps when either side covers at least this share of area",
    )
    parser.add_argument(
        "--out-prefix",
        required=True,
        help="Output path prefix, e.g. data/crosswalks/precinct_old_to_nconemap",
    )
    args = parser.parse_args()

    root = ROOT
    old_path = Path(args.old)
    new_path = Path(args.new)
    out_prefix = Path(args.out_prefix)
    if not old_path.is_absolute():
        old_path = root / old_path
    if not new_path.is_absolute():
        new_path = root / new_path
    if not out_prefix.is_absolute():
        out_prefix = root / out_prefix

    old_gdf = load_precincts(old_path, args.old_label)
    new_gdf = load_precincts(new_path, args.new_label)
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
        old_path=old_path,
        new_path=new_path,
        old_label=args.old_label,
        new_label=args.new_label,
        min_share=args.min_share,
        detail_df=detail_df,
        best_old=best_old,
        best_new=best_new,
        county_df=county_df,
    )

    print(f"Wrote {detail_path}")
    print(f"Wrote {best_old_path}")
    print(f"Wrote {best_new_path}")
    print(f"Wrote {county_path}")
    print(f"Wrote {summary_path}")
    print(
        json.dumps(
            {
                "overlap_rows": int(len(detail_df)),
                "matched_old_precincts": int(best_old['old_precinct_key'].nunique()) if not best_old.empty else 0,
                "matched_new_precincts": int(best_new['new_precinct_key'].nunique()) if not best_new.empty else 0,
            }
        )
    )


if __name__ == "__main__":
    main()
