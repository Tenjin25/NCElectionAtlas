"""
Build data/nc_elections_aggregated.json from OpenElections-style CSV files
stored in year folders (for example: data/2024/20241105__nc__general__precinct.csv).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


OFFICE_KEY_MAP = {
    "US PRESIDENT": "president",
    "US SENATE": "us_senate",
    "NC GOVERNOR": "governor",
    "NC LIEUTENANT GOVERNOR": "lieutenant_governor",
    "NC ATTORNEY GENERAL": "attorney_general",
    "NC AUDITOR": "auditor",
    "NC COMMISSIONER OF AGRICULTURE": "agriculture_commissioner",
    "NC COMMISSIONER OF LABOR": "labor_commissioner",
    "NC COMMISSIONER OF INSURANCE": "insurance_commissioner",
    "NC SECRETARY OF STATE": "secretary_of_state",
    "NC TREASURER": "treasurer",
    "NC SUPERINTENDENT OF PUBLIC INSTRUCTION": "superintendent",
}


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


def process_file(csv_path: Path, year: str) -> dict[str, dict]:
    print(f"Processing {csv_path} (year {year})...")
    df = pd.read_csv(csv_path, low_memory=False)
    df = df[df["office"].isin(OFFICE_KEY_MAP.keys())].copy()
    if df.empty:
        print("  No targeted statewide offices found in this file.")
        return {}

    year_results: dict[str, dict] = {}
    for office_name, office_df in df.groupby("office"):
        office_key = OFFICE_KEY_MAP[office_name]
        grouped = office_df.groupby(["county", "precinct"])
        precinct_results: dict[str, dict] = {}

        for (county, precinct), group in grouped:
            dem_votes = int(group.loc[group["party"] == "DEM", "votes"].sum())
            rep_votes = int(group.loc[group["party"] == "REP", "votes"].sum())
            other_votes = int(group.loc[~group["party"].isin(["DEM", "REP"]), "votes"].sum())
            total_votes = dem_votes + rep_votes + other_votes
            margin = rep_votes - dem_votes
            margin_pct = (margin / total_votes * 100) if total_votes else 0.0
            winner = "REP" if margin > 0 else "DEM" if margin < 0 else "TIE"

            dem_candidate = ""
            rep_candidate = ""
            dem_rows = group.loc[group["party"] == "DEM", "candidate"]
            rep_rows = group.loc[group["party"] == "REP", "candidate"]
            if not dem_rows.empty:
                dem_candidate = str(dem_rows.iloc[0])
            if not rep_rows.empty:
                rep_candidate = str(rep_rows.iloc[0])

            precinct_key = f"{county} - {precinct}"
            precinct_results[precinct_key] = {
                "dem_votes": dem_votes,
                "rep_votes": rep_votes,
                "other_votes": other_votes,
                "total_votes": total_votes,
                "dem_candidate": dem_candidate,
                "rep_candidate": rep_candidate,
                "margin": margin,
                "margin_pct": round(margin_pct, 2),
                "winner": winner,
                "competitiveness": {"color": calculate_competitiveness(margin_pct)},
            }

        year_results[office_key] = {"general": {"results": precinct_results}}
        print(f"  {office_name} -> {office_key}: {len(precinct_results)} precincts")

    return year_results


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    data_dir = root / "data"
    csv_files = sorted(data_dir.glob("*/**/*__nc__general__precinct.csv"))

    if not csv_files:
        raise FileNotFoundError("No general election CSV files found under data/<year>/")

    aggregated: dict[str, dict] = {"results_by_year": {}}
    for csv_path in csv_files:
        year = csv_path.parent.name
        if not year.isdigit():
            year = csv_path.stem[:4]
        if not year.isdigit():
            print(f"Skipping file with unknown year folder: {csv_path}")
            continue

        year_data = process_file(csv_path, year)
        if not year_data:
            continue

        if year not in aggregated["results_by_year"]:
            aggregated["results_by_year"][year] = {}
        aggregated["results_by_year"][year].update(year_data)

    output_path = data_dir / "nc_elections_aggregated.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(aggregated, f, indent=2)

    print(f"\nWrote {output_path}")
    for year in sorted(aggregated["results_by_year"].keys()):
        offices = sorted(aggregated["results_by_year"][year].keys())
        print(f"{year}: {len(offices)} offices ({', '.join(offices)})")


if __name__ == "__main__":
    main()
