import argparse
import json
import re
from pathlib import Path


RE_WS = re.compile(r"\s+")


def norm_text(value: object) -> str:
    return RE_WS.sub(" ", str(value or "")).strip().upper()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize a raw NC precinct GeoJSON into atlas-ready format by uppercasing county/precinct IDs and adding precinct_norm."
    )
    parser.add_argument("--src", required=True, help="Input raw GeoJSON path")
    parser.add_argument("--out", required=True, help="Output atlas-ready GeoJSON path")
    args = parser.parse_args()

    src = Path(args.src)
    out = Path(args.out)

    payload = json.loads(src.read_text(encoding="utf-8"))
    features = payload.get("features", [])
    out_features = []

    for feat in features:
        props = dict((feat.get("properties") or {}))
        county = norm_text(props.get("county_nam", ""))
        prec_id = norm_text(props.get("prec_id", ""))
        if county:
            props["county_nam"] = county
        if prec_id:
            props["prec_id"] = prec_id
        if county and prec_id:
            props["precinct_norm"] = f"{county} - {prec_id}"
        out_features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": feat.get("geometry"),
            }
        )

    out_payload = {
        "type": "FeatureCollection",
        "name": payload.get("name", "Voting_Precincts"),
        "features": out_features,
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(out_payload, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {out} with {len(out_features)} features")


if __name__ == "__main__":
    main()
