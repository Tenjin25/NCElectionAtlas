"""Build direct U.S. House results for the congressional map's matching line sets.

The 2022 and 2024 general-election precinct exports identify the congressional
district in each U.S. House office label.  Because each election is displayed
on its own contemporaneous district lines, these results can be summed directly
by that district instead of being reallocated through a crosswalk.
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOUSE_OFFICE = re.compile(r"^US HOUSE OF REPRESENTATIVES DISTRICT\s*0*(\d+)", re.I)


def build(year: int, source: Path, output_dir: Path) -> None:
    votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    candidates: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    with source.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            match = HOUSE_OFFICE.match((row.get("office") or "").strip())
            if not match:
                continue
            district = str(int(match.group(1)))
            party = (row.get("party") or "").strip().upper()
            bucket = party if party in {"DEM", "REP"} else "OTHER"
            try:
                count = int(float(row.get("votes") or 0))
            except ValueError:
                continue
            votes[district][bucket] += count
            candidate = (row.get("candidate") or "").strip()
            if candidate:
                candidates[district][bucket][candidate] += count

    results = {}
    for district in sorted(votes, key=int):
        dem = votes[district]["DEM"]
        rep = votes[district]["REP"]
        other = votes[district]["OTHER"]
        total = dem + rep + other
        margin = rep - dem
        results[district] = {
            "dem_votes": dem,
            "rep_votes": rep,
            "other_votes": other,
            "total_votes": total,
            "dem_candidate": max(candidates[district]["DEM"], key=candidates[district]["DEM"].get, default=""),
            "rep_candidate": max(candidates[district]["REP"], key=candidates[district]["REP"].get, default=""),
            "margin": margin,
            "margin_pct": round((margin / total * 100) if total else 0, 2),
            "winner": "REP" if margin > 0 else "DEM" if margin < 0 else "TIE",
        }

    payload = {
        "year": year,
        "scope": "congressional",
        "contest_type": "us_house",
        "meta": {
            "source": "ncsbe_precinct_sort_direct_district_sum",
            "office": "US HOUSE OF REPRESENTATIVES",
            "district_lines_year": year,
            "district_lines_label": f"{year} lines",
        },
        "general": {"results": results},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"congressional_us_house_{year}.json"
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"files": []}
    files = [entry for entry in manifest.get("files", []) if not (
        entry.get("scope") == "congressional"
        and entry.get("contest_type") == "us_house"
        and int(entry.get("year", 0)) == year
    )]
    files.append({
        "year": year,
        "scope": "congressional",
        "contest_type": "us_house",
        "file": output.name,
        "districts": len(results),
        "district_lines_year": year,
        "district_lines_label": f"{year} lines",
    })
    files.sort(key=lambda entry: (entry.get("year", 0), entry.get("scope", ""), entry.get("contest_type", "")))
    manifest_path.write_text(json.dumps({"files": files}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output} ({len(results)} districts)")


if __name__ == "__main__":
    build(2022, ROOT / "data/2022/20221108__nc__general__precinct.csv", ROOT / "data/district_contests")
    build(2024, ROOT / "data/2024/20241105__nc__general__precinct.csv", ROOT / "data/district_contests_2024_lines")
