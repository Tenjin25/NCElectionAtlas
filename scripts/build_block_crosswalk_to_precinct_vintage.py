"""Assign 2020 Census blocks to an SBE / VTD precinct polygon vintage.

Outputs a block20->precinct_id CSV suitable as --match-crosswalk-csv for
historical election years, using COUNTY - PREC_ID keys when available.

For 2010s SBE vintages, --via-block10 is usually preferred: assign 2010
blocks to the precinct polygons, then map 2020 block representative points
into those 2010 blocks. That better matches SBE precincts maintained against
2010-era geography.

For 2000-era layers such as Precincts2006Gen, --via-block00-nhgis is usually
preferred: assign 2000 tabblocks to the precinct polygons, then use NHGIS
2000->2010 and 2010->2020 block crosswalks to choose the dominant 2006
precinct for each 2020 block.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
REINIT = ROOT / "NCPrecinctMap_reinit_2026-04-29"
BLOCKS = REINIT / "data/census/block files/tl_2020_37_tabblock20.zip"
BLOCKS10 = REINIT / "data/census/block files/tl_2020_37_tabblock10.zip"
BLOCKS00 = ROOT / "data/tl_2008_37_tabblock00.zip"
NHGIS_BLOCK00_TO_10 = ROOT / "data/census/nhgis_blk2000_blk2010_37/nhgis_blk2000_blk2010_37.csv"
NHGIS_BLOCK10_TO_20 = ROOT / "data/census/nhgis_blk2010_blk2020_37/nhgis_blk2010_blk2020_37.csv"
COUNTY_GEOJSON = ROOT / "data/census/tl_2020_37_county20.geojson"
TARGET_CRS = "EPSG:5070"

KNOWN = {
    "sbe_2006": ROOT / "data/Precincts2006Gen/Precincts2006Gen.shp",
    "sbe_2012": REINIT / "data/census/SBE_PRECINCTS_20120901/SBE_PRECINCTS_09012012.shp",
    "sbe_2013": ROOT / "data/census/SBE_PRECINCTS_20131004/PRECINCTS_20131004.shp",
    "sbe_2014": REINIT / "data/census/SBE_PRECINCTS_20141016/PRECINCTS.shp",
    "sbe_2015": ROOT / "data/census/SBE_PRECINCTS_20150918/PRECINCTS_20150918.shp",
    "sbe_2016": REINIT / "data/census/SBE_PRECINCTS_20161004/Precincts.shp",
    "sbe_2017": ROOT / "data/SBE_PRECINCTS_20170519/Precincts2.shp",
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
    if mode == "sbe_2006":
        # The 2008 OpenElections exports are name-heavy; SEIMS_Code is useful
        # metadata, but using names gives the match map the right key space.
        prec_col = _pick_col(list(gdf.columns), "Precinct", "PRECINCT", "precinct_id")
    else:
        prec_col = _pick_col(
            list(gdf.columns),
            "prec_id",
            "PREC_ID",
            "SEIMS_Code",
            "precinct_id",
            "PRECINCT",
        )
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


def assign_blocks_via_block10(
    blocks20: gpd.GeoDataFrame,
    blocks10: gpd.GeoDataFrame,
    precincts: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Assign 2020 blocks to precincts through 2010 blocks."""
    b10_for_precinct = blocks10.rename(
        columns={"block_geoid10": "block_geoid20", "countyfp10": "countyfp20"}
    )
    block10_to_precinct = assign_blocks(b10_for_precinct, precincts).rename(
        columns={"block_geoid20": "block_geoid10", "countyfp20": "countyfp10"}
    )

    points20 = blocks20.copy()
    points20["geometry"] = points20.geometry.representative_point()
    points20 = points20.to_crs(blocks10.crs)
    joined = gpd.sjoin(
        points20[["block_geoid20", "countyfp20", "geometry"]],
        blocks10[["block_geoid10", "geometry"]],
        how="left",
        predicate="within",
    )
    block20_to_block10 = joined[["block_geoid20", "countyfp20", "block_geoid10"]].copy()

    unmatched_ids = block20_to_block10.loc[block20_to_block10["block_geoid10"].isna(), "block_geoid20"]
    if len(unmatched_ids):
        unmatched = blocks20[blocks20["block_geoid20"].isin(unmatched_ids)].to_crs(TARGET_CRS)
        b10_area = blocks10.to_crs(TARGET_CRS)
        intersections = gpd.overlay(
            unmatched[["block_geoid20", "geometry"]],
            b10_area[["block_geoid10", "geometry"]],
            how="intersection",
            keep_geom_type=False,
        )
        if not intersections.empty:
            intersections["overlap_area"] = intersections.geometry.area
            best = (
                intersections.sort_values(["block_geoid20", "overlap_area"], ascending=[True, False])
                .drop_duplicates("block_geoid20")
                .set_index("block_geoid20")["block_geoid10"]
            )
            block20_to_block10.loc[block20_to_block10["block_geoid10"].isna(), "block_geoid10"] = (
                block20_to_block10.loc[block20_to_block10["block_geoid10"].isna(), "block_geoid20"].map(best)
            )

    out = block20_to_block10.merge(
        block10_to_precinct[["block_geoid10", "precinct_id"]],
        on="block_geoid10",
        how="left",
    )[["block_geoid20", "countyfp20", "precinct_id"]]
    out["block_geoid20"] = out["block_geoid20"].astype(str).str.zfill(15)
    out["countyfp20"] = out["countyfp20"].astype(str).str.zfill(3)
    return out.drop_duplicates("block_geoid20").sort_values("block_geoid20")


