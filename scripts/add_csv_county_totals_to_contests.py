#!/usr/bin/env python3
"""Add canonical raw-CSV county totals to statewide contest JSON slices."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEST_DIR = ROOT / "data" / "contests"


def norm(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def competitiveness_color(margin_pct: float) -> str:
    absolute = abs(margin_pct)
    rep_win = margin_pct > 0
    if absolute < 0.5:
        return "#f7f7f7"
    if absolute >= 40:
        return "#67000d" if rep_win else "#08306b"
    if absolute >= 30:
        return "#a50f15" if rep_win else "#08519c"
    if absolute >= 20:
        return "#cb181d" if rep_win else "#3182bd"
    if absolute >= 10:
        return "#ef3b2c" if rep_win else "#6baed6"
    if absolute >= 5.5:
        return "#fb6a4a" if rep_win else "#9ecae1"
    if absolute >= 1:
        return "#fcae91" if rep_win else "#c6dbef"
    return "#fee8c8" if rep_win else "#e1f5fe"


def contest_year(path: Path, payload: dict) -> int | None:
    try:
        return int(payload.get("year"))
    except (TypeError, ValueError):
        match = re.search(r"_(\d{4})\.json$", path.name)
        return int(match.group(1)) if match else None


def raw_csv_for_year(year: int) -> Path | None:
    candidates = list((ROOT / "data" / str(year)).glob("*__general__precinct.csv"))
    return max(candidates, key=lambda path: path.stat().st_size) if candidates else None


def load_csv_by_office(path: Path) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            office = norm(row.get("office"))
            if office:
                grouped[office].append(row)
    return grouped


def json_candidate_buckets(rows: list[dict]) -> dict[str, str]:
    buckets: dict[str, str] = {}
    for row in rows:
        dem = norm(row.get("dem_candidate"))
        rep = norm(row.get("rep_candidate"))
        if dem:
            buckets[dem] = "DEM"
        if rep:
            buckets[rep] = "REP"
    return buckets


def choose_office(payload: dict, grouped: dict[str, list[dict[str, str]]]) -> tuple[str | None, str]:
    declared = norm((payload.get("meta") or {}).get("office"))
    if declared in grouped:
        return declared, "meta_exact"

    candidates = set(json_candidate_buckets(payload.get("rows") or []))
    if not candidates:
        return None, "no_json_candidates"

    scored: list[tuple[int, int, str]] = []
    for office, rows in grouped.items():
        raw_candidates = {norm(row.get("candidate")) for row in rows if norm(row.get("candidate"))}
        overlap = len(candidates & raw_candidates)
        if overlap:
            scored.append((overlap, -len(raw_candidates), office))
    if not scored:
        return None, "no_candidate_match"
    scored.sort(reverse=True)
    best = scored[0]
    if len(scored) > 1 and scored[1][:2] == best[:2]:
        return None, "ambiguous_candidate_match"
    return best[2], "candidate_match"


def aggregate_county_totals(payload: dict, raw_rows: list[dict[str, str]]) -> dict[str, dict]:
    candidate_buckets = json_candidate_buckets(payload.get("rows") or [])
    dem_candidate = next((row.get("dem_candidate", "") for row in payload.get("rows") or [] if row.get("dem_candidate")), "")
    rep_candidate = next((row.get("rep_candidate", "") for row in payload.get("rows") or [] if row.get("rep_candidate")), "")
    totals: dict[str, dict] = {}

    for row in raw_rows:
        county = norm(row.get("county"))
        if not county:
            continue
        try:
            votes = int(float(row.get("votes") or 0))
        except (TypeError, ValueError):
            votes = 0
        party = candidate_buckets.get(norm(row.get("candidate")), norm(row.get("party")))
        bucket = "dem_votes" if party.startswith("DEM") else ("rep_votes" if party.startswith("REP") else "other_votes")
        node = totals.setdefault(
            county,
            {
                "dem_votes": 0,
                "rep_votes": 0,
                "other_votes": 0,
                "total_votes": 0,
                "dem_candidate": dem_candidate,
                "rep_candidate": rep_candidate,
            },
        )
        node[bucket] += votes
        node["total_votes"] += votes

    for node in totals.values():
        dem_votes = int(node["dem_votes"])
        rep_votes = int(node["rep_votes"])
        total_votes = int(node["total_votes"])
        margin = rep_votes - dem_votes
        margin_pct = round((margin / total_votes) * 100, 4) if total_votes else 0.0
        node["margin"] = margin
        node["margin_pct"] = margin_pct
        node["winner"] = "REP" if margin > 0 else ("DEM" if margin < 0 else "TIE")
        node["color"] = competitiveness_color(margin_pct)
    return dict(sorted(totals.items()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Write matched county totals into contest JSON files.")
    parser.add_argument("--years", default="", help="Optional comma-separated year filter.")
    args = parser.parse_args()
    year_filter = {int(value) for value in args.years.split(",") if value.strip()} if args.years else None

    csv_cache: dict[int, tuple[Path, dict[str, list[dict[str, str]]]]] = {}
    summary = {"matched": [], "skipped": [], "changed": []}

    for path in sorted(CONTEST_DIR.glob("*.json")):
        if path.name == "manifest.json":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        year = contest_year(path, payload)
        if year is None or (year_filter and year not in year_filter):
            continue
        if year not in csv_cache:
            csv_path = raw_csv_for_year(year)
            if csv_path is None:
                csv_cache[year] = (Path(), {})
            else:
                csv_cache[year] = (csv_path, load_csv_by_office(csv_path))
        csv_path, grouped = csv_cache[year]
        if not grouped:
            summary["skipped"].append({"file": path.name, "reason": "missing_csv"})
            continue

        office, method = choose_office(payload, grouped)
        if not office:
            summary["skipped"].append({"file": path.name, "reason": method})
            continue
        county_totals = aggregate_county_totals(payload, grouped[office])
        if len(county_totals) != 100:
            summary["skipped"].append({"file": path.name, "reason": f"county_count_{len(county_totals)}", "office": office})
            continue

        summary["matched"].append({"file": path.name, "office": office, "method": method})
        if payload.get("county_totals") == county_totals:
            continue
        summary["changed"].append(path.name)
        if args.write:
            output = {key: value for key, value in payload.items() if key not in {"county_totals", "rows"}}
            output["county_totals"] = county_totals
            output["rows"] = payload.get("rows") or []
            path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "write": args.write,
        "matched_count": len(summary["matched"]),
        "changed_count": len(summary["changed"]),
        "skipped_count": len(summary["skipped"]),
        **summary,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
