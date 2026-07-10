import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path


RE_WS = re.compile(r"\s+")


def norm_text(value: object) -> str:
    return RE_WS.sub(" ", str(value or "")).strip().upper()


def precinct_key(props: dict) -> str:
    county = norm_text(props.get("county_nam") or props.get("COUNTYNAME") or props.get("CountyName") or props.get("NAME20") or props.get("NAME"))
    prec = norm_text(props.get("prec_id") or props.get("PREC_ID") or props.get("precinct") or props.get("PRECINCT"))
    if county and prec:
        return f"{county} - {prec}"
    return ""


def feature_props_list(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [feat.get("properties") or {} for feat in payload.get("features", [])]


def build_index(path: Path) -> dict:
    props_list = feature_props_list(path)
    keys = []
    counties = Counter()
    prop_names = set()
    for props in props_list:
        key = precinct_key(props)
        if key:
            keys.append(key)
            county = key.split(" - ", 1)[0]
            counties[county] += 1
        for name in props.keys():
            prop_names.add(str(name))
    return {
        "feature_count": len(props_list),
        "keys": keys,
        "key_set": set(keys),
        "county_counts": counties,
        "prop_names": sorted(prop_names),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two NC precinct polygon GeoJSON files by county and precinct key.")
    parser.add_argument("--old", required=True, help="Baseline GeoJSON path")
    parser.add_argument("--new", required=True, help="New GeoJSON path")
    parser.add_argument("--out-json", required=True, help="Summary JSON output path")
    parser.add_argument("--out-csv", required=True, help="County/precinct diff CSV output path")
    args = parser.parse_args()

    old_path = Path(args.old)
    new_path = Path(args.new)
    out_json = Path(args.out_json)
    out_csv = Path(args.out_csv)

    old = build_index(old_path)
    new = build_index(new_path)

    old_only = sorted(old["key_set"] - new["key_set"])
    new_only = sorted(new["key_set"] - old["key_set"])

    counties = sorted(set(old["county_counts"].keys()) | set(new["county_counts"].keys()))
    county_rows = []
    for county in counties:
        old_count = old["county_counts"].get(county, 0)
        new_count = new["county_counts"].get(county, 0)
        if old_count != new_count:
            county_rows.append(
                {
                    "row_type": "county_count_delta",
                    "county": county,
                    "old_count": old_count,
                    "new_count": new_count,
                    "delta": new_count - old_count,
                    "precinct_key": "",
                }
            )

    for key in old_only:
        county = key.split(" - ", 1)[0]
        county_rows.append(
            {
                "row_type": "removed_precinct",
                "county": county,
                "old_count": "",
                "new_count": "",
                "delta": "",
                "precinct_key": key,
            }
        )

    for key in new_only:
        county = key.split(" - ", 1)[0]
        county_rows.append(
            {
                "row_type": "added_precinct",
                "county": county,
                "old_count": "",
                "new_count": "",
                "delta": "",
                "precinct_key": key,
            }
        )

    summary = {
        "old_path": str(old_path),
        "new_path": str(new_path),
        "old_feature_count": old["feature_count"],
        "new_feature_count": new["feature_count"],
        "feature_delta": new["feature_count"] - old["feature_count"],
        "old_only_props": [p for p in old["prop_names"] if p not in new["prop_names"]],
        "new_only_props": [p for p in new["prop_names"] if p not in old["prop_names"]],
        "removed_precinct_count": len(old_only),
        "added_precinct_count": len(new_only),
        "county_count_deltas": county_rows[: len([r for r in county_rows if r["row_type"] == "county_count_delta"])],
        "removed_precinct_examples": old_only[:50],
        "added_precinct_examples": new_only[:50],
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["row_type", "county", "old_count", "new_count", "delta", "precinct_key"],
        )
        writer.writeheader()
        writer.writerows(county_rows)

    print(f"Wrote {out_json}")
    print(f"Wrote {out_csv}")
    print(
        json.dumps(
            {
                "old_feature_count": old["feature_count"],
                "new_feature_count": new["feature_count"],
                "feature_delta": new["feature_count"] - old["feature_count"],
                "removed_precinct_count": len(old_only),
                "added_precinct_count": len(new_only),
            }
        )
    )


if __name__ == "__main__":
    main()
