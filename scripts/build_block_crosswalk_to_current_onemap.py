"""Assign Census blocks directly to a modern OneMap voting precinct layer.

The default run consumes the December 2025 SBE censusblock package directly and
uses the December 2025 precinct target to normalize precinct IDs. Pass
--blocks/--precincts/--out-csv only when you want to spatially rebuild the
assignment from geometry instead of using the packaged block layer.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd


ROOT = Path(__file__).resolve().parent.parent
BLOCKS = (
    ROOT
    / "NCPrecinctMap_reinit_2026-04-29/data/census/block files/tl_2020_37_tabblock20.zip"
)
# Default to the December 2025 SBE target precinct geometry used by the live atlas chain.
PRECINCTS = ROOT / "data/census/SBE_PRECINCTS_20251212/SBE_PRECINCTS_20251212.shp"
ASSIGNED_BLOCKS = ROOT / "data/census/SBE_PRECINCTS_CENSUSBLOCKS_20251212.zip"
OUTPUT = ROOT / "data/crosswalks/block20_to_onemap_2025_12.csv"
COUNTIES = ROOT / "data/census/tl_2020_37_county20.geojson"
TARGET_CRS = "EPSG:5070"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assigned-blocks",
        type=Path,
        default=ASSIGNED_BLOCKS,
        help=(
            "December 2025 modern block assignment layer/zip with GEOID20, COUNTYFP20, county, and precinct columns. "
            "When set, --blocks and --precincts are not used."
        ),
    )
    parser.add_argument(
        "--target-precincts",
        type=Path,
        default=PRECINCTS,
        help=(
            "December 2025 target precinct layer used to validate/fix assigned-block precinct IDs "
            "when --assigned-blocks is set."
        ),
    )
    parser.add_argument(
        "--blocks",
        type=Path,
        default=BLOCKS,
        help="Census block geometry path. Zipped TIGER shapefiles are supported.",
    )
    parser.add_argument(
        "--precincts",
        type=Path,
        default=PRECINCTS,
        help="December 2025 OneMap voting precinct geometry used as the display target.",
    )
    parser.add_argument("--out-csv", type=Path, default=OUTPUT)
    parser.add_argument("--county-reference", type=Path, default=COUNTIES)
    parser.add_argument("--target-crs", default=TARGET_CRS)
    parser.add_argument(
        "--county-col",
        default="county_nam",
        help="County-name column in the modern precinct layer.",
    )
    parser.add_argument(
        "--precinct-col",
        default="prec_id",
        help="Precinct-code column in the modern precinct layer.",
    )
    return parser.parse_args()


def _clean_token(value: object) -> str:
    text = " ".join(str(value or "").strip().upper().split())
    return "" if text in {"", "NAN", "NONE", "NULL"} else text


def _compact_token(value: object) -> str:
    return "".join(ch for ch in _clean_token(value) if ch.isalnum())


def _normalize_precinct_id(county: object, prec: object) -> str:
    c = _clean_token(county)
    p = _clean_token(prec)
    return f"{c} - {p}" if c and p else ""


def _read_vector(path: Path) -> gpd.GeoDataFrame:
    path = Path(path)
    if path.suffix.lower() == ".zip":
        return gpd.read_file(f"zip://{path.as_posix()}")
    return gpd.read_file(path)


def _pick_column(frame: gpd.GeoDataFrame, candidates: list[str], label: str) -> str:
    cols = {str(c).lower(): str(c) for c in frame.columns}
    for candidate in candidates:
        hit = cols.get(candidate.lower())
        if hit:
            return hit
    raise SystemExit(
        f"Assigned-block layer must contain {label}; available columns: {', '.join(map(str, frame.columns))}"
    )


def _load_countyfp_names(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    counties = _read_vector(path)
    countyfp_col = _pick_column(counties, ["COUNTYFP20", "COUNTYFP"], "COUNTYFP20 or COUNTYFP")
    name_col = _pick_column(counties, ["NAME20", "NAME"], "county name")
    out: dict[str, str] = {}
    for row in counties[[countyfp_col, name_col]].itertuples(index=False):
        countyfp = str(row[0]).strip().zfill(3)
        name = _clean_token(row[1])
        if countyfp and name:
            out[countyfp] = name
    return out


def _load_target_precinct_lookup(
    path: Path,
    county_col: str,
    precinct_col: str,
) -> tuple[set[str], dict[str, dict[str, str]]]:
    if not path.exists():
        return set(), {}
    target = _read_vector(path)
    if county_col not in target.columns or precinct_col not in target.columns:
        raise SystemExit(
            f"Target precinct layer must contain {county_col!r} and {precinct_col!r}; "
            f"available columns: {', '.join(map(str, target.columns))}"
        )

    keys: set[str] = set()
    compact_by_county: dict[str, dict[str, str]] = {}
    for county, precinct in target[[county_col, precinct_col]].itertuples(index=False):
        county_name = _clean_token(county)
        precinct_code = _clean_token(precinct)
        key = _normalize_precinct_id(county_name, precinct_code)
        if not key:
            continue
        keys.add(key)
        compact = _compact_token(precinct_code)
        if compact:
            compact_by_county.setdefault(county_name, {}).setdefault(compact, precinct_code)
    return keys, compact_by_county


def _write_assigned_block_map(args: argparse.Namespace) -> None:
    assigned_path = Path(args.assigned_blocks)
    output_path = Path(args.out_csv)
    if not assigned_path.exists():
        raise SystemExit(f"Missing assigned blocks: {assigned_path}")

    print(f"Loading assigned blocks from {assigned_path}")
    assigned = _read_vector(assigned_path)
    geoid_col = _pick_column(assigned, ["GEOID20", "GEOID"], "GEOID20 or GEOID")
    countyfp_col = _pick_column(assigned, ["COUNTYFP20", "COUNTYFP"], "COUNTYFP20 or COUNTYFP")
    county_col = str(args.county_col)
    precinct_col = str(args.precinct_col)
    if county_col not in assigned.columns or precinct_col not in assigned.columns:
        raise SystemExit(
            f"Assigned-block layer must contain {county_col!r} and {precinct_col!r}; "
            f"available columns: {', '.join(map(str, assigned.columns))}"
        )

    countyfp_names = _load_countyfp_names(Path(args.county_reference))
    target_keys, target_compact = _load_target_precinct_lookup(
        Path(args.target_precincts),
        county_col,
        precinct_col,
    )

    out = assigned[[geoid_col, countyfp_col, county_col, precinct_col]].copy()
    out.columns = ["block_geoid20", "countyfp20", "county", "precinct"]
    out["block_geoid20"] = out["block_geoid20"].astype(str).str.strip().str.zfill(15)
    out["countyfp20"] = out["countyfp20"].astype(str).str.strip().str.zfill(3)
    county_values = []
    for county, countyfp in zip(out["county"], out["countyfp20"]):
        cleaned = _clean_token(county)
        if not cleaned or cleaned.isdigit():
            cleaned = countyfp_names.get(str(countyfp).zfill(3), cleaned)
        county_values.append(cleaned)
    out["county"] = county_values
    out["precinct_id"] = [_normalize_precinct_id(c, p) for c, p in zip(out["county"], out["precinct"])]

    if target_keys:
        fixed_ids = []
        for county, precinct_id in zip(out["county"], out["precinct_id"]):
            key = _clean_token(precinct_id)
            if key in target_keys:
                fixed_ids.append(key)
                continue
            if " - " not in key:
                fixed_ids.append("")
                continue
            county_name, precinct_code = key.split(" - ", 1)
            target_code = target_compact.get(county_name, {}).get(_compact_token(precinct_code))
            fixed_ids.append(_normalize_precinct_id(county_name, target_code) if target_code else "")
        out["precinct_id"] = fixed_ids

    out = out[["block_geoid20", "countyfp20", "precinct_id"]].copy()
    out = out[out["precinct_id"].astype(str).str.len() > 3].copy()
    duplicates = int(out["block_geoid20"].duplicated().sum())
    if duplicates:
        print(f"warning: {duplicates:,} duplicate block rows; keeping first assignment per block")
        out = out.drop_duplicates("block_geoid20", keep="first").copy()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)
    print(
        f"Wrote {output_path}: rows={len(out):,}; "
        f"precincts={out['precinct_id'].nunique():,}; "
        f"unmatched={int((out['precinct_id'].astype(str).str.len() <= 3).sum()):,}"
    )


def main() -> None:
    args = parse_args()
    if args.assigned_blocks is not None:
        _write_assigned_block_map(args)
        return

    blocks_path = Path(args.blocks)
    precincts_path = Path(args.precincts)
    output_path = Path(args.out_csv)

    if not blocks_path.exists():
        raise SystemExit(f"Missing blocks: {blocks_path}")
    if not precincts_path.exists():
        raise SystemExit(f"Missing precincts: {precincts_path}")

    print(f"Loading blocks from {blocks_path}")
    blocks = _read_vector(blocks_path)
    geoid = "GEOID20" if "GEOID20" in blocks.columns else "GEOID"
    countyfp = "COUNTYFP20" if "COUNTYFP20" in blocks.columns else "COUNTYFP"
    if geoid not in blocks.columns:
        raise SystemExit("Block geometry must contain GEOID20 or GEOID.")
    if countyfp not in blocks.columns:
        raise SystemExit("Block geometry must contain COUNTYFP20 or COUNTYFP.")
    blocks = blocks[[geoid, countyfp, "geometry"]].rename(
        columns={geoid: "block_geoid20", countyfp: "countyfp20"}
    )
    blocks["block_geoid20"] = blocks["block_geoid20"].astype(str).str.zfill(15)
    blocks["countyfp20"] = blocks["countyfp20"].astype(str).str.zfill(3)

    print(f"Loading precincts from {precincts_path}")
    prec = _read_vector(precincts_path)
    county_col = str(args.county_col)
    precinct_col = str(args.precinct_col)
    if county_col not in prec.columns or precinct_col not in prec.columns:
        raise SystemExit(
            f"Precinct layer must contain {county_col!r} and {precinct_col!r}; "
            f"available columns: {', '.join(map(str, prec.columns))}"
        )
    prec = prec.copy()
    prec["precinct_id"] = [
        _normalize_precinct_id(c, p)
        for c, p in zip(prec[county_col], prec[precinct_col])
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
        b_un = blocks.loc[out.index[unmatched]].to_crs(args.target_crs)
        p_a = prec.to_crs(args.target_crs)
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)
    print(
        f"Wrote {output_path}: rows={len(out):,}; "
        f"precincts={out['precinct_id'].nunique():,}; "
        f"unmatched={int(out['precinct_id'].isna().sum()):,}"
    )


if __name__ == "__main__":
    main()
