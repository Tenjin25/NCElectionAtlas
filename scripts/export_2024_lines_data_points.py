#!/usr/bin/env python3
from __future__ import annotations

"""
Export district-level "data points" on 2024 NC district lines to a long CSV.

By default this reads slices from:
  1) data/district_contests_2024_lines
  2) data/district_contests_2020_2024 (fallback for extra years/contests)

If the same (scope, contest_type, year) exists in multiple directories, the
first directory wins.
"""

import argparse
import csv
import json
import re
from pathlib import Path


VALID_SCOPES = {"congressional", "state_house", "state_senate"}
DEFAULT_INPUT_DIRS = [
    Path("data/district_contests_2024_lines"),
    Path("data/district_contests_2020_2024"),
]
DEFAULT_OUT_CSV = Path("data/tmp/exports/district_data_points_2024_lines.csv")


def parse_scopes(raw: str) -> set[str]:
    values = {s.strip() for s in str(raw or "").split(",") if s.strip()}
    if not values:
        return set(VALID_SCOPES)
    bad = sorted(values - VALID_SCOPES)
    if bad:
        raise ValueError(f"Invalid scope(s): {', '.join(bad)}")
    return values


def parse_years(raw: str) -> set[int]:
    vals = set()
    for part in str(raw or "").split(","):
        token = part.strip()
        if not token:
            continue
        vals.add(int(token))
    return vals


def to_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        return default


def to_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_slice_filename(path: Path) -> tuple[str, str, int] | None:
    if path.suffix.lower() != ".json":
        return None
    stem = path.stem
    parts = stem.split("_")
    if len(parts) < 3:
        return None

    if parts[0] == "state" and len(parts) >= 4:
        scope = "_".join(parts[:2])
        contest_type = "_".join(parts[2:-1])
    else:
        scope = parts[0]
        contest_type = "_".join(parts[1:-1])

    if scope not in VALID_SCOPES or not contest_type:
        return None
    try:
        year = int(parts[-1])
    except ValueError:
        return None
    return scope, contest_type, year


def discover_slices(directory: Path) -> list[dict]:
    entries: list[dict] = []
    manifest = directory / "manifest.json"
    if manifest.exists():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            files = payload.get("files", [])
            if isinstance(files, list):
                for item in files:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("file") or "").strip()
                    if not name:
                        continue
                    p = directory / name
                    if not p.exists():
                        continue
                    scope = str(item.get("scope") or "").strip()
                    contest_type = str(item.get("contest_type") or "").strip()
                    year = item.get("year")
                    if not scope or not contest_type or year is None:
                        parsed = parse_slice_filename(p)
                        if not parsed:
                            continue
                        scope, contest_type, year = parsed
                    try:
                        year_int = int(year)
                    except (TypeError, ValueError):
                        continue
                    if scope not in VALID_SCOPES:
                        continue
                    entries.append(
                        {
                            "scope": scope,
                            "contest_type": contest_type,
                            "year": year_int,
                            "path": p,
                        }
                    )
        except json.JSONDecodeError:
            # Fall through to glob-based discovery.
            pass

    if entries:
        return entries

    for p in sorted(directory.glob("*.json")):
        if p.name.lower() == "manifest.json":
            continue
        parsed = parse_slice_filename(p)
        if not parsed:
            continue
        scope, contest_type, year = parsed
        entries.append(
            {
                "scope": scope,
                "contest_type": contest_type,
                "year": year,
                "path": p,
            }
        )
    return entries


def collect_slice_index(
    *,
    input_dirs: list[Path],
    scopes: set[str],
    years: set[int] | None,
    contest_regex: re.Pattern[str] | None,
) -> dict[tuple[str, str, int], Path]:
    selected: dict[tuple[str, str, int], Path] = {}
    for directory in input_dirs:
        if not directory.exists():
            print(f"Skipping missing directory: {directory}")
            continue
        for item in discover_slices(directory):
            scope = item["scope"]
            contest_type = item["contest_type"]
            year = int(item["year"])
            path = Path(item["path"])
            if scope not in scopes:
                continue
            if years is not None and year not in years:
                continue
            if contest_regex is not None and not contest_regex.search(contest_type):
                continue
            key = (scope, contest_type, year)
            if key not in selected:
                selected[key] = path
    return selected


