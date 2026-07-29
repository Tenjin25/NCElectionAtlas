#!/usr/bin/env python3
"""Refresh candidate display names in generated legislative-history JSON files.

This is intentionally separate from the expensive geometry crosswalk rebuild.
It updates both the top-level source races and their embedded modern-district
lineage copies, while leaving votes, weights, margins, and geometry untouched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any

from build_legislative_history_crosswalks import (
    ROOT,
    is_generic_candidate_placeholder,
    legislative_candidate_display_name,
)


HISTORY_DIR = ROOT / "data" / "legislative_history"


def clean_slate(candidates: list[dict[str, Any]], seats: int) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for candidate in candidates:
        row = dict(candidate)
        row["name"] = legislative_candidate_display_name(row.get("name", ""))
        if not row["name"] or is_generic_candidate_placeholder(row["name"]):
            continue
        cleaned.append(row)
    cleaned.sort(key=lambda row: (-int(row.get("votes") or 0), str(row["name"])))
    for rank, row in enumerate(cleaned, start=1):
        row["rank"] = rank
        row["elected"] = rank <= max(1, int(seats or 1))
    return cleaned


def refresh_payload(payload: dict[str, Any]) -> None:
    race_slates: dict[int, list[dict[str, Any]]] = {}
    for race in payload.get("source_races") or []:
        seats = max(1, int(race.get("seats") or 1))
        race["dem_candidate"] = legislative_candidate_display_name(
            race.get("dem_candidate", "")
        )
        race["rep_candidate"] = legislative_candidate_display_name(
            race.get("rep_candidate", "")
        )
        race["candidates"] = clean_slate(race.get("candidates") or [], seats)
        race_slates[int(race["district"])] = race["candidates"]

    for result in (payload.get("general", {}).get("results") or {}).values():
        for source in result.get("source_districts") or []:
            district = int(source["district"])
            source["candidates"] = [
                dict(candidate) for candidate in race_slates.get(district, [])
            ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh names without rebuilding legislative crosswalks."
    )
    parser.add_argument(
        "--base-ref",
        help="Read each existing payload from this Git ref before refreshing names.",
    )
    args = parser.parse_args()
    paths = sorted(HISTORY_DIR.glob("20??/state_*.json"))
    for path in paths:
        if args.base_ref:
            relative = path.relative_to(ROOT).as_posix()
            source = subprocess.run(
                ["git", "show", f"{args.base_ref}:{relative}"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            ).stdout
        else:
            source = path.read_text(encoding="utf-8")
        payload = json.loads(source)
        refresh_payload(payload)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(path.relative_to(ROOT))
    print(f"Refreshed candidate names in {len(paths)} legislative-history files.")


if __name__ == "__main__":
    main()
