"""Compose an older precinct alias bridge through a newer precinct vintage.

The browser only needs county-scoped old aliases and their current precinct code.
This keeps historical result keys usable after the displayed geometry advances
without rebuilding every contest onto the newest precinct vintage.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


FIELDS = [
    "county",
    "old_precinct_key",
    "old_precinct_id",
    "old_precinct_name",
    "new_precinct_key",
    "new_precinct_id",
    "new_precinct_name",
    "is_best_for_old",
    "bridge_source",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", required=True, type=Path)
    parser.add_argument("--next", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    next_rows = read_rows(args.next)
    next_by_old = {
        row["old_precinct_key"].strip().upper(): row
        for row in next_rows
        if row.get("old_precinct_key") and row.get("new_precinct_id")
    }

    output: dict[tuple[str, str], dict[str, str]] = {}

    # Include the entire immediately preceding vintage, including unchanged keys.
    for row in next_rows:
        if not row.get("old_precinct_key") or not row.get("new_precinct_id"):
            continue
        item = {field: str(row.get(field, "")) for field in FIELDS}
        item["is_best_for_old"] = "True"
        item["bridge_source"] = "onemap_2025_12"
        key = (item["county"].strip().upper(), item["old_precinct_key"].strip().upper())
        output[key] = item

    # Carry older aliases forward through their prior target precinct.
    for row in read_rows(args.previous):
        intermediate = str(row.get("new_precinct_key", "")).strip().upper()
        target = next_by_old.get(intermediate)
        if not target:
            continue
        item = {
            "county": str(row.get("county", target.get("county", ""))),
            "old_precinct_key": str(row.get("old_precinct_key", "")),
            "old_precinct_id": str(row.get("old_precinct_id", "")),
            "old_precinct_name": str(row.get("old_precinct_name", "")),
            "new_precinct_key": str(target.get("new_precinct_key", "")),
            "new_precinct_id": str(target.get("new_precinct_id", "")),
            "new_precinct_name": str(target.get("new_precinct_name", "")),
            "is_best_for_old": "True",
            "bridge_source": "stable_via_onemap_2025_12",
        }
        key = (item["county"].strip().upper(), item["old_precinct_key"].strip().upper())
        output.setdefault(key, item)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(output.values(), key=lambda row: (row["county"], row["old_precinct_key"]))
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {args.out} with {len(rows)} aliases")


if __name__ == "__main__":
    main()
