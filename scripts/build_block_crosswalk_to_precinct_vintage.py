"""Assign 2020 Census blocks to an SBE / VTD precinct polygon vintage.

Outputs a block20->precinct_id CSV suitable as --match-crosswalk-csv for
historical election years, using COUNTY - PREC_ID keys when available.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
REINIT = ROOT / "NCPrecinctMap_reinit_2026-04-29"
BLOCKS = REINIT / "data/census/block files/tl_2020_37_tabblock20.zip"
COUNTY_GEOJSON = ROOT / "data/census/tl_2020_37_county20.geojson"
TARGET_CRS = "EPSG:5070"

KNOWN = {
    "sbe_2012": REINIT / "data/census/SBE_PRECINCTS_20120901/SBE_PRECINCTS_09012012.shp",
    "sbe_2014": REINIT / "data/census/SBE_PRECINCTS_20141016/PRECINCTS.shp",
    "sbe_2016": REINIT / "data/census/SBE_PRECINCTS_20161004/Precincts.shp",
    "sbe_2020": REINIT / "data/census/SBE_PRECINCTS_20201018/SBE_PRECINCTS_20201018.shp",
    "sbe_2022": REINIT / "data/census/SBE_PRECINCTS_20220118/SBE_PRECINCTS_20220118.shp",
    "sbe_2024": REINIT / "data/census/SBE_PRECINCTS_20240723/SBE_PRECINCTS_20240723.shp",
    "vtd00": ROOT / "data/census/tl_2008_37_vtd00_merged.geojson",
    "vtd10": ROOT / "data/census/tl_2012_37_vtd10/tl_2012_37_vtd10.shp",
    "vtd20": ROOT / "data/census/tl_2020_37_vtd20/tl_2020_37_vtd20.shp",
}


def _norm(s: object) -> str:
    # Older SBE vintages use NEW_HANOVER; election/OneMap keys use NEW HANOVER.
    return " ".join(str(s or "").strip().upper().replace("_", " ").split())


def _pick_col(columns: list[str], *candidates: str) -> str | None:
    lower = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def load_county_fips_to_name(path: Path = COUNTY_GEOJSON) -> dict[str, str]:
    """Map 3-digit COUNTYFP -> uppercase county name (e.g. 001 -> ALAMANCE)."""
    if not path.exists():
        # Fallback: derive from an existing block-to-precinct crosswalk.
        fallback = ROOT / "data/crosswalks/block20_to_onemap_2025.csv"
        df = pd.read_csv(fallback, dtype=str)
        county = df["precinct_id"].astype(str).str.split(" - ", n=1).str[0].map(_norm)
        mapping = (
            pd.DataFrame({"countyfp": df["countyfp20"].astype(str).str.zfill(3), "name": county})
            .drop_duplicates("countyfp")
            .set_index("countyfp")["name"]
            .to_dict()
        )
        return mapping

    gdf = gpd.read_file(path)
    fp_col = _pick_col(list(gdf.columns), "COUNTYFP20", "COUNTYFP10", "COUNTYFP00", "COUNTYFP")
    name_col = _pick_col(list(gdf.columns), "NAME20", "NAME10", "NAME00", "NAME")
    if not fp_col or not name_col:
        raise ValueError(f"Cannot find COUNTYFP/NAME in {path}: {list(gdf.columns)}")
    return {
        str(fp).zfill(3): _norm(name)
        for fp, name in zip(gdf[fp_col], gdf[name_col])
        if str(fp).strip() and str(name).strip()
    }


def load_precinct_polygons(path: Path, mode: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if mode.startswith("vtd"):
        # Census VTD NAME* is the precinct/code label, NOT the county name.
        # Build production keys as "COUNTY NAME - VTDST" via COUNTYFP lookup.
        county_fp_col = _pick_col(
            list(gdf.columns), "COUNTYFP00", "COUNTYFP10", "COUNTYFP20", "COUNTYFP"
        )
        prec_col = _pick_col(
            list(gdf.columns), "VTDST00", "VTDST10", "VTDST20", "VTDST", "GEOID10", "GEOID20", "GEOID"
        )
        if not county_fp_col:
            raise ValueError(f"Cannot find COUNTYFP column in {path}: {list(gdf.columns)}")
        if not prec_col:
            raise ValueError(f"Cannot find VTD code column in {path}: {list(gdf.columns)}")

        fips_to_name = load_county_fips_to_name()
        county_fp = gdf[county_fp_col].astype(str).str.zfill(3)
        county = county_fp.map(fips_to_name).fillna("")
        missing = sorted({fp for fp, nm in zip(county_fp, county) if not nm})
        if missing:
            raise ValueError(f"Missing county name for COUNTYFP values: {missing[:10]}")

        if str(prec_col).upper().startswith("VTDST"):
            precinct_id = county + " - " + gdf[prec_col].map(_norm)
        else:
            # GEOID fallback: strip state+county when present (37 + COUNTYFP).
            geoid = gdf[prec_col].map(_norm)
            short = geoid.str.replace(r"^37\d{3}", "", regex=True)
            precinct_id = county + " - " + short.where(short.str.len() > 0, geoid)

        out = gdf[["geometry"]].copy()
        out["precinct_id"] = precinct_id
        return out[out["precinct_id"].str.len() > 3].copy()

    county_col = _pick_col(list(gdf.columns), "county_nam", "COUNTY_NAM", "county_name", "COUNTY")
    prec_col = _pick_col(list(gdf.columns), "prec_id", "PREC_ID", "precinct_id", "PRECINCT")
    if not county_col or not prec_col:
        raise ValueError(f"Cannot find county/precinct columns in {path}: {list(gdf.columns)}")
    out = gdf[["geometry"]].copy()
    out["precinct_id"] = [
        f"{_norm(c)} - {_norm(p)}" for c, p in zip(gdf[county_col], gdf[prec_col])
    ]
    return out[out["precinct_id"].str.len() > 3].copy()


def assign_blocks(blocks: gpd.GeoDataFrame, precincts: gpd.GeoDataFrame) -> pd.DataFrame:
    points = blocks.copy()
    points["geometry"] = points.geometry.representative_point()
    points = points.to_crs(precincts.crs)
    joined = gpd.sjoin(
        points[["block_geoid20", "countyfp20", "geometry"]],
        precincts[["precinct_id", "geometry"]],
        how="left",
        predicate="within",
    )
    out = joined[["block_geoid20", "countyfp20", "precinct_id"]].copy()
    unmatched_ids = out.loc[out["precinct_id"].isna(), "block_geoid20"]
    if len(unmatched_ids):
        unmatched = blocks[blocks["block_geoid20"].isin(unmatched_ids)].to_crs(TARGET_CRS)
        precinct_area = precincts.to_crs(TARGET_CRS)
        intersections = gpd.overlay(
            unmatched[["block_geoid20", "geometry"]],
            precinct_area[["precinct_id", "geometry"]],
            how="intersection",
            keep_geom_type=False,
        )
        if not intersections.empty:
            intersections["overlap_area"] = intersections.geometry.area
            best = (
                intersections.sort_values(["block_geoid20", "overlap_area"], ascending=[True, False])
                .drop_duplicates("block_geoid20")
                .set_index("block_geoid20")["precinct_id"]
            )
            out.loc[out["precinct_id"].isna(), "precinct_id"] = out.loc[
                out["precinct_id"].isna(), "block_geoid20"
            ].map(best)
    out["block_geoid20"] = out["block_geoid20"].astype(str).str.zfill(15)
    out["countyfp20"] = out["countyfp20"].astype(str).str.zfill(3)
    return out.drop_duplicates("block_geoid20").sort_values("block_geoid20")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--vintage",
        choices=sorted(KNOWN),
        required=True,
        help="Known precinct/VTD vintage to assign 2020 blocks into.",
    )
    p.add_argument("--blocks-zip", type=Path, default=BLOCKS)
    p.add_argument("--precinct-shp", type=Path, default=None)
    p.add_argument("--out-csv", type=Path, default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    shp = Path(args.precinct_shp) if args.precinct_shp else KNOWN[args.vintage]
    if not shp.exists():
        raise FileNotFoundError(shp)
    out_csv = (
        Path(args.out_csv)
        if args.out_csv
        else ROOT / "data/crosswalks" / f"block20_to_{args.vintage}.csv"
    )

    blocks = gpd.read_file(f"zip://{Path(args.blocks_zip).as_posix()}")
    geoid = "GEOID20" if "GEOID20" in blocks.columns else "GEOID"
    county = "COUNTYFP20" if "COUNTYFP20" in blocks.columns else "COUNTYFP"
    blocks = blocks[[geoid, county, "geometry"]].rename(
        columns={geoid: "block_geoid20", county: "countyfp20"}
    )
    precincts = load_precinct_polygons(shp, args.vintage)
    out = assign_blocks(blocks, precincts)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)
    print(
        f"Wrote {len(out):,} -> {out_csv} ({args.vintage}); "
        f"precincts={out['precinct_id'].nunique():,}; "
        f"unmatched={int(out['precinct_id'].isna().sum()):,}"
    )


if __name__ == "__main__":
    main()
