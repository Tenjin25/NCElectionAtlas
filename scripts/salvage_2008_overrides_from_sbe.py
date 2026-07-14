#!/usr/bin/env python3
"""
Salvage 2008 name-only precincts using official NCSBE precinct shapefiles.

Unlike the VTD00 path, this uses SBE attributes:
  PREC_ID / ENR_DESC (2012) and/or Precinct / SEIMS_Code (2006)

then spatially maps those era codes onto modern Voting_Precincts / SBE 2024.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import geopandas as gpd
import pandas as pd

from build_district_results_2024_lines import _compact, _norm
from build_precinct_geometry_crosswalks import build_crosswalk
from build_district_contests_from_batch_shatter import load_sbe_precinct_code_map

TARGET_CRS = "EPSG:5070"


def _norm_name(text: str) -> str:
    t = _norm(text)
    t = t.replace("#", " ")
    t = t.replace("_", " ").replace("-", " ").replace(".", " ")
    t = re.sub(r"\bPRECINCT\b", " ", t)
    t = " ".join(t.split())
    return t


def _name_keys(text: str) -> set[str]:
    n = _norm_name(text)
    out = {n, _compact(n)}
    parts = n.split()
    if parts and re.fullmatch(r"[A-Z]*\d+[A-Z]*", parts[0]) and len(parts) > 1:
        rest = " ".join(parts[1:])
        out.add(rest)
        out.add(_compact(rest))
    # hyphenate codes: 1-A -> 1A
    if "-" in n and re.fullmatch(r"[0-9]+-[A-Z0-9]+", n.replace(" ", "")):
        out.add(_compact(n))
    return {x for x in out if x}


def load_modern_keys(path: Path) -> set[str]:
    g = gpd.read_file(path)
    cols = {c.lower(): c for c in g.columns}
    county_col = cols.get("county_nam") or cols.get("county")
    prec_col = cols.get("prec_id") or cols.get("precinct_id")
    out: set[str] = set()
    for _, r in g.iterrows():
        county = _norm(r[county_col])
        prec = _norm(r[prec_col])
        if county and prec:
            out.add(f"{county} - {prec}")
    return out


def load_2008_keys(results_csv: Path) -> set[str]:
    keys: set[str] = set()
    with open(results_csv, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            county = _norm(row.get("county", ""))
            precinct = _norm(row.get("precinct", ""))
            if not county or not precinct:
                continue
            p = _norm_name(precinct)
            if p in {"ONE STOP", "ABSENTEE BY MAIL", "PROVISIONAL", "TRANSFER", "ABSENTEE", "PROV", "CURBSIDE", "TRANSERS"}:
                continue
            if "ABSENTEE" in p or "ONE STOP" in p or p.startswith("OS ") or "CURBSIDE" in p:
                continue
            keys.add(f"{county} - {precinct}")
    return keys


def load_2006_sbe(path: Path) -> gpd.GeoDataFrame:
    g = gpd.read_file(path)
    out = g[["County", "Precinct", "SEIMS_Code", "geometry"]].copy()
    out = out.rename(columns={"County": "county", "Precinct": "precinct_name", "SEIMS_Code": "precinct_id"})
    out["county"] = out["county"].map(_norm)
    out["precinct_id"] = out["precinct_id"].map(_norm)
    out["precinct_name"] = out["precinct_name"].map(_norm_name)
    out = out[(out["county"] != "") & (out["precinct_id"] != "")].copy()
    out["precinct_key"] = out["county"] + " - " + out["precinct_id"]
    return out


def load_sbe_precincts(path: Path) -> gpd.GeoDataFrame:
    g = gpd.read_file(path)
    cols = {c.lower(): c for c in g.columns}
    county_col = cols.get("county_nam") or cols.get("county")
    prec_col = cols.get("prec_id") or cols.get("precinct_id")
    desc_col = cols.get("enr_desc") or cols.get("precinct_name") or cols.get("precinct")
    out = g[[county_col, prec_col, desc_col, "geometry"]].copy()
    out = out.rename(columns={county_col: "county", prec_col: "precinct_id", desc_col: "precinct_name"})
    out["county"] = out["county"].map(_norm)
    out["precinct_id"] = out["precinct_id"].map(_norm)
    out["precinct_name"] = out["precinct_name"].map(_norm_name)
    out = out[(out["county"] != "") & (out["precinct_id"] != "")].copy()
    out["precinct_key"] = out["county"] + " - " + out["precinct_id"]
    return out


def build_attr_index(gdf: gpd.GeoDataFrame) -> dict[str, dict[str, set[str]]]:
    """county -> alias -> {precinct_key}."""
    idx: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for _, r in gdf.iterrows():
        county = r["county"]
        key = r["precinct_key"]
        for a in _name_keys(r["precinct_id"]) | _name_keys(r["precinct_name"]):
            idx[county][a].add(key)
        # ENR_DESC often "G1_GWALTNEY #1" — also index right side only.
        raw_name = str(r["precinct_name"])
        if "_" in raw_name:
            right = _norm_name(raw_name.split("_", 1)[1])
            for a in _name_keys(right):
                idx[county][a].add(key)
    return idx


def resolve_via_attr(county: str, precinct: str, idx: dict[str, dict[str, set[str]]]) -> tuple[str | None, str]:
    aliases = idx.get(county)
    if not aliases:
        return None, "no_county"
    hits: set[str] = set()
    for a in _name_keys(precinct):
        hits |= aliases.get(a, set())
    # Pasquotank-style "1-A ELIZABETH CITY"
    m = re.match(r"^([0-9]+)\s*-\s*([A-Z])\b", _norm(precinct))
    if m:
        code = f"{m.group(1)}{m.group(2)}"
        hits |= aliases.get(code, set())
        hits |= aliases.get(_compact(code), set())
    # "PCT 1"
    m = re.match(r"^PCT\s+#?\s*([0-9]{1,3}[A-Z]?)$", _norm(precinct))
    if m:
        n = m.group(1)
        hits |= aliases.get(n, set())
        if n.isdigit():
            hits |= aliases.get(str(int(n)), set())
            hits |= aliases.get(f"{int(n):02d}", set())
            hits |= aliases.get(f"{int(n):03d}", set())
    # "011 - SCHOOL"
    m = re.match(r"^([A-Z0-9.\-]{1,12})\s+-\s+(.+)$", _norm(precinct))
    if m:
        hits |= aliases.get(_norm(m.group(1)), set())
        hits |= aliases.get(_compact(m.group(1)), set())
        for a in _name_keys(m.group(2)):
            hits |= aliases.get(a, set())
    if len(hits) == 1:
        return next(iter(hits)), "unique_attr"
    if len(hits) > 1:
        return None, "ambiguous_attr"
    return None, "unmatched_attr"


def main() -> None:
    ap = argparse.ArgumentParser(description="Salvage 2008 using official SBE precinct shapefiles.")
    ap.add_argument("--results-csv", type=Path, default=Path("data/2008/20081104__nc__general__precinct.csv"))
    ap.add_argument(
        "--sbe-2012",
        type=Path,
        default=Path("downloads/ncsbe/precinct_shp/2012/SBE_PRECINCTS_09012012.shp"),
    )
    ap.add_argument(
        "--sbe-2006",
        type=Path,
        default=Path("downloads/ncsbe/precinct_shp/2006/Precincts2006Gen.shp"),
    )
    ap.add_argument(
        "--modern",
        type=Path,
        default=Path("data/2025Voting_Precincts.geojson"),
    )
    ap.add_argument("--min-old-share", type=float, default=0.50)
    ap.add_argument(
        "--out-crosswalk-prefix",
        type=Path,
        default=Path("data/crosswalks/sbe2012_to_nconemap"),
    )
    ap.add_argument(
        "--out-suggestions",
        type=Path,
        default=Path("data/reports/precinct_key_overrides_2008_sbe_suggestions.csv"),
    )
    ap.add_argument(
        "--out-overrides",
        type=Path,
        default=Path("data/reports/precinct_key_overrides_2008_sbe_auto.csv"),
    )
    ap.add_argument("--apply-to-overrides", action="store_true")
    args = ap.parse_args()

    results_csv = args.results_csv if args.results_csv.is_absolute() else ROOT / args.results_csv
    sbe_2012 = args.sbe_2012 if args.sbe_2012.is_absolute() else ROOT / args.sbe_2012
    sbe_2006 = args.sbe_2006 if args.sbe_2006.is_absolute() else ROOT / args.sbe_2006
    modern_path = args.modern if args.modern.is_absolute() else ROOT / args.modern
    out_prefix = args.out_crosswalk_prefix if args.out_crosswalk_prefix.is_absolute() else ROOT / args.out_crosswalk_prefix
    out_sug = args.out_suggestions if args.out_suggestions.is_absolute() else ROOT / args.out_suggestions
    out_auto = args.out_overrides if args.out_overrides.is_absolute() else ROOT / args.out_overrides

    print("Loading SBE 2012 / 2006 / modern...")
    g2012 = load_sbe_precincts(sbe_2012)
    g2006 = load_2006_sbe(sbe_2006) if sbe_2006.exists() else None
    gmodern = load_sbe_precincts(modern_path)

    print("Building spatial crosswalk SBE2012 -> modern...")
    detail, best_old, best_new, county_df = build_crosswalk(g2012, gmodern, min_share=0.01)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    detail_path = out_prefix.with_name(out_prefix.name + "_detail.csv")
    best_path = out_prefix.with_name(out_prefix.name + "_best_old_to_new.csv")
    county_path = out_prefix.with_name(out_prefix.name + "_county_summary.csv")
    detail.to_csv(detail_path, index=False)
    best_old.to_csv(best_path, index=False)
    county_df.to_csv(county_path, index=False)
    print(f"Wrote {best_path} ({len(best_old)} best matches)")

    best_map: dict[str, tuple[str, float]] = {}
    for _, r in best_old.iterrows():
        old_key = _norm(r["old_precinct_key"])
        new_key = _norm(r["new_precinct_key"])
        share = float(pd.to_numeric(r["old_share"], errors="coerce") or 0.0)
        if share >= args.min_old_share:
            best_map[old_key] = (new_key, share)

    idx_2012 = build_attr_index(g2012)
    idx_2006 = build_attr_index(g2006) if g2006 is not None else {}
    # Also reuse shatter helper map for ENR_DESC variants.
    sbe_map = load_sbe_precinct_code_map(sbe_2012)

    modern_keys = load_modern_keys(modern_path)
    raw_keys = load_2008_keys(results_csv)

    suggestions: list[dict[str, str]] = []
    auto_rows: list[dict[str, str]] = []
    stats: dict[str, int] = defaultdict(int)

    for raw in sorted(raw_keys):
        stats["total"] += 1
        county, precinct = raw.split(" - ", 1)
        era_key = None
        status = ""

        # Official ENR_DESC map first.
        hit = sbe_map.get((county, _norm_name(precinct).replace(" ", " ")))
        # load_sbe uses _norm_spaces; try several forms.
        if not hit:
            for cand in [
                _norm(precinct),
                _norm_name(precinct),
                _norm(precinct).replace("#", " "),
                _norm_name(precinct.replace("#", " ")),
            ]:
                hit = sbe_map.get((county, cand))
                if hit:
                    break
        if hit:
            era_key = f"{county} - {_norm(hit)}"
            status = "sbe_enr_map"
        else:
            era_key, status = resolve_via_attr(county, precinct, idx_2012)
            if not era_key and idx_2006:
                era_key, status = resolve_via_attr(county, precinct, idx_2006)
                if era_key:
                    status = "sbe2006_" + status

        stats[f"era_{status}"] += 1
        if not era_key:
            suggestions.append(
                {
                    "year": "2008",
                    "raw_precinct_key": raw,
                    "era_precinct_key": "",
                    "canonical_precinct_key": "",
                    "old_share": "",
                    "status": status or "unmatched_attr",
                }
            )
            continue

        mapped = best_map.get(era_key)
        if not mapped:
            # If era key already modern, accept directly.
            if era_key in modern_keys:
                canonical, share, st = era_key, 1.0, "era_already_modern"
            else:
                stats["no_spatial_hit"] += 1
                suggestions.append(
                    {
                        "year": "2008",
                        "raw_precinct_key": raw,
                        "era_precinct_key": era_key,
                        "canonical_precinct_key": "",
                        "old_share": "",
                        "status": "no_spatial_hit",
                    }
                )
                continue
        else:
            canonical, share = mapped
            st = "auto_accept" if share >= args.min_old_share and canonical in modern_keys else "review"

        if st in {"auto_accept", "era_already_modern"} and canonical in modern_keys:
            stats["auto_accept"] += 1
            auto_rows.append(
                {"year": "2008", "raw_precinct_key": raw, "canonical_precinct_key": canonical}
            )
        else:
            stats[st] += 1

        suggestions.append(
            {
                "year": "2008",
                "raw_precinct_key": raw,
                "era_precinct_key": era_key,
                "canonical_precinct_key": canonical,
                "old_share": f"{share:.6f}",
                "status": st if st != "era_already_modern" else "auto_accept",
            }
        )

    out_sug.parent.mkdir(parents=True, exist_ok=True)
    with open(out_sug, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "year",
                "raw_precinct_key",
                "era_precinct_key",
                "canonical_precinct_key",
                "old_share",
                "status",
            ],
        )
        w.writeheader()
        w.writerows(suggestions)
    with open(out_auto, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["year", "raw_precinct_key", "canonical_precinct_key"])
        w.writeheader()
        w.writerows(auto_rows)

    if args.apply_to_overrides:
        overrides_path = ROOT / "data" / "mappings" / "precinct_key_overrides.csv"
        existing = set()
        rows_out: list[dict[str, str]] = []
        if overrides_path.exists():
            with open(overrides_path, "r", encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    year = _norm(r.get("year", "")) or "*"
                    raw = _norm(r.get("raw_precinct_key", ""))
                    can = _norm(r.get("canonical_precinct_key", ""))
                    if not raw or not can:
                        continue
                    existing.add((year, raw))
                    rows_out.append({"year": year, "raw_precinct_key": raw, "canonical_precinct_key": can})
        added = 0
        for r in auto_rows:
            key = (_norm(r["year"]), _norm(r["raw_precinct_key"]))
            if key in existing:
                continue
            rows_out.append(r)
            existing.add(key)
            added += 1
        with open(overrides_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["year", "raw_precinct_key", "canonical_precinct_key"])
            w.writeheader()
            w.writerows(rows_out)
        stats["overrides_added"] = added
        print(f"Appended {added} rows to {overrides_path}")

    print(f"Wrote {out_sug}")
    print(f"Wrote {out_auto} ({len(auto_rows)} auto rows)")
    print(json.dumps(dict(stats), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
