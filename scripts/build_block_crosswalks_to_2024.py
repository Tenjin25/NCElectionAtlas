"""
Build block-level crosswalks from NC 2020 Census blocks (TABBLOCK20)
to 2024 NC district lines (state house, state senate, CD119) using
TIGER/Line district geometries.

Outputs:
  - data/crosswalks/block20_to_2024_state_house.csv
  - data/crosswalks/block20_to_2024_state_senate.csv
  - data/crosswalks/block20_to_cd119.csv

Also writes assignment-compatible files for
`build_district_contests_from_batch_shatter.py`:
  - data/tmp/block_assign_extract_2024/SL_2024_4.csv (Block,District)
  - data/tmp/block_assign_extract_2024/SL_2024_2.csv (Block,District)
  - data/tmp/block_assign_extract_2024/NC_CD119.csv (GEOID,CDFP)
"""
from __future__ import annotations

from pathlib import Path
import zipfile

import geopandas as gpd
import pandas as pd


PLAN_ID = "tiger_line_2024"
PLAN_LABEL = "TIGER/Line 2024 NC districts (SLDL/SLDU/CD119)"
TARGET_YEAR = 2024
TARGET_CRS = "EPSG:5070"


def _read_single_shp_from_zip(zip_path: Path) -> gpd.GeoDataFrame:
    if not zip_path.exists():
        raise FileNotFoundError(f"Missing zip: {zip_path}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        shp_names = [n for n in zf.namelist() if n.lower().endswith(".shp")]
    if not shp_names:
        raise FileNotFoundError(f"No .shp file found in {zip_path}")
    shp_name = shp_names[0]
    uri = f"zip://{zip_path.as_posix()}!{shp_name}"
    return gpd.read_file(uri)


def _read_geo(path: Path) -> gpd.GeoDataFrame:
    if path.suffix.lower() == ".zip":
        return _read_single_shp_from_zip(path)
    return gpd.read_file(path)


def _load_blocks(block_zip: Path) -> gpd.GeoDataFrame:
    gdf = _read_single_shp_from_zip(block_zip)
    geoid_col = "GEOID20" if "GEOID20" in gdf.columns else "GEOID"
    county_col = "COUNTYFP20" if "COUNTYFP20" in gdf.columns else "COUNTYFP"
    cols = [geoid_col, county_col, "geometry"]
    missing = [c for c in cols if c not in gdf.columns]
    if missing:
        raise ValueError(f"Block file missing columns: {missing}")
    out = gdf[cols].copy()
    out = out.rename(columns={geoid_col: "block_geoid20", county_col: "countyfp20"})
    out["block_geoid20"] = out["block_geoid20"].astype(str).str.strip().str.zfill(15)
    out["countyfp20"] = out["countyfp20"].astype(str).str.strip().str.zfill(3)
    return out


def _load_districts(path: Path, district_col: str) -> gpd.GeoDataFrame:
    d = _read_geo(path)
    geoid_col = "GEOID" if "GEOID" in d.columns else "GEOID20"
    name_col = "NAMELSAD" if "NAMELSAD" in d.columns else "NAMELSAD20"
    cols = [district_col, geoid_col, name_col, "geometry"]
    missing = [c for c in cols if c not in d.columns]
    if missing:
        raise ValueError(f"District file missing columns: {missing}")
    out = d[cols].copy()
    out = out.rename(
        columns={
            district_col: "district",
            geoid_col: "district_geoid",
            name_col: "district_name",
        }
    )
    out["district"] = out["district"].astype(str).str.strip()
    return out


def _district_label(district: str, district_type: str) -> str:
    dnum = pd.to_numeric(pd.Series([district]), errors="coerce").iloc[0]
    if district_type == "state_house":
        width = 3
        prefix = "HD"
    elif district_type == "state_senate":
        width = 2
        prefix = "SD"
    else:
        width = 2
        prefix = "CD"
    if pd.notna(dnum):
        code = f"{int(dnum):0{width}d}"
    else:
        code = district
    return f"{prefix}-{code}"


def build_crosswalk(
    *,
    blocks: gpd.GeoDataFrame,
    district_path: Path,
    district_col: str,
    district_type: str,
    out_csv: Path,
) -> pd.DataFrame:
    d = _load_districts(district_path, district_col)

    # Fast path: representative point join (district lines are effectively block-built).
    b_points = blocks.copy()
    b_points["geometry"] = b_points.geometry.representative_point()
    b_points = b_points.to_crs(d.crs)
    d_native = d.to_crs(d.crs)

    joined = gpd.sjoin(
        b_points[["block_geoid20", "countyfp20", "geometry"]],
        d_native[["district", "district_geoid", "district_name", "geometry"]],
        how="left",
        predicate="within",
    )
    out = joined[["block_geoid20", "countyfp20", "district", "district_geoid", "district_name"]].copy()

    unmatched = out["district"].isna()
    unmatched_count = int(unmatched.sum())

    # Fallback for boundary/topology edge cases: max-area overlay on unmatched blocks.
    if unmatched_count > 0:
        b_un = blocks.loc[out.index[unmatched]].copy().to_crs(TARGET_CRS)
        d_a = d.to_crs(TARGET_CRS)
        inter = gpd.overlay(
            b_un[["block_geoid20", "countyfp20", "geometry"]],
            d_a[["district", "district_geoid", "district_name", "geometry"]],
            how="intersection",
            keep_geom_type=False,
        )
        if not inter.empty:
            inter["a"] = inter.geometry.area
            inter = inter.sort_values(["block_geoid20", "a"], ascending=[True, False])
            top = inter.drop_duplicates(subset=["block_geoid20"], keep="first")
            fix = top.set_index("block_geoid20")[["district", "district_geoid", "district_name"]]
            out = out.set_index("block_geoid20")
            for bgeoid, r in fix.iterrows():
                out.loc[bgeoid, "district"] = r["district"]
                out.loc[bgeoid, "district_geoid"] = r["district_geoid"]
                out.loc[bgeoid, "district_name"] = r["district_name"]
            out = out.reset_index()

    out["district"] = out["district"].astype(str).str.strip()
    out["district_label"] = out["district"].map(lambda x: _district_label(x, district_type))
    out["district_type"] = district_type
    out["target_year"] = TARGET_YEAR
    out["plan_id"] = PLAN_ID
    out["plan_label"] = PLAN_LABEL
    out["area_weight"] = 1.0

    out = out.sort_values(["block_geoid20"])
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)

    matched = int(out["district"].notna().sum())
    total = len(out)
    print(f"{district_type}: wrote {out_csv}")
    print(f"  blocks: {total:,}")
    print(f"  matched: {matched:,} ({matched/total:.2%})")
    if unmatched_count:
        print(f"  unmatched before fallback: {unmatched_count:,}")
    return out