def load_nhgis_bridge_2000_to_2020(
    blk2000_2010_csv: Path,
    blk2010_2020_csv: Path,
) -> pd.DataFrame:
    """Chain NHGIS block crosswalks into normalized blk2000ge -> blk2020ge weights."""
    if not blk2000_2010_csv.exists():
        raise FileNotFoundError(blk2000_2010_csv)
    if not blk2010_2020_csv.exists():
        raise FileNotFoundError(blk2010_2020_csv)

    a = pd.read_csv(blk2000_2010_csv, dtype=str, usecols=["blk2000ge", "blk2010ge", "weight"]).fillna("")
    b = pd.read_csv(blk2010_2020_csv, dtype=str, usecols=["blk2010ge", "blk2020ge", "weight"]).fillna("")

    a["blk2000ge"] = a["blk2000ge"].astype(str).str.strip().str.zfill(15)
    a["blk2010ge"] = a["blk2010ge"].astype(str).str.strip().str.zfill(15)
    b["blk2010ge"] = b["blk2010ge"].astype(str).str.strip().str.zfill(15)
    b["blk2020ge"] = b["blk2020ge"].astype(str).str.strip().str.zfill(15)

    a["w1"] = pd.to_numeric(a["weight"], errors="coerce").fillna(0.0)
    b["w2"] = pd.to_numeric(b["weight"], errors="coerce").fillna(0.0)

    a = a[a["blk2010ge"].str.startswith("37") & (a["w1"] > 0)].copy()
    b = b[b["blk2010ge"].str.startswith("37") & b["blk2020ge"].str.startswith("37") & (b["w2"] > 0)].copy()
    if a.empty or b.empty:
        return pd.DataFrame(columns=["blk2000ge", "blk2020ge", "weight"])

    m = a[["blk2000ge", "blk2010ge", "w1"]].merge(
        b[["blk2010ge", "blk2020ge", "w2"]],
        on="blk2010ge",
        how="inner",
    )
    if m.empty:
        return pd.DataFrame(columns=["blk2000ge", "blk2020ge", "weight"])

    m["weight"] = pd.to_numeric(m["w1"], errors="coerce").fillna(0.0) * pd.to_numeric(
        m["w2"], errors="coerce"
    ).fillna(0.0)
    m = m[m["weight"] > 0].copy()
    if m.empty:
        return pd.DataFrame(columns=["blk2000ge", "blk2020ge", "weight"])

    g = m.groupby(["blk2000ge", "blk2020ge"], as_index=False)["weight"].sum()
    den = g.groupby("blk2000ge", as_index=False)["weight"].sum().rename(columns={"weight": "wden"})
    g = g.merge(den, on="blk2000ge", how="left")
    g["weight"] = g["weight"] / g["wden"].replace(0, pd.NA)
    g["weight"] = pd.to_numeric(g["weight"], errors="coerce").fillna(0.0)
    return g[g["weight"] > 0][["blk2000ge", "blk2020ge", "weight"]].copy()


