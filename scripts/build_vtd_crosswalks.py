"""
Build area-weighted crosswalks from NC 2020 VTD20 precincts to NC
court-ordered 2022 district lines (SLDL, SLDU, and CD118).
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd


TARGET_CRS = "EPSG:5070"  # CONUS Albers, good for area weighting
PLAN_ID = "nc_court_ordered_2022"
PLAN_LABEL = "NC Court-Ordered 2022 Lines (used for 2022 cycle)"


def _load_vtd(vtd_shp: Path) -> gpd.GeoDataFrame:
    vtd = gpd.read_file(vtd_shp)
    cols = ["GEOID20", "COUNTYFP20", "VTDST20", "NAME20", "geometry"]
    missing = [c for c in cols if c not in vtd.columns]
    if missing:
        raise ValueError(f"VTD file missing columns: {missing}")
    vtd = vtd[cols].copy()
    vtd = vtd.rename(
        columns={
            "GEOID20": "vtd_geoid20",
            "COUNTYFP20": "countyfp20",
            "VTDST20": "vtdst20",
            "NAME20": "vtd_name20",
        }
    )
    return vtd


def _load_districts(district_shp: Path, district_col: str) -> gpd.GeoDataFrame:
    d = gpd.read_file(district_shp)
    geoid_col = "GEOID" if "GEOID" in d.columns else "GEOID20"
    name_col = "NAMELSAD" if "NAMELSAD" in d.columns else "NAMELSAD20"
    cols = [district_col, geoid_col, name_col, "geometry"]
    missing = [c for c in cols if c not in d.columns]
    if missing:
        raise ValueError(f"District file missing columns: {missing}")
    d = d[cols].copy()
    d = d.rename(
        columns={
            district_col: "district",
            geoid_col: "district_geoid",
            name_col: "district_name",
        }
    )
    d["district"] = d["district"].astype(str)
    return d


def build_crosswalk(
    *,
    vtd_shp: Path,
    district_shp: Path,
    district_col: str,
    district_type: str,
    out_csv: Path,
) -> pd.DataFrame:
    vtd = _load_vtd(vtd_shp).to_crs(TARGET_CRS)
    d = _load_districts(district_shp, district_col).to_crs(TARGET_CRS)

    vtd["vtd_area_m2"] = vtd.geometry.area
    vtd_index = vtd[["vtd_geoid20", "vtd_area_m2"]].set_index("vtd_geoid20")

    inter = gpd.overlay(vtd, d, how="intersection", keep_geom_type=False)
    inter["intersect_area_m2"] = inter.geometry.area
    inter["area_weight"] = inter["intersect_area_m2"] / inter["vtd_geoid20"].map(
        vtd_index["vtd_area_m2"]
    )

    # Keep only positive overlaps; clamp minor numeric noise
    inter = inter[inter["intersect_area_m2"] > 0].copy()
    inter["area_weight"] = inter["area_weight"].clip(lower=0, upper=1)

    out = inter[
        [
            "vtd_geoid20",
            "countyfp20",
            "vtdst20",
            "vtd_name20",
            "district",
            "district_geoid",
            "district_name",
            "intersect_area_m2",
            "vtd_area_m2",
            "area_weight",
        ]
    ].copy()
    out["district_type"] = district_type
    out["target_year"] = 2022
    out["plan_id"] = PLAN_ID
    out["plan_label"] = PLAN_LABEL

    # Normalize per-VTD weights to sum exactly to 1 where there is any overlap
    sums = out.groupby("vtd_geoid20")["area_weight"].sum().rename("sum_weight")
    out = out.join(sums, on="vtd_geoid20")
    out["area_weight"] = out["area_weight"] / out["sum_weight"]
    out = out.drop(columns=["sum_weight"])

    out = out.sort_values(["vtd_geoid20", "area_weight"], ascending=[True, False])
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)

    coverage = out["vtd_geoid20"].nunique() / vtd["vtd_geoid20"].nunique()
    print(f"{district_type}: wrote {out_csv}")
    print(f"  rows: {len(out):,}")
    print(f"  unique VTDs: {out['vtd_geoid20'].nunique():,}")
    print(f"  coverage: {coverage:.4%}")
    weight_sums = out.groupby("vtd_geoid20")["area_weight"].sum()
    print(
        f"  weight sum min/max: {weight_sums.min():.6f} / {weight_sums.max():.6f}"
    )

    return out


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    census = root / "data" / "census"
    vtd_shp = census / "tl_2020_37_vtd20" / "tl_2020_37_vtd20.shp"
    sldl_shp = root / "data" / "tl_2022_37_sldl" / "tl_2022_37_sldl.shp"
    sldu_shp = root / "data" / "tl_2022_37_sldu" / "tl_2022_37_sldu.shp"
    cd_shp_candidates = [
        root / "data" / "tl_2022_37_cd118" / "tl_2022_37_cd118.shp",
        root / "data" / "tl_2023_37_cd118" / "tl_2023_37_cd118.shp",
        census / "tl_2022_37_cd118" / "tl_2022_37_cd118.shp",
        census / "tl_2023_37_cd118" / "tl_2023_37_cd118.shp",
    ]
    cd_shp = None
    for p in cd_shp_candidates:
        if p.exists():
            cd_shp = p
            break
    if not sldl_shp.exists() or not sldu_shp.exists():
        raise FileNotFoundError(
            "Missing 2022 court-ordered legislative shapefiles: "
            f"{sldl_shp} and/or {sldu_shp}"
        )

    crosswalk_dir = root / "data" / "crosswalks"

    build_crosswalk(
        vtd_shp=vtd_shp,
        district_shp=sldl_shp,
        district_col="SLDLST",
        district_type="state_house",
        out_csv=crosswalk_dir / "vtd20_to_2024_state_house.csv",
    )
    build_crosswalk(
        vtd_shp=vtd_shp,
        district_shp=sldu_shp,
        district_col="SLDUST",
        district_type="state_senate",
        out_csv=crosswalk_dir / "vtd20_to_2024_state_senate.csv",
    )
    if cd_shp:
        build_crosswalk(
            vtd_shp=vtd_shp,
            district_shp=cd_shp,
            district_col="CD118FP",
            district_type="congressional",
            out_csv=crosswalk_dir / "vtd20_to_cd118.csv",
        )
    else:
        print("congressional: skipped (no CD118 shapefile found)")


if __name__ == "__main__":
    main()
