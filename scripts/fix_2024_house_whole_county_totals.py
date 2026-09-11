#!/usr/bin/env python3
"""Canonicalize whole-county House districts in both line-set datasets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data" / "contests"
TARGET_DIRS = (
    ROOT / "data" / "district_contests",
    ROOT / "data" / "district_contests_2024_lines",
)

# Exactly the same complete counties in both House plans. Districts containing
# any county split, including HD-24/25 in Nash County, are excluded.
CLUSTERS = {
    5: ("CAMDEN", "GATES", "HERTFORD", "PASQUOTANK"),
    12: ("GREENE", "JONES", "LENOIR"),
    22: ("BLADEN", "SAMPSON"),
    23: ("BERTIE", "EDGECOMBE", "MARTIN"),
    27: ("HALIFAX", "NORTHAMPTON", "WARREN"),
    48: ("HOKE", "SCOTLAND"),
    65: ("ROCKINGHAM",),
    67: ("MONTGOMERY", "STANLY"),
    86: ("BURKE",),
    97: ("LINCOLN",),
    118: ("HAYWOOD", "MADISON"),
    119: ("JACKSON", "SWAIN", "TRANSYLVANIA"),
    120: ("CHEROKEE", "CLAY", "GRAHAM", "MACON"),
}
VOTE_FIELDS = ("dem_votes", "rep_votes", "other_votes")


def color(margin_pct: float) -> str:
    absolute = abs(margin_pct)
    republican = margin_pct > 0
    if absolute < 0.5: return "#f7f7f7"
    if absolute >= 40: return "#67000d" if republican else "#08306b"
    if absolute >= 30: return "#a50f15" if republican else "#08519c"
    if absolute >= 20: return "#cb181d" if republican else "#3182bd"
    if absolute >= 10: return "#ef3b2c" if republican else "#6baed6"
    if absolute >= 5.5: return "#fb6a4a" if republican else "#9ecae1"
    if absolute >= 1: return "#fcae91" if republican else "#c6dbef"
    return "#fee8c8" if republican else "#e1f5fe"


def finalize(row: dict, exact: dict[str, int], candidates: dict[str, str]) -> None:
    row.update(exact)
    row.update(candidates)
    total = sum(exact.values())
    margin = exact["rep_votes"] - exact["dem_votes"]
    margin_pct = round(100 * margin / total, 2) if total else 0
    row.update({
        "total_votes": total,
        "margin": margin,
        "margin_pct": margin_pct,
        "winner": "REP" if margin > 0 else "DEM" if margin < 0 else "TIE",
        "competitiveness": {"color": color(margin_pct)},
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    report = []

    for dest_path in sorted(path for directory in TARGET_DIRS for path in directory.glob("state_house_*.json")):
        if dest_path.name.startswith("state_house_state_house_"):
            continue
        contest_path = SOURCE_DIR / dest_path.name.removeprefix("state_house_")
        if not contest_path.exists():
            continue
        destination = json.loads(dest_path.read_text(encoding="utf-8"))
        contest = json.loads(contest_path.read_text(encoding="utf-8"))
        rows = destination.get("general", {}).get("results", {})
        counties = contest.get("county_totals", {})
        changed = []

        for district, county_names in CLUSTERS.items():
            key = str(district)
            if key not in rows or not all(name in counties for name in county_names):
                continue
            canonical_candidate = {}
            for field in ("dem_candidate", "rep_candidate"):
                labels = {str(counties[name].get(field, "")) for name in county_names}
                if len(labels) != 1:
                    canonical_candidate = None
                    break
                canonical_candidate[field] = labels.pop()
            if canonical_candidate is None:
                continue
            exact = {
                field: sum(int(counties[name].get(field, 0) or 0) for name in county_names)
                for field in VOTE_FIELDS
            }
            current = rows[key]
            vote_change = sum(abs(exact[field] - int(current.get(field, 0) or 0)) for field in VOTE_FIELDS)
            candidate_change = any(
                str(current.get(field, "")) != value
                for field, value in canonical_candidate.items()
            )
            if vote_change == 0 and not candidate_change:
                continue
            delta = {field: exact[field] - int(current.get(field, 0) or 0) for field in VOTE_FIELDS}
            finalize(current, exact, canonical_candidate)
            changed.append({
                "district": district,
                "vote_change": vote_change,
                "candidate_change": candidate_change,
                "delta": delta,
            })

        if changed:
            report.append({"file": str(dest_path.relative_to(ROOT)), "changes": changed})
            if args.write:
                dest_path.write_text(json.dumps(destination, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({"mode": "write" if args.write else "audit", "files": report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