def assign_blocks_via_block00_nhgis(
    blocks20: gpd.GeoDataFrame,
    blocks00: gpd.GeoDataFrame,
    precincts: gpd.GeoDataFrame,
    blk2000_2010_csv: Path,
    blk2010_2020_csv: Path,
) -> pd.DataFrame:
    """Assign 2020 blocks to a 2000-era precinct layer through tabblock00 + NHGIS."""
    b00_for_precinct = blocks00.rename(
        columns={"block_geoid00": "block_geoid20", "countyfp00": "countyfp20"}
    )
    block00_to_precinct = assign_blocks(b00_for_precinct, precincts).rename(
        columns={"block_geoid20": "blk2000ge"}
    )
    bridge = load_nhgis_bridge_2000_to_2020(blk2000_2010_csv, blk2010_2020_csv)
    if bridge.empty:
        raise ValueError("NHGIS 2000->2020 bridge is empty after filtering.")

    weighted = bridge.merge(
        block00_to_precinct[["blk2000ge", "precinct_id"]],
        on="blk2000ge",
        how="inner",
    )
    weighted = weighted[weighted["precinct_id"].notna()].copy()
    if weighted.empty:
        raise ValueError("No NHGIS-bridged 2000 blocks matched the precinct layer.")

    best = (
        weighted.groupby(["blk2020ge", "precinct_id"], as_index=False)["weight"].sum()
        .sort_values(["blk2020ge", "weight"], ascending=[True, False])
        .drop_duplicates("blk2020ge")
        .rename(columns={"blk2020ge": "block_geoid20"})
    )
    out = blocks20[["block_geoid20", "countyfp20"]].copy()
    out["block_geoid20"] = out["block_geoid20"].astype(str).str.zfill(15)
    out["countyfp20"] = out["countyfp20"].astype(str).str.zfill(3)
    out = out.merge(best[["block_geoid20", "precinct_id"]], on="block_geoid20", how="left")
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
    p.add_argument("--blocks10-zip", type=Path, default=BLOCKS10)
    p.add_argument(
        "--blocks00",
        type=Path,
        default=BLOCKS00,
        help="2000 tabblock shapefile/zip path used with --via-block00-nhgis.",
    )
    p.add_argument("--nhgis-blk2000-blk2010-csv", type=Path, default=NHGIS_BLOCK00_TO_10)
    p.add_argument("--nhgis-blk2010-blk2020-csv", type=Path, default=NHGIS_BLOCK10_TO_20)
    p.add_argument("--precinct-shp", type=Path, default=None)
    p.add_argument("--out-csv", type=Path, default=None)
    p.add_argument(
        "--via-block10",
        action="store_true",
        help="Assign 2020 blocks through 2010 blocks before precinct matching.",
    )
    p.add_argument(
        "--via-block00-nhgis",
        action="store_true",
        help="Assign through 2000 tabblocks, then bridge to 2020 blocks with NHGIS crosswalks.",
    )
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
    if args.via_block10 and args.via_block00_nhgis:
        raise ValueError("Choose only one of --via-block10 or --via-block00-nhgis.")
    if args.via_block00_nhgis:
        if args.blocks00 is None:
            raise ValueError("--blocks00 is required with --via-block00-nhgis.")
        blocks00_path = Path(args.blocks00)
        if not blocks00_path.exists():
            raise FileNotFoundError(blocks00_path)
        blocks00 = gpd.read_file(
            f"zip://{blocks00_path.as_posix()}" if blocks00_path.suffix.lower() == ".zip" else blocks00_path
        )
        geoid00 = _pick_col(list(blocks00.columns), "GEOID00", "GEOID", "BLOCKID", "BLKIDFP00", "BLKIDFP")
        county00 = _pick_col(list(blocks00.columns), "COUNTYFP00", "COUNTYFP", "COUNTY")
        if not geoid00 or not county00:
            raise ValueError(f"Cannot find 2000 block GEOID/county columns in {blocks00_path}: {list(blocks00.columns)}")
        blocks00 = blocks00[[geoid00, county00, "geometry"]].rename(
            columns={geoid00: "block_geoid00", county00: "countyfp00"}
        )
        # 2000 TIGER tabblocks may carry suffix pieces (e.g. ...2043D), while
        # NHGIS crosswalk IDs use the 15-digit base Census block GEOID.
        blocks00["block_geoid00"] = blocks00["block_geoid00"].astype(str).str.extract(r"(\d{15})", expand=False)
        blocks00["countyfp00"] = blocks00["countyfp00"].astype(str).str.zfill(3)
        blocks00 = blocks00[blocks00["block_geoid00"].notna()].copy()
        if blocks00["block_geoid00"].duplicated().any():
            blocks00 = blocks00.dissolve(by=["block_geoid00", "countyfp00"], as_index=False)
        out = assign_blocks_via_block00_nhgis(
            blocks,
            blocks00,
            precincts,
            Path(args.nhgis_blk2000_blk2010_csv),
            Path(args.nhgis_blk2010_blk2020_csv),
        )
    elif args.via_block10:
        blocks10 = gpd.read_file(f"zip://{Path(args.blocks10_zip).as_posix()}")
        geoid10 = "GEOID10" if "GEOID10" in blocks10.columns else "GEOID"
        county10 = "COUNTYFP10" if "COUNTYFP10" in blocks10.columns else "COUNTYFP"
        blocks10 = blocks10[[geoid10, county10, "geometry"]].rename(
            columns={geoid10: "block_geoid10", county10: "countyfp10"}
        )
        out = assign_blocks_via_block10(blocks, blocks10, precincts)
    else:
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
