from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


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
    try:
        return str(int(float(v)))
    except ValueError:
        return v


def build_whole_county_map(
    crosswalk_csv: Path,
    *,
    threshold: float,
) -> dict[str, str]:
    county_intersections: dict[tuple[str, str], float] = defaultdict(float)
    county_total_area: dict[str, float] = defaultdict(float)
    district_total_area: dict[str, float] = defaultdict(float)
    county_precinct_area: dict[tuple[str, str], float] = {}

    with crosswalk_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            precinct_key = str(row.get("precinct_key", "")).strip().upper()
            if " - " not in precinct_key:
                continue
            county_name, _ = precinct_key.split(" - ", 1)
            district_id = normalize_district_id(row.get("district", ""))
            if not district_id:
                continue

            intersection_area = float(row.get("intersect_area_m2", 0) or 0)
            precinct_area = float(row.get("precinct_area_m2", 0) or 0)
            county_intersections[(county_name, district_id)] += intersection_area
            district_total_area[district_id] += intersection_area
            county_precinct_area[(county_name, precinct_key)] = precinct_area

    for (county_name, _), precinct_area in county_precinct_area.items():
        county_total_area[county_name] += precinct_area

    out: dict[str, str] = {}
    for (county_name, district_id), intersection_area in county_intersections.items():
        total_county = county_total_area.get(county_name, 0.0)
        total_district = district_total_area.get(district_id, 0.0)
        if total_county <= 0 or total_district <= 0:
            continue
        county_cover_pct = intersection_area / total_county
        district_cover_pct = intersection_area / total_district
        if county_cover_pct >= threshold and district_cover_pct >= threshold:
            out[district_id] = county_name
    return out


def aggregate_county_contest_totals_from_json(
    src_path: Path,
    *,
    year: str,
    office: str,
) -> dict[str, dict[str, int]]:
    payload = json.loads(src_path.read_text(encoding="utf-8"))
    results = payload.get("results_by_year", {}).get(str(year), {}).get(office, {}).get("general", {}).get("results", {})
    if not isinstance(results, dict):
        raise ValueError(f"Could not find contest results for year={year}, office={office}")
    out: dict[str, dict[str, int]] = {}
    for key, row in results.items():
        if not isinstance(row, dict):
            continue
        county = str(key).split(" - ", 1)[0].strip().upper()
        if not county:
            continue
        bucket = out.setdefault(county, {"dem_votes": 0, "rep_votes": 0, "other_votes": 0, "total_votes": 0})
        bucket["dem_votes"] += int(row.get("dem_votes", 0) or 0)
        bucket["rep_votes"] += int(row.get("rep_votes", 0) or 0)
        bucket["other_votes"] += int(row.get("other_votes", 0) or 0)
        bucket["total_votes"] += int(row.get("total_votes", 0) or 0)
    return out


def aggregate_county_contest_totals_from_raw_csv(
    raw_csv: Path,
    *,
    office_name: str,
) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    with raw_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if str(row.get("office", "")).strip() != office_name:
                continue
            county = str(row.get("county", "")).strip().upper()
            if not county:
                continue
            party = str(row.get("party", "")).strip().upper()
            votes = int(float(row.get("votes", 0) or 0))
            bucket = out.setdefault(county, {"dem_votes": 0, "rep_votes": 0, "other_votes": 0, "total_votes": 0})
            if party == "DEM":
                bucket["dem_votes"] += votes
            elif party == "REP":
                bucket["rep_votes"] += votes
            else:
                bucket["other_votes"] += votes
            bucket["total_votes"] += votes
    return out


