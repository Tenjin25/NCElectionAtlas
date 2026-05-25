from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    src_path = root / "data" / "nc_elections_aggregated.json"
    data = json.loads(src_path.read_text(encoding="utf-8"))

    y2020 = data.get("results_by_year", {}).get("2020", {})
    if not isinstance(y2020, dict):
        raise RuntimeError("Missing results_by_year['2020'] in nc_elections_aggregated.json")

    # Approximation: Union precincts 0044/0045 were created in 2023.
    # For 2020 views, use stable proxy precincts so these geographies populate:
    #   0044 -> 020A (Millbridge carved from 020A)
    #   0045 -> 020B (0045 carved mostly from 020B + part of 019)
    proxy_map = {
        "UNION - 044": "UNION - 020A",
        "UNION - 045": "UNION - 020B",
    }

    inserted = 0
    scanned = 0
    for _office_key, office_data in y2020.items():
        general = office_data.get("general", {})
        results = general.get("results", {})
        if not isinstance(results, dict):
            continue
        scanned += 1
        for target_key, source_key in proxy_map.items():
            if target_key in results:
                continue
            if source_key in results:
                # Deep copy candidate map/value map as plain JSON object.
                results[target_key] = json.loads(json.dumps(results[source_key]))
                inserted += 1

    src_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"Scanned 2020 offices: {scanned}")
    print(f"Inserted proxy precinct result entries: {inserted}")


if __name__ == "__main__":
    main()
