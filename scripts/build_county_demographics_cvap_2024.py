"""Build North Carolina county CVAP demographics from the official Census special tabulation.

Input is County.csv from the Census Bureau's 2020-2024 ACS CVAP CSV bundle:
https://www2.census.gov/programs-surveys/decennial/rdo/datasets/2024/2024-cvap/
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


LINE_TO_GROUP = {
    3: "native",
    4: "asian",
    5: "black",
    6: "pacific",
    7: "white",
    12: "multiracial",
    13: "hispanic",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("county_csv", type=Path, help="County.csv from the official Census CVAP bundle")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/county_demographics_2020_2024_cvap.json"),
    )
    return parser.parse_args()


def as_int(value: str) -> int:
    return int(float(value or 0))


def main() -> int:
    args = parse_args()
    counties: dict[str, dict[str, object]] = {}

    with args.county_csv.open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            geoid = (row.get("geoid") or "").strip()
            if not geoid.startswith("0500000US37"):
                continue
            county_geoid = geoid[-5:]
            county_name = (row.get("geoname") or "").split(",", 1)[0].removesuffix(" County")
            county_key = county_name.upper()
            line = as_int(row.get("lnnumber") or "0")
            record = counties.setdefault(
                county_key,
                {"county": county_name, "county_geoid": county_geoid},
            )
            if line == 1:
                record["cvap_total"] = as_int(row["cvap_est"])
                record["cvap_total_moe"] = as_int(row["cvap_moe"])
            elif line in LINE_TO_GROUP:
                group = LINE_TO_GROUP[line]
                record[f"{group}_cvap"] = as_int(row["cvap_est"])
                record[f"{group}_cvap_moe"] = as_int(row["cvap_moe"])

    for record in counties.values():
        total = int(record.get("cvap_total", 0))
        for group in LINE_TO_GROUP.values():
            estimate = int(record.get(f"{group}_cvap", 0))
            record[f"{group}_cvap_pct"] = round(estimate / total * 100, 2) if total else 0.0

    payload = {
        "source": "2020-2024 ACS CVAP Special Tabulation",
        "source_url": "https://www.census.gov/programs-surveys/decennial-census/about/voting-rights/cvap/2020-2024-CVAP.html",
        "release_date": "2026-01-30",
        "geography_reference_date": "2024-01-01",
        "notes": [
            "All displayed race and ethnicity shares use citizen voting age population (CVAP), not total population.",
            "Race categories are non-Hispanic; Hispanic or Latino is a separate, mutually exclusive category.",
            "Estimates and margins of error come directly from the Census Bureau county tabulation.",
        ],
        "counties": dict(sorted(counties.items())),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(counties)} NC counties -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
