#!/usr/bin/env python3
"""Repair targeted district calibration by line family."""
from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

HELPER_REF = "209bdadd7d5f3ffa5fa6203eafb98fdac60c14d5"
PRE_CALIBRATION_REF = "209bdadd7d5f3ffa5fa6203eafb98fdac60c14d5"

DEFAULT_2022_LINE_TARGETS = [
    "data/district_contests/state_house_president_2004.json",
    "data/district_contests/state_house_governor_2008.json",
    "data/district_contests/state_senate_president_2004.json",
    "data/district_contests/state_senate_governor_2008.json",
]

LEGISLATIVE_2024_LINE_TARGETS = [
    ("data/district_contests_2024_lines/state_house_president_2004.json", "NC-2024-State-House-district-statistics 2004 pres.csv"),
    ("data/district_contests_2024_lines/state_house_governor_2008.json", "NC-2024-State-House-district-statistics 2008 gov.csv"),
    ("data/district_contests_2024_lines/state_senate_president_2004.json", "NC-2024-State-Senate-district-statistics 2004 pres.csv"),
    ("data/district_contests_2024_lines/state_senate_governor_2008.json", "NC-2024-State-Senate-district-statistics 2008 gov.csv"),
]

CONGRESSIONAL_2026_TARGET = "data/district_contests_2026_lines/congressional_president_2024.json"
CONGRESSIONAL_2024_SOURCE = "data/district_contests_2024_lines/congressional_president_2024.json"
CONGRESSIONAL_2026_CSV = "NC-2026-Congressional-district-statistics 2024 pres.csv"
CONGRESSIONAL_2026_ONLY = {"1", "3"}


def load_helper_namespace() -> dict:
    helper = subprocess.check_output(
        ["git", "show", f"{HELPER_REF}:scripts/apply_targeted_dra_calibration_uploads.py"],
        text=True,
    )
    ns: dict = {}
    exec(compile(helper, "apply_targeted_dra_calibration_uploads.py", "exec"), ns)
    return ns


def write_json(path: Path, payload: dict, *, compact: bool = False) -> None:
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False) if compact else json.dumps(payload, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def update_row_from_shares(row: dict, shares, apportion_votes, calculate_competitiveness) -> None:
    dem_share, rep_share, oth_share = shares
    total_votes = int(row.get("total_votes", 0) or 0)
    if total_votes <= 0:
        total_votes = int(row.get("dem_votes", 0) or 0) + int(row.get("rep_votes", 0) or 0) + int(row.get("other_votes", 0) or 0)
    if total_votes <= 0:
        return

    dem_votes, rep_votes, other_votes = apportion_votes(total_votes, dem_share, rep_share, oth_share)
    margin = rep_votes - dem_votes
    margin_pct = round((margin / total_votes) * 100.0, 2)

    row["dem_votes"] = int(dem_votes)
    row["rep_votes"] = int(rep_votes)
    row["other_votes"] = int(other_votes)
    row["total_votes"] = int(total_votes)
    row["margin"] = int(margin)
    row["margin_pct"] = float(margin_pct)
    row["winner"] = "REP" if rep_votes > dem_votes else ("DEM" if dem_votes > rep_votes else "TIE")
    row["competitiveness"] = {"color": calculate_competitiveness(margin_pct)}


def main() -> None:
    ns = load_helper_namespace()
    csv_data = ns["CSV_DATA"]
    load_stats_from_text = ns["load_stats_from_text"]
    normalize_district_id = ns["normalize_district_id"]
    apportion_votes = ns["apportion_votes"]
    calculate_competitiveness = ns["calculate_competitiveness"]

    # Keep the default 2022/MQP files on their pre-CSV-calibration baseline until real 2022-line CSVs exist.
    subprocess.run(["git", "checkout", PRE_CALIBRATION_REF, "--", *DEFAULT_2022_LINE_TARGETS], check=True)

    repaired = {"restored_default_2022_lines": DEFAULT_2022_LINE_TARGETS, "calibrated_2024_lines": [], "repaired_2026_congressional": {}}

    for target, csv_name in LEGISLATIVE_2024_LINE_TARGETS:
        payload = json.loads(Path(target).read_text(encoding="utf-8"))
        stats = load_stats_from_text(csv_name, csv_data[csv_name])
        touched = []
        for district, row in payload["general"]["results"].items():
            district_id = normalize_district_id(district)
            if district_id in stats:
                update_row_from_shares(row, stats[district_id], apportion_votes, calculate_competitiveness)
                touched.append(district_id)
        write_json(Path(target), payload, compact=("state_senate" in target))
        repaired["calibrated_2024_lines"].append({"target": target, "csv": csv_name, "districts": len(touched)})

    target = json.loads(Path(CONGRESSIONAL_2026_TARGET).read_text(encoding="utf-8"))
    source = json.loads(Path(CONGRESSIONAL_2024_SOURCE).read_text(encoding="utf-8"))
    stats = load_stats_from_text(CONGRESSIONAL_2026_CSV, csv_data[CONGRESSIONAL_2026_CSV])
    copied = []
    recalibrated = []
    for district, row in list(target["general"]["results"].items()):
        district_id = normalize_district_id(district)
        if district_id in CONGRESSIONAL_2026_ONLY:
            update_row_from_shares(row, stats[district_id], apportion_votes, calculate_competitiveness)
            recalibrated.append(district_id)
        else:
            target["general"]["results"][district] = copy.deepcopy(source["general"]["results"][district])
            copied.append(district_id)
    write_json(Path(CONGRESSIONAL_2026_TARGET), target, compact=False)
    repaired["repaired_2026_congressional"] = {"copied_from_2024_lines": copied, "recalibrated_2026_lines": recalibrated}

    print(json.dumps(repaired, indent=2))


if __name__ == "__main__":
    main()
