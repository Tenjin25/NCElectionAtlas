"""
Calibrate district contest JSON slices to DRA-style district statistics CSV shares.

For each district row in a target slice:
  - keep total_votes fixed
  - rebalance dem/rep/other votes to match CSV Dem/Rep/Oth proportions
  - recompute margin, margin_pct, winner, and competitiveness color

Usage:
  python scripts/calibrate_district_slices_from_stats_csv.py ^
    --map data/district_contests/state_house_president_2020.json=\"data/district-statistics 2020 Pres State House 2022.csv\" ^
    --map data/district_contests/state_house_president_2024.json=\"data/district-statistics 2024 Pres State House 2022.csv\"

Formatting:
  By default this script preserves the target JSON's formatting style (pretty vs minified).
  Use --format pretty/minify to force an output style.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, Tuple


def calculate_competitiveness(margin_pct: float) -> str:
    abs_margin = abs(margin_pct)
    if abs_margin < 0.5:
        return "#f7f7f7"
    rep_win = margin_pct > 0
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


def normalize_district_id(raw: str) -> str:
    v = str(raw or "").strip().strip("\"")
    if not v:
        return ""
    if v.upper() == "UN":
        return ""
    try:
        return str(int(float(v)))
    except ValueError:
        return v


def load_stats(path: Path) -> Dict[str, Tuple[float, float, float]]:
    out: Dict[str, Tuple[float, float, float]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            district = normalize_district_id(row.get("ID", ""))
            if not district:
                continue
            try:
                dem = float(row.get("Dem", 0) or 0)
                rep = float(row.get("Rep", 0) or 0)
                oth = float(row.get("Oth", 0) or 0)
            except ValueError:
                continue
            s = dem + rep + oth
            if s <= 0:
                continue
            out[district] = (dem / s, rep / s, oth / s)
    if not out:
        raise ValueError(f"No district share rows loaded from {path}")
    return out


def apportion_votes(total: int, dem_share: float, rep_share: float, oth_share: float) -> tuple[int, int, int]:
    shares = [dem_share, rep_share, oth_share]
    raw = [total * x for x in shares]
    base = [int(x) for x in raw]
    remainder = total - sum(base)
    if remainder > 0:
        frac = [(raw[i] - base[i], i) for i in range(3)]
        frac.sort(key=lambda t: (t[0], -t[1]), reverse=True)
        for _, idx in frac[:remainder]:
            base[idx] += 1
    return base[0], base[1], base[2]


def calibrate_slice(target_json: Path, stats_csv: Path, *, format_mode: str = "auto") -> dict:
    raw_text = target_json.read_text(encoding="utf-8")
    payload = json.loads(raw_text)
    stats = load_stats(stats_csv)

    results = payload.get("general", {}).get("results", {})
    if not isinstance(results, dict):
        raise ValueError(f"Unexpected payload format in {target_json}")

    calibrated = 0
    missing = 0
    max_margin_delta = 0.0
    max_margin_dist = None

    for district, row in results.items():
        district_id = normalize_district_id(district)
        if not district_id or district_id not in stats:
            missing += 1
            continue
        if not isinstance(row, dict):
            continue

        dem_share, rep_share, oth_share = stats[district_id]
        old_dem = int(row.get("dem_votes", 0) or 0)
        old_rep = int(row.get("rep_votes", 0) or 0)
        old_oth = int(row.get("other_votes", 0) or 0)
        total_votes = int(row.get("total_votes", old_dem + old_rep + old_oth) or 0)
        if total_votes <= 0:
            continue

        dem_votes, rep_votes, oth_votes = apportion_votes(total_votes, dem_share, rep_share, oth_share)
        margin = rep_votes - dem_votes
        margin_pct = round((margin / total_votes) * 100.0, 2)
        winner = "REP" if rep_votes > dem_votes else ("DEM" if dem_votes > rep_votes else "TIE")
        color = calculate_competitiveness(margin_pct)

        row["dem_votes"] = int(dem_votes)
        row["rep_votes"] = int(rep_votes)
        row["other_votes"] = int(oth_votes)
        row["total_votes"] = int(total_votes)
        row["margin"] = int(margin)
        row["margin_pct"] = float(margin_pct)
        row["winner"] = winner
        if isinstance(row.get("competitiveness"), dict):
            row["competitiveness"]["color"] = color
        else:
            row["competitiveness"] = {"color": color}

        calibrated += 1

        target_margin_pct = (rep_share - dem_share) * 100.0
        delta = abs(margin_pct - target_margin_pct)
        if delta > max_margin_delta:
            max_margin_delta = delta
            max_margin_dist = district_id

    # Preserve input formatting by default: pretty JSON (multi-line) vs minified (single-line).
    was_pretty = ("\n" in raw_text.strip()) and (len(raw_text.strip().splitlines()) > 1)
    if format_mode == "auto":
        format_mode = "pretty" if was_pretty else "minify"

    if format_mode == "pretty":
        out_text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    elif format_mode == "minify":
        out_text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    else:
        raise ValueError(f"Unexpected format_mode: {format_mode}")

    target_json.write_text(out_text, encoding="utf-8")
    return {
        "target_json": str(target_json),
        "stats_csv": str(stats_csv),
        "calibrated": calibrated,
        "missing_stats_rows": missing,
        "max_margin_delta_pct": round(max_margin_delta, 6),
        "max_margin_delta_district": max_margin_dist,
    }


def parse_map_arg(raw: str) -> tuple[Path, Path]:
    if "=" not in raw:
        raise ValueError(f"--map value must be target_json=stats_csv, got: {raw}")
    left, right = raw.split("=", 1)
    target = Path(left.strip().strip("\""))
    stats = Path(right.strip().strip("\""))
    if not target.exists():
        raise FileNotFoundError(f"Missing target json: {target}")
    if not stats.exists():
        raise FileNotFoundError(f"Missing stats csv: {stats}")
    return target, stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate district contest slices to DRA district stats shares.")
    parser.add_argument(
        "--map",
        action="append",
        required=True,
        help="Mapping of target_json=stats_csv. Repeat for multiple files.",
    )
    parser.add_argument(
        "--format",
        choices=["auto", "pretty", "minify"],
        default="auto",
        help="Output JSON formatting. auto preserves the target file style (default).",
    )
    args = parser.parse_args()

    summaries = []
    for raw in args.map:
        target, stats = parse_map_arg(raw)
        summaries.append(calibrate_slice(target, stats, format_mode=args.format))

    print(json.dumps({"updated": summaries}, indent=2))


if __name__ == "__main__":
    main()
