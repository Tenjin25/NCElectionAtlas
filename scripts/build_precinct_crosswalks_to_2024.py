"""
Build area-weighted crosswalks from local precinct geometries
(data/Voting_Precincts.geojson) to current-cycle NC district lines.

Preferred inputs are local 2022-era files (CD118/SLDL/SLDU) if present.
Falls back to previously downloaded Census legislative files under data/census.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd


TARGET_CRS = "EPSG:5070"


def _normalize_precinct_key(county: str, precinct: str) -> str:
    return f"{str(county).strip().upper()} - {str(precinct).strip().upper()}"


def _load_precincts(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    need = ["county_nam", "prec_id", "geometry"]
    missing = [c for c in need if c not in gdf.columns]
    if missing:
        raise ValueError(f"Precinct GeoJSON missing columns: {missing}")

    gdf = gdf[need].copy()
    gdf["precinct_key"] = gdf.apply(
        lambda r: _normalize_precinct_key(r["county_nam"], r["prec_id"]), axis=1
    )
    return gdf


def _build_crosswalk(
    *,
    precincts: gpd.GeoDataFrame,
    district_shp: Path,
    district_col: str,
    district_type: str,
    out_csv: Path,
) -> None:
    districts = gpd.read_file(district_shp)
    geoid_col = "GEOID" if "GEOID" in districts.columns else "GEOID20"
    name_col = "NAMELSAD" if "NAMELSAD" in districts.columns else "NAMELSAD20"
    districts = districts[[district_col, geoid_col, name_col, "geometry"]].copy()
    districts = districts.rename(
        columns={
            district_col: "district",
            geoid_col: "district_geoid",
            name_col: "district_name",
        }
    )
    districts["district"] = districts["district"].astype(str).str.strip()

    p = precincts.to_crs(TARGET_CRS).copy()
    d = districts.to_crs(TARGET_CRS).copy()
    p["precinct_area_m2"] = p.geometry.area

    inter = gpd.overlay(p, d, how="intersection", keep_geom_type=False)
    inter["intersect_area_m2"] = inter.geometry.area
    inter = inter[inter["intersect_area_m2"] > 0].copy()
    inter["area_weight"] = inter["intersect_area_m2"] / inter["precinct_area_m2"]
    inter["area_weight"] = inter["area_weight"].clip(lower=0, upper=1)

    out = inter[
        [
            "precinct_key",
            "district",
            "district_geoid",
            "district_name",
            "intersect_area_m2",
            "precinct_area_m2",
            "area_weight",
        ]
    ].copy()
    # Human-friendly district fields in addition to Census GEOID.
    out["district_num"] = pd.to_numeric(out["district"], errors="coerce")
    width = 3 if district_type == "state_house" else 2
    out["district_code"] = out["district_num"].map(
        lambda x: f"{int(x):0{width}d}" if pd.notna(x) else ""
    )
    out.loc[out["district_code"] == "", "district_code"] = out["district"].astype(str)
    prefix = (
        "HD" if district_type == "state_house"
        else "SD" if district_type == "state_senate"
        else "CD"
    )
    out["district_label"] = out["district_code"].map(lambda x: f"{prefix}-{x}")
    out["district_type"] = district_type
    out["target_year"] = 2024

    # Re-normalize to sum to 1 for each precinct key
    sums = out.groupby("precinct_key")["area_weight"].sum().rename("sum_w")
    out = out.join(sums, on="precinct_key")
    out["area_weight"] = out["area_weight"] / out["sum_w"]
    out = out.drop(columns=["sum_w"])
    out = out.sort_values(["precinct_key", "area_weight"], ascending=[True, False])

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)

    coverage = out["precinct_key"].nunique() / p["precinct_key"].nunique()
    wsum = out.groupby("precinct_key")["area_weight"].sum()
    print(f"{district_type}: {out_csv}")
    print(f"  rows: {len(out):,}")
    print(f"  precinct coverage: {coverage:.4%}")
    print(f"  weight min/max: {wsum.min():.6f} / {wsum.max():.6f}")


def _resolve_existing_path(candidates: list[Path]) -> Path:
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "No candidate shapefile found. Tried:\n" + "\n".join(str(p) for p in candidates)
    )


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    data_dir = root / "data"
    census = data_dir / "census"

    precincts = _load_precincts(data_dir / "Voting_Precincts.geojson")
    house_shp = _resolve_existing_path(
        [
            data_dir / "tl_2022_37_sldl" / "tl_2022_37_sldl.shp",
            census / "tl_2024_37_sldl" / "tl_2024_37_sldl.shp",
        ]
    )
    senate_shp = _resolve_existing_path(
        [
            data_dir / "tl_2022_37_sldu" / "tl_2022_37_sldu.shp",
            census / "tl_2024_37_sldu" / "tl_2024_37_sldu.shp",
        ]
    )
    congress_shp = _resolve_existing_path(
        [
            data_dir / "tl_2022_37_cd118" / "tl_2022_37_cd118.shp",
            data_dir / "tl_2023_37_cd118" / "tl_2023_37_cd118.shp",
        ]
    )

    _build_crosswalk(
        precincts=precincts,
        district_shp=house_shp,
        district_col="SLDLST",
        district_type="state_house",
        out_csv=data_dir / "crosswalks" / "precinct_to_2022_state_house.csv",
    )
    _build_crosswalk(
        precincts=precincts,
        district_shp=senate_shp,
        district_col="SLDUST",
        district_type="state_senate",
        out_csv=data_dir / "crosswalks" / "precinct_to_2022_state_senate.csv",
    )
    _build_crosswalk(
        precincts=precincts,
        district_shp=congress_shp,
        district_col="CD118FP",
        district_type="congressional",
        out_csv=data_dir / "crosswalks" / "precinct_to_cd118.csv",
    )


if __name__ == "__main__":
    main()