def relpath_str(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def build_rows(slices: dict[tuple[str, str, int], Path]) -> list[dict]:
    rows: list[dict] = []
    for scope, contest_type, year in sorted(slices, key=lambda x: (x[2], x[0], x[1])):
        path = slices[(scope, contest_type, year)]
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        results = (((payload.get("general") or {}).get("results")) or {})
        if not isinstance(results, dict):
            continue

        for district, item in results.items():
            if not isinstance(item, dict):
                continue
            dem_votes = to_int(item.get("dem_votes"), 0)
            rep_votes = to_int(item.get("rep_votes"), 0)
            other_votes = to_int(item.get("other_votes"), 0)
            total_votes = to_int(item.get("total_votes"), dem_votes + rep_votes + other_votes)
            margin_votes = to_int(item.get("margin"), rep_votes - dem_votes)
            margin_pct = to_float(
                item.get("margin_pct"),
                (margin_votes / total_votes * 100.0) if total_votes else 0.0,
            )
            winner = str(item.get("winner") or ("REP" if margin_votes > 0 else "DEM" if margin_votes < 0 else "TIE")).upper()
            if winner not in {"REP", "DEM", "TIE"}:
                winner = "TIE"

            dem_share = (dem_votes / total_votes) if total_votes else 0.0
            rep_share = (rep_votes / total_votes) if total_votes else 0.0
            other_share = (other_votes / total_votes) if total_votes else 0.0

            rows.append(
                {
                    "lines_year": 2024,
                    "scope": scope,
                    "contest_type": contest_type,
                    "year": year,
                    "district": str(district),
                    "dem_votes": dem_votes,
                    "rep_votes": rep_votes,
                    "other_votes": other_votes,
                    "total_votes": total_votes,
                    "dem_share": round(dem_share, 6),
                    "rep_share": round(rep_share, 6),
                    "other_share": round(other_share, 6),
                    "margin_votes": margin_votes,
                    "margin_pct": round(margin_pct, 4),
                    "winner": winner,
                    "match_coverage_pct": to_float(meta.get("match_coverage_pct"), 0.0),
                    "matched_precinct_keys": to_int(meta.get("matched_precinct_keys"), 0),
                    "total_precinct_keys": to_int(meta.get("total_precinct_keys"), 0),
                    "dem_candidate": str(item.get("dem_candidate") or ""),
                    "rep_candidate": str(item.get("rep_candidate") or ""),
                    "source_file": relpath_str(path),
                }
            )

    rows.sort(
        key=lambda r: (
            int(r["year"]),
            str(r["scope"]),
            str(r["contest_type"]),
            int(str(r["district"]).strip().lstrip("0") or "0"),
            str(r["district"]),
        )
    )
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("No rows to write.")

    fieldnames = [
        "lines_year",
        "scope",
        "contest_type",
        "year",
        "district",
        "dem_votes",
        "rep_votes",
        "other_votes",
        "total_votes",
        "dem_share",
        "rep_share",
        "other_share",
        "margin_votes",
        "margin_pct",
        "winner",
        "match_coverage_pct",
        "matched_precinct_keys",
        "total_precinct_keys",
        "dem_candidate",
        "rep_candidate",
        "source_file",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows: list[dict]) -> None:
    by_scope: dict[str, int] = {}
    by_year: dict[int, int] = {}
    contests: set[tuple[str, str, int]] = set()
    for r in rows:
        scope = str(r["scope"])
        year = int(r["year"])
        by_scope[scope] = by_scope.get(scope, 0) + 1
        by_year[year] = by_year.get(year, 0) + 1
        contests.add((scope, str(r["contest_type"]), year))

    print(f"Data points: {len(rows):,}")
    print(f"Unique slices: {len(contests):,}")
    print("Rows by scope:")
    for scope in sorted(by_scope):
        print(f"  {scope}: {by_scope[scope]:,}")
    print("Rows by year:")
    for year in sorted(by_year):
        print(f"  {year}: {by_year[year]:,}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export long-form district data points using 2024 legislative and congressional lines."
    )
    parser.add_argument(
        "--input-dir",
        action="append",
        type=Path,
        help=(
            "Directory containing district contest slices. Repeatable. "
            "Earlier directories take precedence when duplicate slices exist."
        ),
    )
    parser.add_argument(
        "--out-csv",
        type=Path,
        default=DEFAULT_OUT_CSV,
        help=f"Output CSV path (default: {DEFAULT_OUT_CSV})",
    )
    parser.add_argument(
        "--scopes",
        type=str,
        default="congressional,state_house,state_senate",
        help="Comma-separated scopes to include.",
    )
    parser.add_argument(
        "--years",
        type=str,
        default="",
        help="Optional comma-separated year filter (example: 2020,2022,2024).",
    )
    parser.add_argument(
        "--contest-type-regex",
        type=str,
        default="",
        help="Optional regex filter for contest_type (example: '^(president|governor)$').",
    )
    args = parser.parse_args()

    input_dirs = args.input_dir if args.input_dir else DEFAULT_INPUT_DIRS
    scopes = parse_scopes(args.scopes)
    years = parse_years(args.years) if str(args.years).strip() else None
    contest_regex = re.compile(args.contest_type_regex) if str(args.contest_type_regex).strip() else None

    slices = collect_slice_index(
        input_dirs=input_dirs,
        scopes=scopes,
        years=years,
        contest_regex=contest_regex,
    )
    if not slices:
        raise SystemExit("No matching district slices found.")

    rows = build_rows(slices)
    if not rows:
        raise SystemExit("No data points produced from selected slices.")

    write_csv(args.out_csv, rows)
    summarize(rows)
    print(f"Wrote: {args.out_csv}")


if __name__ == "__main__":
    main()

