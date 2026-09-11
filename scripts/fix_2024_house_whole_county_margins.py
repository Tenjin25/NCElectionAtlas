#!/usr/bin/env python3
"""Align displayed margins for unchanged whole-county House districts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data" / "district_contests"
DEST_DIR = ROOT / "data" / "district_contests_2024_lines"

# Each district contains exactly the same complete counties in both plans.
# Districts with any county split, including HD-24 and HD-25, are excluded.
WHOLE_COUNTY_DISTRICTS = (5, 12, 22, 23, 27, 48, 65, 67, 86, 97, 118, 119, 120)


def competitiveness_color(margin_pct: float) -> str:
    absolute = abs(margin_pct)
    republican = margin_pct > 0
    if absolute < 0.5:
        return "#f7f7f7"
    if absolute >= 40:
        return "#67000d" if republican else "#08306b"
    if absolute >= 30:
        return "#a50f15" if republican else "#08519c"
    if absolute >= 20:
        return "#cb181d" if republican else "#3182bd"
    if absolute >= 10:
        return "#ef3b2c" if republican else "#6baed6"
    if absolute >= 5.5:
        return "#fb6a4a" if republican else "#9ecae1"
    if absolute >= 1:
        return "#fcae91" if republican else "#c6dbef"
    return "#fee8c8" if republican else "#e1f5fe"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    touched: list[dict[str, object]] = []
    for source_path in sorted(SOURCE_DIR.glob("state_house_*.json")):
        if source_path.name.startswith("state_house_state_house_"):
            continue
        dest_path = DEST_DIR / source_path.name
        if not dest_path.exists():
            continue

        source = json.loads(source_path.read_text(encoding="utf-8"))
        destination = json.loads(dest_path.read_text(encoding="utf-8"))
        source_rows = source.get("general", {}).get("results", {})
        dest_rows = destination.get("general", {}).get("results", {})
        changed: list[int] = []

        for district in WHOLE_COUNTY_DISTRICTS:
            key = str(district)
            if key not in source_rows or key not in dest_rows:
                continue
            source_row = source_rows[key]
            dest_row = dest_rows[key]
            if any(
                str(source_row.get(field, "")) != str(dest_row.get(field, ""))
                for field in ("dem_candidate", "rep_candidate")
            ):
                continue
            target_margin = source_row.get("margin_pct")
            if target_margin is None or dest_row.get("margin_pct") == target_margin:
                continue
            dest_row["margin_pct"] = target_margin
            dest_row["competitiveness"] = {
                "color": competitiveness_color(float(target_margin))
            }
            changed.append(district)

        if changed:
            touched.append({"file": dest_path.name, "districts": changed})
            if args.write:
                dest_path.write_text(
                    json.dumps(destination, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )

    print(json.dumps({"mode": "write" if args.write else "audit", "files": touched}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
