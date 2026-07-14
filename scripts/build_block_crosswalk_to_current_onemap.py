"""Assign 2020 Census blocks directly to the current OneMap voting precincts (2025)."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd


ROOT = Path(__file__).resolve().parent.parent
BLOCKS = (
    ROOT
    / "NCPrecinctMap_reinit_2026-04-29/data/census/block files/tl_2020_37_tabblock20.zip"
)
# Prefer the 2025 OneMap precinct vintage used by the live atlas.
PRECINCTS = ROOT / "data/2025Voting_Precincts.geojson"
OUTPUT = ROOT / "data/crosswalks/block20_to_onemap_2025.csv"
TARGET_CRS = "EPSG:5070"


def _normalize_precinct_id(county: str, prec: str) -> str:
    c = " ".join(str(county or "").strip().upper().split())
    p = " ".join(str(prec or "").strip().upper().split())
    return f"{c} - {p}" if c and p else ""


def main() -> None:
    if not BLOCKS.exists():
        raise SystemExit(f"Missing blocks: {BLOCKS}")
    if not PRECINCTS.exists():
        raise SystemExit(f"Missing precincts: {PRECINCTS}")

    print(f"Loading blocks from {BLOCKS}")
    blocks = gpd.read_file(f"zip://{BLOCKS.as_posix()}")
    geoid = "GEOID20" if "GEOID20" in blocks.columns else "GEOID"
    countyfp = "COUNTYFP20" if "COUNTYFP20" in blocks.columns else "COUNTYFP"
    blocks = blocks[[geoid, countyfp, "geometry"]].rename(
        columns={geoid: "block_geoid20", countyfp: "countyfp20"}
    )
    blocks["block_geoid20"] = blocks["block_geoid20"].astype(str).str.zfill(15)
    blocks["countyfp20"] = blocks["countyfp20"].astype(str).str.zfill(3)

    print(f"Loading precincts from {PRECINCTS}")
    prec = gpd.read_file(PRECINCTS)
    prec = prec.copy()
    prec["precinct_id"] = [
        _normalize_precinct_id(c, p)
        for c, p in zip(prec["county_nam"], prec["prec_id"])
    ]
    prec = prec[prec["precinct_id"].str.len() > 3][["precinct_id", "geometry"]].copy()

    print("Point-in-polygon assign (representative_point)")
    pts = blocks.copy()
    pts["geometry"] = pts.geometry.representative_point()
    pts = pts.to_crs(prec.crs)
    joined = gpd.sjoin(
        pts[["block_geoid20", "countyfp20", "geometry"]],
        prec,
        how="left",
        predicate="within",
    )
    out = joined[["block_geoid20", "countyfp20", "precinct_id"]].copy()
    unmatched = out["precinct_id"].isna()
    print(f"unmatched after point-in-poly: {int(unmatched.sum()):,}")

    if unmatched.any():
        print("Max-area overlay fallback for unmatched")
        b_un = blocks.loc[out.index[unmatched]].to_crs(TARGET_CRS)
        p_a = prec.to_crs(TARGET_CRS)
        inter = gpd.overlay(
            b_un[["block_geoid20", "countyfp20", "geometry"]],
            p_a,
            how="intersection",
            keep_geom_type=False,
        )
        if not inter.empty:
            inter["a"] = inter.geometry.area
            top = (
                inter.sort_values(["block_geoid20", "a"], ascending=[True, False])
                .drop_duplicates("block_geoid20")
                .set_index("block_geoid20")["precinct_id"]
            )
            out.loc[out["precinct_id"].isna(), "precinct_id"] = out.loc[
                out["precinct_id"].isna(), "block_geoid20"
            ].map(top)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT, index=False)
    print(
        f"Wrote {OUTPUT}: rows={len(out):,}; "
        f"precincts={out['precinct_id'].nunique():,}; "
        f"unmatched={int(out['precinct_id'].isna().sum()):,}"
    )


if __name__ == "__main__":
    main()