def enforce_county_totals(
    contest_json: Path,
    district_to_county: dict[str, str],
    county_totals: dict[str, dict[str, int]],
) -> dict[str, object]:
    raw_text = contest_json.read_text(encoding="utf-8")
    payload = json.loads(raw_text)
    results = payload.get("general", {}).get("results", {})
    if not isinstance(results, dict):
        raise ValueError(f"Unexpected contest JSON shape: {contest_json}")

    updated: list[dict[str, object]] = []
    missing_counties: list[str] = []
    missing_districts: list[str] = []

    for district_id, county_name in sorted(district_to_county.items(), key=lambda kv: int(kv[0])):
        row = results.get(district_id)
        if not isinstance(row, dict):
            missing_districts.append(district_id)
            continue
        totals = county_totals.get(county_name)
        if not totals:
            missing_counties.append(county_name)
            continue

        dem_votes = int(totals["dem_votes"])
        rep_votes = int(totals["rep_votes"])
        other_votes = int(totals["other_votes"])
        total_votes = int(totals["total_votes"])
        margin = rep_votes - dem_votes
        margin_pct = round((margin / total_votes) * 100.0, 2) if total_votes else 0.0
        winner = "REP" if rep_votes > dem_votes else ("DEM" if dem_votes > rep_votes else "TIE")

        row["dem_votes"] = dem_votes
        row["rep_votes"] = rep_votes
        row["other_votes"] = other_votes
        row["total_votes"] = total_votes
        row["margin"] = margin
        row["margin_pct"] = margin_pct
        row["winner"] = winner
        if isinstance(row.get("competitiveness"), dict):
            row["competitiveness"]["color"] = calculate_competitiveness(margin_pct)
        else:
            row["competitiveness"] = {"color": calculate_competitiveness(margin_pct)}

        updated.append(
            {
                "district": district_id,
                "county": county_name,
                "dem_votes": dem_votes,
                "rep_votes": rep_votes,
                "other_votes": other_votes,
                "margin_pct": margin_pct,
            }
        )

    was_pretty = ("\n" in raw_text.strip()) and (len(raw_text.strip().splitlines()) > 1)
    if was_pretty:
        out_text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    else:
        out_text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    contest_json.write_text(out_text, encoding="utf-8")

    return {
        "contest_json": str(contest_json),
        "updated_count": len(updated),
        "updated": updated,
        "missing_counties": sorted(set(missing_counties)),
        "missing_districts": sorted(set(missing_districts), key=lambda v: int(v)),
    }


def parse_target(raw: str) -> tuple[Path, Path, Path, str]:
    parts = [p.strip().strip("\"") for p in raw.split("|")]
    if len(parts) != 4:
        raise ValueError(
            "--target must be contest_json|crosswalk_csv|raw_csv|raw_office_name"
        )
    contest_json = Path(parts[0])
    crosswalk_csv = Path(parts[1])
    raw_csv = Path(parts[2])
    raw_office_name = parts[3]
    if not contest_json.exists():
        raise FileNotFoundError(f"Missing contest JSON: {contest_json}")
    if not crosswalk_csv.exists():
        raise FileNotFoundError(f"Missing crosswalk CSV: {crosswalk_csv}")
    if not raw_csv.exists():
        raise FileNotFoundError(f"Missing raw CSV: {raw_csv}")
    return contest_json, crosswalk_csv, raw_csv, raw_office_name


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Force whole-county districts to match exact county contest totals."
    )
    parser.add_argument("--target", action="append", required=True)
    parser.add_argument("--threshold", type=float, default=0.999)
    args = parser.parse_args()

    summaries = []

    for raw_target in args.target:
        contest_json, crosswalk_csv, raw_csv, raw_office_name = parse_target(raw_target)
        district_to_county = build_whole_county_map(
            crosswalk_csv,
            threshold=args.threshold,
        )
        county_totals = aggregate_county_contest_totals_from_raw_csv(raw_csv, office_name=raw_office_name)
        summary = enforce_county_totals(contest_json, district_to_county, county_totals)
        summary["whole_county_districts_found"] = len(district_to_county)
        summary["district_to_county"] = district_to_county
        summaries.append(summary)

    print(json.dumps({"updated": summaries}, indent=2))


if __name__ == "__main__":
    main()
