#!/usr/bin/env python3
"""Lock near-identical 2024 State Senate geometries to the 2022-line results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from calibrate_district_slices_from_stats_csv import calculate_competitiveness

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data/district_contests"
DEST_DIR = ROOT / "data/district_contests_2024_lines"

# 2024-line district -> same/near-identical 2022-line district, verified with GeoPandas.
LOCKED = {
    "state_senate": {3: 2, 4: 4, 5: 5, 6: 6, 9: 9, 10: 10, 11: 11, 12: 12, 23: 23, 24: 24, 30: 30, 33: 33, 36: 36, 43: 43, 44: 44, 48: 48},
    "state_house": {2: 2, 5: 5, 12: 12, 16: 16, 22: 22, 23: 23, 24: 24, 25: 25, 27: 27, 28: 28, 29: 29, 30: 30, 31: 31, 48: 48, 51: 51, 52: 52, 54: 54, 65: 65, 67: 67, 76: 76, 78: 78, 86: 86, 87: 87, 89: 89, 93: 93, 96: 96, 97: 97, 118: 118, 119: 119, 120: 120},
}
FIELDS = ("dem_votes", "rep_votes", "other_votes")


def finalize(row: dict) -> None:
    row["total_votes"] = row["dem_votes"] + row["rep_votes"] + row["other_votes"]
    row["margin"] = row["rep_votes"] - row["dem_votes"]
    row["margin_pct"] = round(100 * row["margin"] / row["total_votes"], 2) if row["total_votes"] else 0
    row["winner"] = "REP" if row["margin"] > 0 else "DEM" if row["margin"] < 0 else "TIE"
    if isinstance(row.get("competitiveness"), dict):
        row["competitiveness"]["color"] = calculate_competitiveness(float(row["margin_pct"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    changed = 0
    balanced = 0
    details = []

    for scope, locked in LOCKED.items():
      for source_path in sorted(SOURCE_DIR.glob(f"{scope}_*_2024.json")):
        if source_path.name == f"{scope}_{scope}_2024.json":
            continue
        dest_path = DEST_DIR / source_path.name
        if not dest_path.exists():
            continue
        source = json.loads(source_path.read_text(encoding="utf-8"))
        destination = json.loads(dest_path.read_text(encoding="utf-8"))
        src = source["general"]["results"]
        dst = destination["general"]["results"]
        target_totals = {field: sum(int(row[field]) for row in dst.values()) for field in FIELDS}
        touched = []
        for new_district, old_district in locked.items():
            before = {field: dst[str(new_district)][field] for field in FIELDS}
            canonical = {field: src[str(old_district)][field] for field in FIELDS}
            if before != canonical:
                for field in FIELDS:
                    dst[str(new_district)][field] = canonical[field]
                finalize(dst[str(new_district)])
                changed += 1
                touched.append(new_district)

        if touched:
            # Preserve each destination file's original statewide totals.
            balancer = max((d for d in dst if int(d) not in locked), key=lambda d: dst[d]["total_votes"])
            adjustments = {field: target_totals[field] - sum(int(row[field]) for row in dst.values()) for field in FIELDS}
            if any(adjustments.values()):
                for field, amount in adjustments.items():
                    dst[balancer][field] += amount
                finalize(dst[balancer])
                balanced += 1
            details.append({"scope": scope, "file": source_path.name, "locked_districts": touched, "balancer": balancer, "adjustments": adjustments})
            if args.write:
                destination["general"]["results"] = dst
                dest_path.write_text(json.dumps(destination, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

      
    print(json.dumps({"mode": "write" if args.write else "audit", "locked_rows": changed, "balanced_files": balanced, "details": details}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
