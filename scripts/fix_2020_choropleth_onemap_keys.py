"""Fix 2020 precinct contest keys for Voting_Precincts choropleth join.

1) Rename high-confidence key variants onto polygon IDs (Gaston *A / -1, Rockingham
   ED vs ED-1, etc.).
2) Remaining non-joining rows are treated as residual early-vote / site buckets and
   allocated onto in-county matched precincts by each precinct's major-party share
   (same spirit as precinct_candidate non-geo).

Does not touch district_contests*.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parents[1]


def norm(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().upper())


def load_poly_by_county() -> dict[str, set[str]]:
    gdf = gpd.read_file(ROOT / "data/Voting_Precincts.geojson")
    out: dict[str, set[str]] = defaultdict(set)
    for _, r in gdf.iterrows():
        county = norm(r["county_nam"])
        code = norm(r["prec_id"])
        if county and code:
            out[county].add(code)
    return out


def gaston_style_remap(code: str, poly: set[str]) -> str:
    """Map '1A'/'10A' onto '01'/'10' or '06-1' when those are the polygon IDs."""
    m = re.fullmatch(r"0*([0-9]{1,3})A", code)
    if not m:
        return code
    n = int(m.group(1))
    z2 = f"{n:02d}"
    bare = str(n)
    for cand in (z2, bare, f"{z2}-1", f"{bare}-1"):
        if cand in poly:
            return cand
    return code


def rockingham_remap(code: str, poly: set[str]) -> str:
    aliases = {
        "ED": "ED-1",
        "HO-1": "HO",
        "HU-1": "HU",
        "LI-1": "LI",
        "WS-1": "WS",
        "RE-1": "RC",  # only if RC in poly and RE-1 not — validate below
        "RE-2": "RC",
    }
    # Careful with RE-*: only map if target exists and source doesn't
    if code in poly:
        return code
    if code == "RE-1" and "RC" in poly:
        return "RC"
    if code == "RE-2" and "SE" in poly:
        # unknown — leave for allocate path
        return code
    tgt = aliases.get(code)
    if tgt and tgt in poly and code not in poly:
        return tgt
    # WI / MO / ST / ED already handled
    if code == "ST" and "SE" in poly:
        return "SE"
    if code == "MO" and "MS" in poly:
        return "MS"
    if code == "WI" and "IR" in poly:
        return "IR"
    return code


def cleveland_remap(code: str, poly: set[str]) -> str:
    # contest 'S E' / 'S N' vs poly 'S 4A' etc. — not safe 1:1; leave
    return code


def propose_remap(county: str, code: str, poly: set[str]) -> str:
    if code in poly:
        return code
    if county == "GASTON":
        return gaston_style_remap(code, poly)
    if county == "ROCKINGHAM":
        return rockingham_remap(code, poly)
    if county == "CLEVELAND":
        return cleveland_remap(code, poly)
    # Generic: zero-pad bare integers when poly uses zero-padded forms
    if re.fullmatch(r"[0-9]{1,3}", code):
        z2 = f"{int(code):02d}"
        for cand in (z2, f"{z2}-1", f"{code}-1"):
            if cand in poly:
                return cand
    return code


def allocate_residual(
    matched: list[dict], residual: list[dict]
) -> list[dict]:
    """Spread residual dem/rep/other onto matched rows by each row's major-party share."""
    if not residual:
        return matched
    if not matched:
        # Nowhere to put them — keep residual (still unmatched) rather than drop votes
        return residual

    dem_res = sum(float(r.get("dem_votes") or 0) for r in residual)
    rep_res = sum(float(r.get("rep_votes") or 0) for r in residual)
    oth_res = sum(float(r.get("other_votes") or 0) for r in residual)

    weights = []
    for r in matched:
        d = float(r.get("dem_votes") or 0)
        rp = float(r.get("rep_votes") or 0)
        weights.append(max(d + rp, 0.0))
    wsum = sum(weights)
    if wsum <= 0:
        weights = [1.0] * len(matched)
        wsum = float(len(matched))

    out = []
    for r, w in zip(matched, weights):
        share = w / wsum
        nr = dict(r)
        nr["dem_votes"] = float(r.get("dem_votes") or 0) + dem_res * share
        nr["rep_votes"] = float(r.get("rep_votes") or 0) + rep_res * share
        nr["other_votes"] = float(r.get("other_votes") or 0) + oth_res * share
        nr["total_votes"] = nr["dem_votes"] + nr["rep_votes"] + nr["other_votes"]
        dem, rep = nr["dem_votes"], nr["rep_votes"]
        tot_major = dem + rep
        if tot_major > 0:
            # Prefer DEM-REP signed convention already used (rep-dem in some paths);
            # existing files use margin as |winner lead| with winner label.
            if rep >= dem:
                nr["margin"] = rep - dem
                nr["margin_pct"] = (rep - dem) / tot_major * 100.0
                nr["winner"] = "REP" if rep > dem else "TIE"
            else:
                nr["margin"] = dem - rep
                nr["margin_pct"] = (dem - rep) / tot_major * 100.0
                nr["winner"] = "DEM"
            # colors left as-is; UI often recomputes from margin_pct
        out.append(nr)
    return out


