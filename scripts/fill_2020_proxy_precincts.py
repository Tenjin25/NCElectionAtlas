from __future__ import annotations

import json
from pathlib import Path


PROXY_MAP: dict[str, str] = {
    # Union (new precinct IDs after 2020)
    "UNION - 044": "UNION - 020A",
    "UNION - 045": "UNION - 020B",
    "UNION - 0005": "UNION - 005",
    "UNION - 0019": "UNION - 019",
    "UNION - 0020A": "UNION - 020A",
    "UNION - 0030": "UNION - 030",
    # Additional high-confidence county mappings (single clear parent key)
    "ALAMANCE - 03SE": "ALAMANCE - 03S",
    "ALAMANCE - 03SM": "ALAMANCE - 03S",
    "CUMBERLAND - AL51-1": "CUMBERLAND - AL51",
    "CUMBERLAND - AL51-2": "CUMBERLAND - AL51",
    "CUMBERLAND - AL51-3": "CUMBERLAND - AL51",
    "CUMBERLAND - G3A-2C": "CUMBERLAND - G3A-2",
    "CUMBERLAND - G9A-3": "CUMBERLAND - G9A",
    "DURHAM - 33-1": "DURHAM - 33",
    "DURHAM - 33-2": "DURHAM - 33",
    "GASTON - 04-1": "GASTON - 04",
    "GASTON - 06-1": "GASTON - 06",
    "GASTON - 14-1": "GASTON - 14",
    "GASTON - 18-1": "GASTON - 18",
    "GASTON - 19-1": "GASTON - 19",
    "GASTON - 21-1": "GASTON - 21",
    "GASTON - 25-1": "GASTON - 25",
    "GASTON - 26-1": "GASTON - 26",
    "GASTON - 28-1": "GASTON - 28",
    "GASTON - 29-1": "GASTON - 29",
    "GASTON - 30-1": "GASTON - 30",
    "GASTON - 32-1": "GASTON - 32",
    "IREDELL - BA-1": "IREDELL - BA",
    "IREDELL - CC3-1": "IREDELL - CC3",
    "IREDELL - CC4-1": "IREDELL - CC4",
    "IREDELL - DV1A1A": "IREDELL - DV1-A",
    "IREDELL - DV1B-1": "IREDELL - DV1-B",
    "IREDELL - DV2A-1": "IREDELL - DV2-A",
    "IREDELL - DV2B-1": "IREDELL - DV2-B",
    "MARTIN - GRF": "MARTIN - GR",
    "MARTIN - HMT": "MARTIN - HM",
    "MOORE - PHB1A": "MOORE - PHB1",
    "ORANGE - HN": "ORANGE - H",
    "WILKES - 120A": "WILKES - 120",
    "WILKES - 123A": "WILKES - 123",
    # Wake (2020-on-current-geometry gaps; nearest predecessor approximation)
    "WAKE - 03-01": "WAKE - 03-00",
    "WAKE - 03-02": "WAKE - 03-00",
    "WAKE - 06-11": "WAKE - 06-10",
    "WAKE - 06-12": "WAKE - 06-10",
    "WAKE - 10-05": "WAKE - 10-04",
    "WAKE - 10-06": "WAKE - 10-04",
    "WAKE - 12-10": "WAKE - 12-09",
    "WAKE - 12-11": "WAKE - 12-09",
    "WAKE - 17-14": "WAKE - 17-13",
    "WAKE - 17-15": "WAKE - 17-13",
    "WAKE - 19-22": "WAKE - 19-21",
    "WAKE - 19-23": "WAKE - 19-21",
}


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    src_path = root / "data" / "nc_elections_aggregated.json"
    data = json.loads(src_path.read_text(encoding="utf-8"))

    y2020 = data.get("results_by_year", {}).get("2020", {})
    if not isinstance(y2020, dict):
        raise RuntimeError("Missing results_by_year['2020'] in nc_elections_aggregated.json")

    inserted = 0
    scanned = 0
    for office_data in y2020.values():
        results = office_data.get("general", {}).get("results", {})
        if not isinstance(results, dict):
            continue
        scanned += 1
        for target_key, source_key in PROXY_MAP.items():
            if target_key in results:
                continue
            if source_key in results:
                results[target_key] = json.loads(json.dumps(results[source_key]))
                inserted += 1

    src_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"Scanned 2020 offices: {scanned}")
    print(f"Inserted proxy precinct result entries: {inserted}")


if __name__ == "__main__":
    main()
