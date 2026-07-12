from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
override_vendor = os.environ.get("NCEA_GEOPANDAS_VENDOR", "").strip()
vendor_candidates = [Path(override_vendor)] if override_vendor else [ROOT / ".python-vendor" / "geopandas", ROOT / ".vendor" / "geopandas"]
for vendor_dir in vendor_candidates:
    if vendor_dir.exists():
        sys.path.insert(0, str(vendor_dir))

import geopandas as gpd
import pandas as pd


TARGET_CRS = "EPSG:5070"
COUNTY_GEOJSON = Path("data/census/tl_2020_37_county20.geojson")
MIN_COUNTY_OVERLAP_PCT = 0.5


def calculate_competitiveness(margin_pct: float) -> str:
    abs_margin = abs(float(margin_pct))
    if abs_margin < 0.5:
        return "#f7f7f7"
    rep_win = float(margin_pct) > 0
    if abs_margin >= 40:
        return "#67000d" if rep_win else "#08306b"
    if abs_margin >= 30:
        return "#a50f15" if rep_win else "#08519c"
    if abs_margin >= 20:
        return "#cb181d" if rep_win else "#3182bd"
    if abs_margin >= 10:
        return "#ef3b2c" if rep_win else "#6baed6"
    if abs_margin >= 5.5:
        return "#fb6a4a" if rep_win else "#9ecae1"
    if abs_margin >= 1:
        return "#fcae91" if rep_win else "#c6dbef"
    return "#fee8c8" if rep_win else "#e1f5fe"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build a precinct->CD2026 crosswalk from SL 2025-95 and patch CD slices (e.g., CD-01 and CD-03)."
    )
    p.add_argument("--precinct-geojson", type=Path, default=Path("data/Voting_Precincts.geojson"))
    p.add_argument("--cd-shapefile", type=Path, default=Path("data/sl2025_95_shapefile/SL 2025-95.shp"))
    p.add_argument("--district-col", default="District")
    p.add_argument("--aggregated", type=Path, default=Path("data/nc_elections_aggregated.json"))
    p.add_argument("--in-dir", type=Path, default=Path("data/district_contests_2024_lines"))
    p.add_argument("--out-dir", type=Path, default=Path("data/district_contests_2026_lines"))
    p.add_argument("--out-crosswalk", type=Path, default=Path("data/crosswalks/precinct_to_cd2026_sl2025_95.csv"))
    p.add_argument("--target-districts", default="1,3")
    return p.parse_args()


def build_precinct_crosswalk(precinct_geojson: Path, cd_shp: Path, district_col: str) -> pd.DataFrame:
    p = gpd.read_file(precinct_geojson)
    need_p = {"county_nam", "prec_id", "geometry"}
    if not need_p.issubset(set(p.columns)):
        raise ValueError(f"Precinct file missing columns: {sorted(need_p - set(p.columns))}")
    p = p[list(need_p)].copy()
    p["county_nam"] = p["county_nam"].astype(str).str.strip().str.upper()
    p["prec_id"] = p["prec_id"].astype(str).str.strip().str.upper()
    p["precinct_key"] = p["county_nam"] + " - " + p["prec_id"]
    p = p[p["prec_id"] != ""].copy().to_crs(TARGET_CRS)
    p["prec_area"] = p.geometry.area

    d = gpd.read_file(cd_shp)
    district_lookup = {str(col).strip().lower(): col for col in d.columns}
    district_col_resolved = district_lookup.get(str(district_col).strip().lower())
    if district_col_resolved is None:
        for fallback in ("district", "dist", "districts"):
            if fallback in district_lookup:
                district_col_resolved = district_lookup[fallback]
                break
    if district_col_resolved is None:
        raise ValueError(f"District shapefile missing column: {district_col}")
    d = d[[district_col_resolved, "geometry"]].copy()
    d["district"] = d[district_col_resolved].astype(str).str.strip()
    d = d[["district", "geometry"]].to_crs(TARGET_CRS)

    inter = gpd.overlay(
        p[["precinct_key", "prec_area", "geometry"]],
        d[["district", "geometry"]],
        how="intersection",
        keep_geom_type=False,
    )
    inter["overlap_area"] = inter.geometry.area
    inter = inter[inter["overlap_area"] > 0].copy()
    inter["area_weight"] = inter["overlap_area"] / inter["prec_area"]
    inter = inter[["precinct_key", "district", "prec_area", "area_weight"]].copy()

    s = inter.groupby("precinct_key", as_index=False)["area_weight"].sum().rename(columns={"area_weight": "sum_w"})
    inter = inter.merge(s, on="precinct_key", how="left")
    inter["area_weight"] = inter["area_weight"] / inter["sum_w"]
    inter = inter.drop(columns=["sum_w"])
    inter["district"] = inter["district"].astype(str).str.replace(r"\.0$", "", regex=True)
    inter["district"] = inter["district"].str.lstrip("0")
    inter.loc[inter["district"] == "", "district"] = "0"
    return inter.sort_values(["precinct_key", "district"]).reset_index(drop=True)


