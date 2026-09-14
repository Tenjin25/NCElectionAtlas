#!/usr/bin/env python3
"""Canonicalize whole-county State Senate districts for each live line set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fix_2024_house_whole_county_totals import VOTE_FIELDS, finalize


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data" / "contests"
LINE_SETS = {
    ROOT / "data" / "district_contests": {
        1: ("CARTERET", "CHOWAN", "DARE", "HYDE", "PAMLICO", "PASQUOTANK", "PERQUIMANS", "WASHINGTON"),
        2: ("BEAUFORT", "CRAVEN", "LENOIR"),
        3: ("BERTIE", "CAMDEN", "CURRITUCK", "GATES", "HALIFAX", "HERTFORD", "MARTIN", "NORTHAMPTON", "TYRRELL", "WARREN"),
        4: ("GREENE", "WAYNE", "WILSON"),
        5: ("EDGECOMBE", "PITT"),
        6: ("ONSLOW",),
        10: ("JOHNSTON",),
        11: ("FRANKLIN", "NASH", "VANCE"),
        23: ("CASWELL", "ORANGE", "PERSON"),
        24: ("HOKE", "ROBESON", "SCOTLAND"),
        30: ("DAVIDSON", "DAVIE"),
        33: ("ROWAN", "STANLY"),
        36: ("ALEXANDER", "SURRY", "WILKES", "YADKIN"),
        48: ("HENDERSON", "POLK", "RUTHERFORD"),
    },
    ROOT / "data" / "district_contests_2024_lines": {
        1: ("BERTIE", "CAMDEN", "CURRITUCK", "DARE", "GATES", "HERTFORD", "NORTHAMPTON", "PASQUOTANK", "PERQUIMANS", "TYRRELL"),
        2: ("CARTERET", "CHOWAN", "HALIFAX", "HYDE", "MARTIN", "PAMLICO", "WARREN", "WASHINGTON"),
        3: ("BEAUFORT", "CRAVEN", "LENOIR"),
        4: ("GREENE", "WAYNE", "WILSON"),
        5: ("EDGECOMBE", "PITT"),
        6: ("ONSLOW",),
        10: ("JOHNSTON",),
        11: ("FRANKLIN", "NASH", "VANCE"),
        23: ("CASWELL", "ORANGE", "PERSON"),
        24: ("HOKE", "ROBESON", "SCOTLAND"),
        30: ("DAVIDSON", "DAVIE"),
        33: ("ROWAN", "STANLY"),
        36: ("ALEXANDER", "SURRY", "WILKES", "YADKIN"),
        48: ("HENDERSON", "POLK", "RUTHERFORD"),
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    report = []

    for directory, clusters in LINE_SETS.items():
        for destination_path in sorted(directory.glob("state_senate_*.json")):
            if destination_path.name.startswith("state_senate_state_senate_"):
                continue
            contest_path = SOURCE_DIR / destination_path.name.removeprefix("state_senate_")
            if not contest_path.exists():
                continue
            destination = json.loads(destination_path.read_text(encoding="utf-8"))
            contest = json.loads(contest_path.read_text(encoding="utf-8"))
            rows = destination.get("general", {}).get("results", {})
            counties = contest.get("county_totals", {})
            changed = []

            for district, county_names in clusters.items():
                row = rows.get(str(district))
                if not isinstance(row, dict) or not all(name in counties for name in county_names):
                    continue
                candidate_labels = {}
                for field in ("dem_candidate", "rep_candidate"):
                    labels = {str(counties[name].get(field, "")) for name in county_names}
                    if len(labels) != 1:
                        candidate_labels = None
                        break
                    candidate_labels[field] = labels.pop()
                if candidate_labels is None:
                    continue
                exact = {
                    field: sum(int(counties[name].get(field, 0) or 0) for name in county_names)
                    for field in VOTE_FIELDS
                }
                before_margin = float(row.get("margin_pct", 0) or 0)
                if all(int(row.get(field, 0) or 0) == exact[field] for field in VOTE_FIELDS):
                    continue
                finalize(row, exact, candidate_labels)
                changed.append({
                    "district": district,
                    "before_margin": before_margin,
                    "canonical_margin": row["margin_pct"],
                })

            meta = destination.setdefault("meta", {})
            meta["whole_county_exact_override"] = True
            meta["whole_county_exact_districts"] = [str(d) for d in sorted(clusters)]
            meta["whole_county_exact_method"] = (
                "Sum canonical county contest totals for districts composed entirely "
                "of one or more whole counties on this specific line set."
            )
            if changed:
                report.append({"file": str(destination_path.relative_to(ROOT)), "changes": changed})
            if args.write and changed:
                destination_path.write_text(json.dumps(destination, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({"mode": "write" if args.write else "audit", "files": report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