def merge_rows(rows: list[dict]) -> list[dict]:
    """Sum rows that share the same county key."""
    buckets: dict[str, dict] = {}
    order: list[str] = []
    for r in rows:
        key = norm(r.get("county"))
        if key not in buckets:
            buckets[key] = dict(r)
            buckets[key]["dem_votes"] = float(r.get("dem_votes") or 0)
            buckets[key]["rep_votes"] = float(r.get("rep_votes") or 0)
            buckets[key]["other_votes"] = float(r.get("other_votes") or 0)
            order.append(key)
        else:
            buckets[key]["dem_votes"] += float(r.get("dem_votes") or 0)
            buckets[key]["rep_votes"] += float(r.get("rep_votes") or 0)
            buckets[key]["other_votes"] += float(r.get("other_votes") or 0)
    out = []
    for key in order:
        r = buckets[key]
        r["county"] = key
        r["dem_votes"] = float(r["dem_votes"])
        r["rep_votes"] = float(r["rep_votes"])
        r["other_votes"] = float(r["other_votes"])
        r["total_votes"] = r["dem_votes"] + r["rep_votes"] + r["other_votes"]
        dem, rep = r["dem_votes"], r["rep_votes"]
        tot_major = dem + rep
        if tot_major > 0:
            if rep >= dem:
                r["margin"] = rep - dem
                r["margin_pct"] = round((rep - dem) / tot_major * 100.0, 4)
                r["winner"] = "REP" if rep > dem else "TIE"
            else:
                r["margin"] = dem - rep
                r["margin_pct"] = round((dem - rep) / tot_major * 100.0, 4)
                r["winner"] = "DEM"
        out.append(r)
    return out


def fix_contest(path: Path, poly_by_county: dict[str, set[str]]) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows") or []
    remapped = []
    remap_hits = 0
    for r in rows:
        key = norm(r.get("county"))
        if " - " not in key:
            remapped.append(dict(r, county=key))
            continue
        county, code = key.split(" - ", 1)
        poly = poly_by_county.get(county, set())
        new_code = propose_remap(county, code, poly)
        new_key = f"{county} - {new_code}"
        if new_code != code:
            remap_hits += 1
        nr = dict(r)
        nr["county"] = new_key
        remapped.append(nr)

    remapped = merge_rows(remapped)

    matched: list[dict] = []
    residual: list[dict] = []
    by_county_m: dict[str, list[dict]] = defaultdict(list)
    by_county_r: dict[str, list[dict]] = defaultdict(list)
    for r in remapped:
        key = norm(r.get("county"))
        county, code = (key.split(" - ", 1) + [""])[:2] if " - " in key else (key, "")
        poly = poly_by_county.get(county, set())
        if code in poly:
            by_county_m[county].append(r)
        else:
            by_county_r[county].append(r)

    fixed_rows: list[dict] = []
    counties = sorted(set(by_county_m) | set(by_county_r))
    residual_votes = 0.0
    residual_n = 0
    for county in counties:
        m = by_county_m.get(county, [])
        r = by_county_r.get(county, [])
        residual_votes += sum(
            float(x.get("dem_votes") or 0) + float(x.get("rep_votes") or 0) for x in r
        )
        residual_n += len(r)
        fixed_rows.extend(allocate_residual(m, r))

    # Keep stable-ish ordering: by county key
    fixed_rows.sort(key=lambda r: norm(r.get("county")))

    dem_total = sum(float(r.get("dem_votes") or 0) for r in fixed_rows)
    rep_total = sum(float(r.get("rep_votes") or 0) for r in fixed_rows)
    oth_total = sum(float(r.get("other_votes") or 0) for r in fixed_rows)
    meta = dict(data.get("meta") or {})
    meta["dem_total"] = dem_total
    meta["rep_total"] = rep_total
    meta["other_total"] = oth_total
    meta["total_votes"] = dem_total + rep_total + oth_total
    meta["choropleth_key_fix"] = "onemap_join_remap_plus_residual_alloc"
    meta["choropleth_remap_hits"] = remap_hits
    meta["choropleth_residual_rows_allocated"] = residual_n
    meta["choropleth_residual_major_votes_allocated"] = residual_votes
    data["meta"] = meta
    data["rows"] = fixed_rows
    return {
        "path": path,
        "data": data,
        "remap_hits": remap_hits,
        "residual_n": residual_n,
        "residual_votes": residual_votes,
        "rows_before": len(rows),
        "rows_after": len(fixed_rows),
    }


def main() -> None:
    poly = load_poly_by_county()
    paths = sorted((ROOT / "data/contests").glob("*_2020.json"))
    # Skip manifest
    paths = [p for p in paths if p.name != "manifest.json"]
    summaries = []
    for p in paths:
        stats = fix_contest(p, poly)
        p.write_text(json.dumps(stats["data"], indent=2) + "\n", encoding="utf-8")
        summaries.append(stats)
        print(
            f"{p.name}: rows {stats['rows_before']}->{stats['rows_after']} "
            f"remap={stats['remap_hits']} residual_rows={stats['residual_n']} "
            f"residual_votes={stats['residual_votes']:.0f}"
        )

    # Quick president join QA
    pres = next(s for s in summaries if s["path"].name == "president_2020.json")
    keys = {norm(r["county"]) for r in pres["data"]["rows"]}
    all_poly = {f"{c} - {code}" for c, codes in poly.items() for code in codes}
    print(
        f"president join matched={len(keys & all_poly)} "
        f"unmatched={len(keys - all_poly)} residual_votes={pres['residual_votes']:.0f}"
    )


if __name__ == "__main__":
    main()
