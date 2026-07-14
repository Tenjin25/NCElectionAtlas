"""Build precinct label points that always lie inside their polygons.

Uses shapely representative_point (guaranteed on-surface) instead of a raw
bounding-box midpoint, which can land in a neighboring precinct for concave
or L-shaped polygons (observed in Cabarrus 01-10 / 02-01).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from shapely.geometry import shape


RE_NON_KEY = re.compile(r"[^a-z0-9 .\-]", flags=re.IGNORECASE)
RE_WS = re.compile(r"\s+")


def normalize_precinct_norm(county_nam: str, prec_id: str) -> str:
    raw = f"{county_nam} - {prec_id}"
    raw = RE_NON_KEY.sub("", raw)
    raw = RE_WS.sub(" ", raw).strip().upper()
    return raw


def clean_label(raw: str) -> str:
    return RE_WS.sub(" ", str(raw or "").strip())


def point_inside_geom(geom_obj) -> tuple[float, float] | None:
    if not geom_obj:
        return None
    try:
        geom = shape(geom_obj)
    except Exception:
        return None
    if geom.is_empty:
        return None
    # Prefer a guaranteed interior point; fall back to centroid if needed.
    pt = geom.representative_point()
    if pt.is_empty:
        pt = geom.centroid
    if pt.is_empty:
        return None
    return (float(pt.x), float(pt.y))


def main() -> None:
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
        c = point_inside_geom(feat.get("geometry"))
        if not c:
            continue
        x, y = c
        x = round(x, 6)
        y = round(y, 6)
        out_features.append(
            {
                "type": "Feature",
                "properties": {
                    "county_nam": county_nam,
                    "prec_id": prec_id,
                    "enr_desc": clean_label(props.get("enr_desc") or ""),
                    "name": clean_label(props.get("enr_desc") or ""),
                    "label": clean_label(props.get("enr_desc") or ""),
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
