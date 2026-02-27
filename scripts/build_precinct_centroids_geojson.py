import json
import math
import re
from pathlib import Path


RE_NON_KEY = re.compile(r"[^a-z0-9 .\-]", flags=re.IGNORECASE)
RE_WS = re.compile(r"\s+")


def normalize_precinct_norm(county_nam: str, prec_id: str) -> str:
    raw = f"{county_nam} - {prec_id}"
    raw = RE_NON_KEY.sub("", raw)
    raw = RE_WS.sub(" ", raw).strip().upper()
    return raw


def scan_bbox(coords, bbox):
    # coords can be nested lists; leaf is [x, y] (or [x, y, ...]).
    if not coords:
        return
    first = coords[0]
    if isinstance(first, (float, int)):
        x = float(coords[0])
        y = float(coords[1])
        bbox[0] = min(bbox[0], x)
        bbox[1] = min(bbox[1], y)
        bbox[2] = max(bbox[2], x)
        bbox[3] = max(bbox[3], y)
        return
    for sub in coords:
        scan_bbox(sub, bbox)


def centroid_from_bbox(geom) -> tuple[float, float] | None:
    if not geom:
        return None
    coords = geom.get("coordinates")
    if coords is None:
        return None
    bbox = [math.inf, math.inf, -math.inf, -math.inf]
    scan_bbox(coords, bbox)
    if not math.isfinite(bbox[0]) or not math.isfinite(bbox[1]):
        return None
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def main():
    repo_root = Path(__file__).resolve().parents[1]
    in_path = repo_root / "data" / "Voting_Precincts.geojson"
    out_path = repo_root / "data" / "precinct_centroids.geojson"

    if not in_path.exists():
        raise SystemExit(f"Missing input: {in_path}")

    with in_path.open("r", encoding="utf-8") as f:
        gj = json.load(f)

    out_features = []
    for feat in gj.get("features", []):
        props = feat.get("properties") or {}
        county_nam = (props.get("county_nam") or "").strip()
        prec_id = (props.get("prec_id") or "").strip()
        if not county_nam or not prec_id:
            continue
        c = centroid_from_bbox(feat.get("geometry"))
        if not c:
            continue
        x, y = c
        # Keep the output small and deterministic.
        x = round(x, 6)
        y = round(y, 6)
        out_features.append(
            {
                "type": "Feature",
                "properties": {
                    "county_nam": county_nam,
                    "prec_id": prec_id,
                    "precinct_norm": normalize_precinct_norm(county_nam, prec_id),
                },
                "geometry": {"type": "Point", "coordinates": [x, y]},
            }
        )

    out = {"type": "FeatureCollection", "features": out_features}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
        f.write("\n")

    print(f"Wrote {out_path} with {len(out_features)} precinct centroids")


if __name__ == "__main__":
    main()

