"""
Generate diagnostics for unresolved precinct keys when mapping election data
to the precinct crosswalk keyspace.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from build_district_results_2024_lines import (
    build_precinct_alias_index,
    enrich_alias_index_from_vtd,
    resolve_precinct_key,
)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    data_dir = root / "data"
    in_json = data_dir / "nc_elections_aggregated.json"
    voting_geojson = data_dir / "Voting_Precincts.geojson"
    vtd_2008 = data_dir / "census" / "tl_2008_37_vtd00_merged.geojson"
    vtd_2012 = data_dir / "census" / "tl_2012_37_vtd10" / "tl_2012_37_vtd10.shp"
    vtd_2020 = data_dir / "tl_2020_37_vtd20" / "tl_2020_37_vtd20.shp"
    if not vtd_2020.exists():
        vtd_2020 = data_dir / "census" / "tl_2020_37_vtd20" / "tl_2020_37_vtd20.shp"
    out_dir = data_dir / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    src = json.load(open(in_json, "r", encoding="utf-8"))
    alias_index = build_precinct_alias_index(voting_geojson)
    enrich_alias_index_from_vtd(
        alias_index,
        vtd_path=vtd_2008,
        county_col="COUNTYFP00",
        code_col="VTDST00",
        name_col="NAME00",
    )
    enrich_alias_index_from_vtd(
        alias_index,
        vtd_path=vtd_2012,
        county_col="COUNTYFP10",
        code_col="VTDST10",
        name_col="NAME10",
    )
    enrich_alias_index_from_vtd(
        alias_index,
        vtd_path=vtd_2020,
        county_col="COUNTYFP20",
        code_col="VTDST20",
        name_col="NAME20",
    )

    summary_rows = []
    unresolved_counter: dict[tuple[str, str], Counter] = defaultdict(Counter)

    for year, year_data in src.get("results_by_year", {}).items():
        year_status = Counter()
        year_total = 0
        for office_key, office_data in year_data.items():
            results = office_data.get("general", {}).get("results", {})
            for precinct_key in results.keys():
                year_total += 1
                resolved, status = resolve_precinct_key(str(precinct_key), alias_index)
                year_status[status] += 1
                if not resolved:
                    unresolved_counter[(year, status)][str(precinct_key).strip().upper()] += 1

        matched = year_status.get("matched", 0)
        summary_rows.append(
            {
                "year": year,
                "total_precinct_keys": year_total,
                "matched": matched,
                "matched_pct": round((matched / year_total * 100.0), 2) if year_total else 0.0,
                "unmatched": year_status.get("unmatched", 0),
                "ambiguous": year_status.get("ambiguous", 0),
                "non_geographic": year_status.get("non_geographic", 0),
                "no_county": year_status.get("no_county", 0),
                "bad_key": year_status.get("bad_key", 0),
            }
        )

    summary_csv = out_dir / "unmatched_precinct_summary.csv"
    with open(summary_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "year",
                "total_precinct_keys",
                "matched",
                "matched_pct",
                "unmatched",
                "ambiguous",
                "non_geographic",
                "no_county",
                "bad_key",
            ],
        )
        writer.writeheader()
        writer.writerows(sorted(summary_rows, key=lambda r: r["year"]))

    examples_csv = out_dir / "unmatched_precinct_examples.csv"
    with open(examples_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["year", "status", "precinct_key", "count"])
        for (year, status), counter in sorted(unresolved_counter.items()):
            for precinct_key, count in counter.most_common(500):
                writer.writerow([year, status, precinct_key, count])

    print(f"Wrote {summary_csv}")
    print(f"Wrote {examples_csv}")


if __name__ == "__main__":
    main()
