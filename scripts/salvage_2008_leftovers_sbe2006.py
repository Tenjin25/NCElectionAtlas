#!/usr/bin/env python3
"""
Close remaining 2008 unmatched keys using the 2006 SBE precinct map.

Many leftovers fail because:
  - 2008 labels use "NO 1" while SBE ENR uses "#1"
  - codes like Belville/FR5/CL57 exist in 2006 but were split/renamed by 2012
  - Cherokee BEAVERDAM Y/Z map to 2006 BEAV, etc.

This script builds SBE2006 -> modern spatial matches and emits high-confidence
overrides for current unmatched 2008 keys only.
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
from salvage_2008_overrides_from_sbe import (
    _name_keys,
    _norm_name,
    load_2006_sbe,
    load_2008_keys,
    load_modern_keys,
    load_sbe_precincts,
)


def expand_label_aliases(precinct: str) -> set[str]:
    base = _norm_name(precinct)
    out = _name_keys(precinct)
    # NO <-> # / NUMBER
    out |= _name_keys(re.sub(r"\bNO\b", "#", base))
    out |= _name_keys(re.sub(r"\bNUMBER\b", "#", base))
    out |= _name_keys(re.sub(r"#", " NO ", base))
    out |= _name_keys(re.sub(r"#", " ", base))
    # drop satellite/admin suffixes
    out |= _name_keys(re.sub(r"\bSAT\b|\bSATELLITE\b", " ", base))
    # strip trailing single letters Y/Z for Cherokee-style suffixes
    m = re.match(r"^(.+?)\s+([YZ])$", base)
    if m:
        out |= _name_keys(m.group(1))
    # Roman/I variants: SHINGLETREE I -> SHINGLETREE 1
    out |= _name_keys(re.sub(r"\bI\b", "1", base))
    out |= _name_keys(re.sub(r"\bII\b", "2", base))
    out |= _name_keys(re.sub(r"\bIII\b", "3", base))
    # truncated SPRING
    if base.endswith("SPRING"):
        out |= _name_keys(base + "S")
    if base.endswith("VALLE"):
        out |= _name_keys(base + "Y")
    return {x for x in out if x}


def build_2006_index(g06: gpd.GeoDataFrame) -> dict[str, dict[str, set[str]]]:
    idx: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for _, r in g06.iterrows():
        county = r["county"]
        key = r["precinct_key"]
        for a in _name_keys(r["precinct_id"]) | _name_keys(r["precinct_name"]):
            idx[county][a].add(key)
        # Combined labels: "Balsam Grove & Gloucester" / "Scotts Creek 1, 2, & 3"
        name = str(r["precinct_name"])
        for part in re.split(r"\s*&\s*|,|/|\bAND\b", name):
            part = _norm_name(part)
            if part:
                for a in _name_keys(part):
                    idx[county][a].add(key)
    return idx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-csv", type=Path, default=Path("data/2008/20081104__nc__general__precinct.csv"))
    ap.add_argument("--sbe-2006", type=Path, default=Path("downloads/ncsbe/precinct_shp/2006/Precincts2006Gen.shp"))
    ap.add_argument("--modern", type=Path, default=Path("data/2025Voting_Precincts.geojson"))
    ap.add_argument("--unmatched-examples", type=Path, default=Path("data/reports/unmatched_precinct_examples.csv"))
    ap.add_argument("--min-old-share", type=float, default=0.35)
    ap.add_argument("--out-crosswalk-prefix", type=Path, default=Path("data/crosswalks/sbe2006_to_nconemap"))
    ap.add_argument("--out-overrides", type=Path, default=Path("data/reports/precinct_key_overrides_2008_sbe2006_leftovers.csv"))
    ap.add_argument("--apply-to-overrides", action="store_true")
    args = ap.parse_args()

    results_csv = ROOT / args.results_csv if not args.results_csv.is_absolute() else args.results_csv
    sbe_2006 = ROOT / args.sbe_2006 if not args.sbe_2006.is_absolute() else args.sbe_2006
    modern = ROOT / args.modern if not args.modern.is_absolute() else args.modern
    unmatched_path = ROOT / args.unmatched_examples if not args.unmatched_examples.is_absolute() else args.unmatched_examples
    out_prefix = ROOT / args.out_crosswalk_prefix if not args.out_crosswalk_prefix.is_absolute() else args.out_crosswalk_prefix
    out_overrides = ROOT / args.out_overrides if not args.out_overrides.is_absolute() else args.out_overrides

    # Restrict to currently unmatched 2008 keys when available.
    target: set[str] = set()
    if unmatched_path.exists():
        with open(unmatched_path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("year") == "2008" and r.get("status") == "unmatched":
                    target.add(_norm(r["precinct_key"]))
    if not target:
        target = load_2008_keys(results_csv)

    # typo non-geo
    target.discard("JONES - TRANSERS")

    print(f"Target leftovers: {len(target)}")
    g06 = load_2006_sbe(sbe_2006)
    gmod = load_sbe_precincts(modern)
    print("Building SBE2006 -> modern spatial crosswalk...")
    detail, best_old, best_new, county_df = build_crosswalk(g06, gmod, min_share=0.01)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    best_path = out_prefix.with_name(out_prefix.name + "_best_old_to_new.csv")
    detail_path = out_prefix.with_name(out_prefix.name + "_detail.csv")
    county_path = out_prefix.with_name(out_prefix.name + "_county_summary.csv")
    best_old.to_csv(best_path, index=False)
    detail.to_csv(detail_path, index=False)
    county_df.to_csv(county_path, index=False)
    print(f"Wrote {best_path} ({len(best_old)} rows)")

    best_map: dict[str, tuple[str, float]] = {}
    for _, r in best_old.iterrows():
        old_key = _norm(r["old_precinct_key"])
        new_key = _norm(r["new_precinct_key"])
        share = float(pd.to_numeric(r["old_share"], errors="coerce") or 0.0)
        best_map[old_key] = (new_key, share)

    idx = build_2006_index(g06)
    modern_keys = load_modern_keys(modern)

    rows: list[dict[str, str]] = []
    stats = defaultdict(int)
    for raw in sorted(target):
        stats["total"] += 1
        county, precinct = raw.split(" - ", 1)
        aliases = expand_label_aliases(precinct)
        hits: set[str] = set()
        for a in aliases:
            hits |= idx.get(county, {}).get(a, set())
        if len(hits) != 1:
            stats["attr_fail" if not hits else "attr_ambiguous"] += 1
            continue
        era_key = next(iter(hits))
        mapped = best_map.get(era_key)
        if not mapped:
            stats["no_spatial"] += 1
            continue
        canonical, share = mapped
        if canonical not in modern_keys or share < args.min_old_share:
            stats["low_share_or_missing"] += 1
            continue
        stats["auto"] += 1
        rows.append(
            {
                "year": "2008",
                "raw_precinct_key": raw,
                "era_precinct_key": era_key,
                "canonical_precinct_key": canonical,
                "old_share": f"{share:.6f}",
            }
        )

    out_overrides.parent.mkdir(parents=True, exist_ok=True)
    with open(out_overrides, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["year", "raw_precinct_key", "era_precinct_key", "canonical_precinct_key", "old_share"],
        )
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {out_overrides} ({len(rows)} rows)")
    print(json.dumps(dict(stats), indent=2, sort_keys=True))

    if args.apply_to_overrides:
        overrides_path = ROOT / "data" / "mappings" / "precinct_key_overrides.csv"
        existing = set()
        out_rows: list[dict[str, str]] = []
        with open(overrides_path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                year = _norm(r.get("year", "")) or "*"
                raw = _norm(r.get("raw_precinct_key", ""))
                can = _norm(r.get("canonical_precinct_key", ""))
                if not raw or not can:
                    continue
                existing.add((year, raw))
                out_rows.append({"year": year, "raw_precinct_key": raw, "canonical_precinct_key": can})
        added = 0
        for r in rows:
            key = ("2008", _norm(r["raw_precinct_key"]))
            if key in existing:
                continue
            out_rows.append(
                {
                    "year": "2008",
                    "raw_precinct_key": _norm(r["raw_precinct_key"]),
                    "canonical_precinct_key": _norm(r["canonical_precinct_key"]),
                }
            )
            existing.add(key)
            added += 1
        # Mark TRANSERS as non-geo by mapping? Better leave unmatched / skip. Optional:
        # no override for JONES - TRANSERS.
        with open(overrides_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["year", "raw_precinct_key", "canonical_precinct_key"])
            w.writeheader()
            w.writerows(out_rows)
        print(f"Appended {added} overrides")


if __name__ == "__main__":
    main()