def load_aggregated(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_cd_file_meta(name: str) -> tuple[str, int] | None:
    m = re.match(r"^congressional_(.+)_(\d{4})\.json$", name)
    if not m:
        return None
    return m.group(1), int(m.group(2))


def build_vote_maps(results_node: dict) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for key, row in (results_node or {}).items():
        precinct_key = str(key).strip().upper()
        out[precinct_key] = {
            "dem_votes": int(row.get("dem_votes", 0) or 0),
            "rep_votes": int(row.get("rep_votes", 0) or 0),
            "other_votes": int(row.get("other_votes", 0) or 0),
        }
    return out


def canonicalize_precinct_key(precinct_key: str) -> str:
    key = str(precinct_key or "").strip().upper()
    key = re.sub(r"\s+", " ", key)
    m = re.match(r"^(.*? - [A-Z0-9]+)_.+$", key)
    if m:
        return m.group(1)
    m = re.match(r"^(.*? - [A-Z0-9.\-]+)\s+.+$", key)
    if m:
        return m.group(1)
    return key


def is_non_geographic_precinct_key(precinct_key: str) -> bool:
    key = str(precinct_key or "").strip().upper()
    if " - " in key:
        key = key.split(" - ", 1)[1].strip()
    if not key:
        return True
    if key in {"EV", "PROVISIONAL", "TRANSFER"}:
        return True
    if key.startswith("ABSEN") or key.startswith("ABSENTEE"):
        return True
    if key.startswith("ONE STOP") or key.startswith("ONESTOP"):
        return True
    if key.startswith("PROVI") or key.startswith("TRANS"):
        return True
    if "ABSENTEE" in key or "PROVISIONAL" in key or "ONE STOP" in key or "TRANSFER" in key:
        return True
    return False


def build_target_county_map(
    county_geojson: Path,
    cd_shp: Path,
    district_col: str,
    target_districts: set[str],
    min_overlap_pct: float = MIN_COUNTY_OVERLAP_PCT,
) -> dict[str, set[str]]:
    counties = gpd.read_file(county_geojson)
    county_name_col = "NAME20" if "NAME20" in counties.columns else "NAME"
    counties = counties[[county_name_col, "geometry"]].copy().to_crs(TARGET_CRS)
    counties["county"] = counties[county_name_col].astype(str).str.strip().str.upper()
    counties["county_area"] = counties.geometry.area

    districts = gpd.read_file(cd_shp)
    district_lookup = {str(col).strip().lower(): col for col in districts.columns}
    district_col_resolved = district_lookup.get(str(district_col).strip().lower())
    if district_col_resolved is None:
        for fallback in ("district", "dist", "districts"):
            if fallback in district_lookup:
                district_col_resolved = district_lookup[fallback]
                break
    if district_col_resolved is None:
        raise ValueError(f"District shapefile missing column: {district_col}")
    districts = districts[[district_col_resolved, "geometry"]].copy().to_crs(TARGET_CRS)
    districts["district"] = (
        districts[district_col_resolved].astype(str).str.strip().str.replace(r"\.0$", "", regex=True).str.lstrip("0")
    )
    districts.loc[districts["district"] == "", "district"] = "0"
    districts = districts[districts["district"].isin(target_districts)].copy()

    inter = gpd.overlay(
        counties[["county", "county_area", "geometry"]],
        districts[["district", "geometry"]],
        how="intersection",
        keep_geom_type=False,
    )
    inter["overlap_area"] = inter.geometry.area
    inter = inter[inter["overlap_area"] > 0].copy()
    inter["pct_of_county"] = inter["overlap_area"] / inter["county_area"] * 100.0
    inter = inter[inter["pct_of_county"] >= float(min_overlap_pct)].copy()

    target_counties: dict[str, set[str]] = defaultdict(set)
    for _, row in inter.iterrows():
        target_counties[str(row["district"]).strip()].add(str(row["county"]).strip().upper())
    return dict(target_counties)


def weighted_aggregate(
    vote_map: dict[str, dict[str, int]],
    crosswalk: pd.DataFrame,
    target_counties: dict[str, set[str]] | None = None,
) -> tuple[dict[str, dict[str, int]], int, int, int]:
    by_precinct: dict[str, list[tuple[str, float]]] = defaultdict(list)
    county_fallback_weights: dict[str, list[tuple[str, float]]] = defaultdict(list)
    county_district_area: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for _, r in crosswalk.iterrows():
        raw_key = str(r["precinct_key"]).strip().upper()
        by_precinct[raw_key].append((str(r["district"]).strip(), float(r["area_weight"])))
        county = raw_key.split(" - ", 1)[0].strip().upper() if " - " in raw_key else ""
        if county:
            county_district_area[county][str(r["district"]).strip()] += float(r["prec_area"]) * float(r["area_weight"])

    for county, district_area in county_district_area.items():
        total_area = sum(district_area.values())
        if total_area <= 0:
            continue
        county_fallback_weights[county] = [
            (district, area / total_area)
            for district, area in sorted(district_area.items())
            if area > 0
        ]

    out: dict[str, dict[str, float]] = defaultdict(lambda: {"dem_votes": 0.0, "rep_votes": 0.0, "other_votes": 0.0})
    matched = 0
    county_fallback_used = 0
    total = 0
    for pk, votes in vote_map.items():
        county = pk.split(" - ", 1)[0].strip().upper() if " - " in pk else ""
        total += 1
        alloc = by_precinct.get(pk)
        if not alloc:
            alloc = by_precinct.get(canonicalize_precinct_key(pk))
        if not alloc and county:
            alloc = county_fallback_weights.get(county)
        if not alloc:
            continue
        filtered_alloc: list[tuple[str, float]] = []
        for district, w in alloc:
            allowed_counties = (target_counties or {}).get(str(district).strip())
            if allowed_counties is not None and county not in allowed_counties:
                continue
            filtered_alloc.append((district, w))
        if not filtered_alloc:
            continue
        matched += 1
        if pk not in by_precinct and canonicalize_precinct_key(pk) not in by_precinct:
            county_fallback_used += 1
        weight_sum = sum(w for _, w in filtered_alloc)
        if weight_sum <= 0:
            continue
        for district, w in filtered_alloc:
            w_norm = w / weight_sum
            out[district]["dem_votes"] += votes["dem_votes"] * w_norm
            out[district]["rep_votes"] += votes["rep_votes"] * w_norm
            out[district]["other_votes"] += votes["other_votes"] * w_norm

    rounded: dict[str, dict[str, int]] = {}
    for d, vals in out.items():
        rounded[d] = {
            "dem_votes": int(round(vals["dem_votes"])),
            "rep_votes": int(round(vals["rep_votes"])),
            "other_votes": int(round(vals["other_votes"])),
        }
    return rounded, matched, total, county_fallback_used


def patch_district_row(template_row: dict, new_votes: dict[str, int]) -> dict:
    dem = int(new_votes.get("dem_votes", 0))
    rep = int(new_votes.get("rep_votes", 0))
    other = int(new_votes.get("other_votes", 0))
    total = dem + rep + other
    margin = rep - dem
    margin_pct = (margin / total * 100.0) if total else 0.0
    row = dict(template_row or {})
    row.update(
        {
            "dem_votes": dem,
            "rep_votes": rep,
            "other_votes": other,
            "total_votes": total,
            "margin": margin,
            "margin_pct": round(margin_pct, 2),
            "winner": "REP" if margin > 0 else ("DEM" if margin < 0 else "TIE"),
            "competitiveness": {"color": calculate_competitiveness(margin_pct)},
        }
    )
    return row


def is_uncontested_partisan_contest(agg_votes: dict[str, dict[str, int]]) -> bool:
    dem_total = 0
    rep_total = 0
    other_total = 0
    for row in agg_votes.values():
        dem_total += int(row.get("dem_votes", 0) or 0)
        rep_total += int(row.get("rep_votes", 0) or 0)
        other_total += int(row.get("other_votes", 0) or 0)
    return (dem_total == 0 or rep_total == 0) and other_total == 0


def main() -> None:
    args = parse_args()
    target_districts = {d.strip().lstrip("0") or "0" for d in str(args.target_districts).split(",") if d.strip()}

    crosswalk = build_precinct_crosswalk(args.precinct_geojson, args.cd_shapefile, args.district_col)
    target_counties = build_target_county_map(COUNTY_GEOJSON, args.cd_shapefile, args.district_col, target_districts)
    args.out_crosswalk.parent.mkdir(parents=True, exist_ok=True)
    crosswalk.to_csv(args.out_crosswalk, index=False)
    print(f"Wrote crosswalk: {args.out_crosswalk} ({len(crosswalk):,} rows)")

    agg = load_aggregated(args.aggregated)
    results_by_year = agg.get("results_by_year", {})

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(args.in_dir.glob("congressional_*.json")):
        dst = args.out_dir / src.name
        payload_path = dst if dst.exists() else src
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        meta = extract_cd_file_meta(src.name)
        if not meta:
            continue
        contest_type, year = meta
        year_node = results_by_year.get(str(year), {})
        contest_node = (((year_node.get(contest_type) or {}).get("general")) or {}).get("results")
        if not isinstance(contest_node, dict):
            print(f"Skipped {src.name}: no precinct aggregate for {contest_type} {year}")
            continue

        vote_map = build_vote_maps(contest_node)
        agg_votes, matched, total, county_fallback_used = weighted_aggregate(
            vote_map, crosswalk, target_counties=target_counties
        )
        if agg_votes and is_uncontested_partisan_contest(agg_votes):
            if dst.exists():
                dst.unlink()
            print(f"Skipped {src.name}: uncontested partisan contest")
            continue

        results = (((payload.get("general") or {}).get("results")) or {})
        for district in target_districts:
            if district not in results:
                continue
            if district not in agg_votes:
                continue
            results[district] = patch_district_row(results[district], agg_votes[district])
        payload.setdefault("meta", {})
        payload["meta"]["source"] = "sl2025_95_precinct_area_weighted"
        payload["meta"]["match_coverage_pct"] = round((matched / total * 100.0), 2) if total else 0.0
        payload["meta"]["matched_precinct_keys"] = int(matched)
        payload["meta"]["total_precinct_keys"] = int(total)
        payload["meta"]["county_fallback_precinct_keys"] = int(county_fallback_used)

        dst.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {dst.name}: patched districts {sorted(target_districts)}")

    # Rebuild manifest in the new output directory.
    manifest_rows: list[dict] = []
    for p in sorted(args.out_dir.glob("*.json")):
        if p.name == "manifest.json":
            continue
        bits = p.stem.split("_")
        if len(bits) < 3:
            continue
        try:
            year = int(bits[-1])
        except ValueError:
            continue
        if bits[0] == "state" and len(bits) >= 4:
            scope = "_".join(bits[:2])
            contest = "_".join(bits[2:-1])
        else:
            scope = bits[0]
            contest = "_".join(bits[1:-1])
        try:
            node = json.loads(p.read_text(encoding="utf-8"))
            districts = len((((node.get("general") or {}).get("results")) or {}))
        except Exception:
            districts = 0
        manifest_rows.append(
            {"year": year, "scope": scope, "contest_type": contest, "file": p.name, "districts": districts}
        )
    manifest_rows.sort(key=lambda r: (r["year"], r["scope"], r["contest_type"]))
    (args.out_dir / "manifest.json").write_text(json.dumps({"files": manifest_rows}, indent=2), encoding="utf-8")
    print(f"Wrote manifest: {args.out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