def _write_assignment_files(
    *,
    house_df: pd.DataFrame,
    senate_df: pd.DataFrame,
    cd_df: pd.DataFrame,
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    house_out = house_df[["block_geoid20", "district"]].copy()
    house_out.columns = ["Block", "District"]
    house_out.to_csv(out_dir / "SL_2024_4.csv", index=False)

    senate_out = senate_df[["block_geoid20", "district"]].copy()
    senate_out.columns = ["Block", "District"]
    senate_out.to_csv(out_dir / "SL_2024_2.csv", index=False)

    cd_out = cd_df[["block_geoid20", "district"]].copy()
    cd_out.columns = ["GEOID", "CDFP"]
    cd_out.to_csv(out_dir / "NC_CD119.csv", index=False)

    print(f"Wrote assignment-compatible files in {out_dir}")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    data = root / "data"
    block_zip = data / "census" / "block files" / "tl_2020_37_tabblock20.zip"
    crosswalk_dir = data / "crosswalks"
    assign_dir = data / "tmp" / "block_assign_extract_2024"

    house_zip = data / "tl_2024_37_sldl.zip"
    senate_zip = data / "tl_2024_37_sldu.zip"
    cd_zip = data / "tl_2024_37_cd119.zip"

    if not house_zip.exists() or not senate_zip.exists() or not cd_zip.exists():
        raise FileNotFoundError(
            "Missing 2024 district ZIPs under data/: "
            "tl_2024_37_sldl.zip, tl_2024_37_sldu.zip, tl_2024_37_cd119.zip"
        )

    blocks = _load_blocks(block_zip)
    print(f"Loaded blocks: {len(blocks):,} from {block_zip}")

    house_df = build_crosswalk(
        blocks=blocks,
        district_path=house_zip,
        district_col="SLDLST",
        district_type="state_house",
        out_csv=crosswalk_dir / "block20_to_2024_state_house.csv",
    )
    senate_df = build_crosswalk(
        blocks=blocks,
        district_path=senate_zip,
        district_col="SLDUST",
        district_type="state_senate",
        out_csv=crosswalk_dir / "block20_to_2024_state_senate.csv",
    )
    cd_df = build_crosswalk(
        blocks=blocks,
        district_path=cd_zip,
        district_col="CD119FP",
        district_type="congressional",
        out_csv=crosswalk_dir / "block20_to_cd119.csv",
    )

    _write_assignment_files(
        house_df=house_df,
        senate_df=senate_df,
        cd_df=cd_df,
        out_dir=assign_dir,
    )


if __name__ == "__main__":
    main()
