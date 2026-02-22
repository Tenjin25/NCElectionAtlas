"""
Build district-level election results on 2024 legislative lines by reallocating
precinct results using precomputed area-weighted crosswalks.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd


def calculate_competitiveness(margin_pct: float) -> str:
    abs_margin = abs(margin_pct)
    if abs_margin < 0.5:
        return "#f7f7f7"
    rep_win = margin_pct > 0
    if abs_margin >= 40:
        return "#67000d" if rep_win else "#08306b"
    if abs_margin >= 30:
        return "#a50f15" if rep_win else "#08519c"
    if abs_margin >= 20:
        return "#cb181d" if rep_win else "#3182bd"
    if abs_margin >= 10:
        return "#ef3b2c" if rep_win else "#6baed6"
    if abs_margin >= 5.5:
        return "#fb6a4a" if rep_win else "#9ecae1"
    if abs_margin >= 1:
        return "#fcae91" if rep_win else "#c6dbef"
    return "#fee8c8" if rep_win else "#e1f5fe"


def load_crosswalk(path: Path) -> dict[str, list[tuple[str, float]]]:
    df = pd.read_csv(path, dtype={"district": str})
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for _, r in df.iterrows():
        key = str(r["precinct_key"]).strip().upper()
        out[key].append((str(r["district"]).strip(), float(r["area_weight"])))
    return out


def _norm(text: str) -> str:
    return str(text).upper().strip()


def _compact(text: str) -> str:
    t = _norm(text)
    return "".join(ch for ch in t if ch.isalnum())


def _is_non_geographic_precinct(p: str) -> bool:
    t = _norm(p)
    flags = [
        "ABSENTEE",
        "PROVISIONAL",
        "CURBSIDE",
        "ONE STOP",
        "EARLY VOT",
        "TRANSFER",
        "MAIL",
    ]
    return any(f in t for f in flags) or t.startswith("OS-")


def _extract_code_name_aliases(raw: str) -> list[str]:
    aliases = set()
    p = _norm(raw)
    aliases.add(p)
    aliases.add(_compact(p))

    if "_" in p:
        code, name = p.split("_", 1)
        aliases.add(code.strip())
        aliases.add(name.strip())
        aliases.add(_compact(code))
        aliases.add(_compact(name))

    parts = p.split()
    if parts:
        first = parts[0]
        if any(ch.isdigit() for ch in first):
            aliases.add(first)
            aliases.add(_compact(first))
            rest = " ".join(parts[1:]).strip()
            if rest:
                aliases.add(rest)
                aliases.add(_compact(rest))

    # Precinct code variants (01.1 vs 011 vs 0011 etc.)
    s = p.replace("-", ".")
    if "." in s:
        a, b = s.split(".", 1)
        if a.isdigit() and b.isdigit():
            aliases.add(f"{int(a)}.{int(b)}")
            aliases.add(f"{int(a):02d}.{int(b)}")
            aliases.add(f"{int(a):02d}{int(b)}")
            aliases.add(f"{int(a):02d}{int(b):02d}")
    if p.isdigit():
        aliases.add(str(int(p)))
        aliases.add(p.zfill(4))

    return [a for a in aliases if a]


NC_COUNTY_FIPS = {
    "001": "ALAMANCE", "003": "ALEXANDER", "005": "ALLEGHANY", "007": "ANSON",
    "009": "ASHE", "011": "AVERY", "013": "BEAUFORT", "015": "BERTIE",
    "017": "BLADEN", "019": "BRUNSWICK", "021": "BUNCOMBE", "023": "BURKE",
    "025": "CABARRUS", "027": "CALDWELL", "029": "CAMDEN", "031": "CARTERET",
    "033": "CASWELL", "035": "CATAWBA", "037": "CHATHAM", "039": "CHEROKEE",
    "041": "CHOWAN", "043": "CLAY", "045": "CLEVELAND", "047": "COLUMBUS",
    "049": "CRAVEN", "051": "CUMBERLAND", "053": "CURRITUCK", "055": "DARE",
    "057": "DAVIDSON", "059": "DAVIE", "061": "DUPLIN", "063": "DURHAM",
    "065": "EDGECOMBE", "067": "FORSYTH", "069": "FRANKLIN", "071": "GASTON",
    "073": "GATES", "075": "GRAHAM", "077": "GRANVILLE", "079": "GREENE",
    "081": "GUILFORD", "083": "HALIFAX", "085": "HARNETT", "087": "HAYWOOD",
    "089": "HENDERSON", "091": "HERTFORD", "093": "HOKE", "095": "HYDE",
    "097": "IREDELL", "099": "JACKSON", "101": "JOHNSTON", "103": "JONES",
    "105": "LEE", "107": "LENOIR", "109": "LINCOLN", "111": "MCDOWELL",
    "113": "MACON", "115": "MADISON", "117": "MARTIN", "119": "MECKLENBURG",
    "121": "MITCHELL", "123": "MONTGOMERY", "125": "MOORE", "127": "NASH",
    "129": "NEW HANOVER", "131": "NORTHAMPTON", "133": "ONSLOW", "135": "ORANGE",
    "137": "PAMLICO", "139": "PASQUOTANK", "141": "PENDER", "143": "PERQUIMANS",
    "145": "PERSON", "147": "PITT", "149": "POLK", "151": "RANDOLPH",
    "153": "RICHMOND", "155": "ROBESON", "157": "ROCKINGHAM", "159": "ROWAN",
    "161": "RUTHERFORD", "163": "SAMPSON", "165": "SCOTLAND", "167": "STANLY",
    "169": "STOKES", "171": "SURRY", "173": "SWAIN", "175": "TRANSYLVANIA",
    "177": "TYRRELL", "179": "UNION", "181": "VANCE", "183": "WAKE",
    "185": "WARREN", "187": "WASHINGTON", "189": "WATAUGA", "191": "WAYNE",
    "193": "WILKES", "195": "WILSON", "197": "YADKIN", "199": "YANCEY",
}


def build_precinct_alias_index(voting_geojson_path: Path) -> dict[str, dict[str, set[str]]]:
    geo = json.load(open(voting_geojson_path, "r", encoding="utf-8"))
    county_map: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for f in geo.get("features", []):
        props = f.get("properties", {})
        county = _norm(props.get("county_nam", ""))
        prec_id = _norm(props.get("prec_id", ""))
        enr_desc = _norm(props.get("enr_desc", ""))
        if not county or not prec_id:
            continue
        canonical = f"{county} - {prec_id}"

        aliases = set()
        aliases.update(_extract_code_name_aliases(prec_id))
        if enr_desc:
            aliases.update(_extract_code_name_aliases(enr_desc))
            aliases.update(_extract_code_name_aliases(f"{prec_id}_{enr_desc}"))
            aliases.update(_extract_code_name_aliases(f"{prec_id} {enr_desc}"))

        for a in aliases:
            county_map[county][a].add(canonical)

    return county_map


def _canonical_code_maps(alias_index: dict[str, dict[str, set[str]]]) -> dict[str, dict[str, set[str]]]:
    out: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for county, aliases in alias_index.items():
        canonical_keys = set()
        for vals in aliases.values():
            canonical_keys.update(vals)
        for canon in canonical_keys:
            if " - " not in canon:
                continue
            _, precinct = canon.split(" - ", 1)
            out[county][_compact(precinct)].add(canon)
    return out


def _county_name_from_record(props: dict, county_col: str) -> str:
    raw = props.get(county_col, "")
    if raw is None:
        return ""
    s = str(raw).strip()
    if s.isdigit():
        return NC_COUNTY_FIPS.get(s.zfill(3), "")
    return _norm(s)


def enrich_alias_index_from_vtd(
    alias_index: dict[str, dict[str, set[str]]],
    *,
    vtd_path: Path,
    county_col: str,
    code_col: str,
    name_col: str,
) -> int:
    if not vtd_path.exists():
        return 0
    vtd = json.load(open(vtd_path, "r", encoding="utf-8")) if vtd_path.suffix.lower() == ".geojson" else None
    if vtd is None:
        import geopandas as gpd  # local import to avoid dependency at module import time

        gdf = gpd.read_file(vtd_path)
        features = [{"properties": row} for row in gdf.to_dict("records")]
    else:
        features = vtd.get("features", [])

    code_map = _canonical_code_maps(alias_index)
    added = 0

    for f in features:
        props = f.get("properties", {})
        county = _county_name_from_record(props, county_col)
        if not county or county not in alias_index:
            continue
        code = _norm(props.get(code_col, ""))
        name = _norm(props.get(name_col, ""))
        if not code:
            continue

        county_aliases = alias_index[county]
        candidates = set()

        for a in _extract_code_name_aliases(code):
            vals = county_aliases.get(a)
            if vals:
                candidates.update(vals)

        if name:
            for a in _extract_code_name_aliases(name):
                vals = county_aliases.get(a)
                if vals:
                    candidates.update(vals)

        code_compact = _compact(code)
        if code_compact in code_map[county]:
            candidates.update(code_map[county][code_compact])

        if len(candidates) != 1:
            continue
        canonical = next(iter(candidates))
        for a in _extract_code_name_aliases(code):
            if canonical not in county_aliases[a]:
                county_aliases[a].add(canonical)
                added += 1
        if name:
            for a in _extract_code_name_aliases(name):
                if canonical not in county_aliases[a]:
                    county_aliases[a].add(canonical)
                    added += 1

    return added


def resolve_precinct_key(
    election_precinct_key: str,
    alias_index: dict[str, dict[str, set[str]]],
) -> tuple[str | None, str]:
    # Returns (canonical_precinct_key, status)
    if " - " not in election_precinct_key:
        return None, "bad_key"
    county, precinct = election_precinct_key.split(" - ", 1)
    county = _norm(county)
    precinct = _norm(precinct)
    if _is_non_geographic_precinct(precinct):
        return None, "non_geographic"

    county_aliases = alias_index.get(county)
    if not county_aliases:
        return None, "no_county"

    cands = _extract_code_name_aliases(precinct)
    hits = set()
    for a in cands:
        vals = county_aliases.get(a)
        if vals:
            hits.update(vals)

    if len(hits) == 1:
        return next(iter(hits)), "matched"
    if len(hits) > 1:
        return None, "ambiguous"
    return None, "unmatched"


def allocate_office_results(
    office_results: dict,
    crosswalk: dict[str, list[tuple[str, float]]],
    alias_index: dict[str, dict[str, set[str]]],
) -> tuple[dict, dict[str, int]]:
    by_district: dict[str, dict[str, float]] = defaultdict(
        lambda: {"dem_votes": 0.0, "rep_votes": 0.0, "other_votes": 0.0}
    )
    stats = defaultdict(int)

    for precinct_key, row in office_results.items():
        stats["total"] += 1
        key = str(precinct_key).strip().upper()
        resolved_key, status = resolve_precinct_key(key, alias_index)
        stats[status] += 1
        if resolved_key:
            key = resolved_key

        splits = crosswalk.get(key)
        if not splits:
            continue
        stats["crosswalk_matched"] += 1

        dem = float(row.get("dem_votes", 0) or 0)
        rep = float(row.get("rep_votes", 0) or 0)
        oth = float(row.get("other_votes", 0) or 0)

        for district, weight in splits:
            by_district[district]["dem_votes"] += dem * weight
            by_district[district]["rep_votes"] += rep * weight
            by_district[district]["other_votes"] += oth * weight

    out = {}
    for district, vals in by_district.items():
        dem = int(round(vals["dem_votes"]))
        rep = int(round(vals["rep_votes"]))
        oth = int(round(vals["other_votes"]))
        total_votes = dem + rep + oth
        margin = rep - dem
        margin_pct = (margin / total_votes * 100) if total_votes else 0.0
        winner = "REP" if margin > 0 else "DEM" if margin < 0 else "TIE"
        out[district] = {
            "dem_votes": dem,
            "rep_votes": rep,
            "other_votes": oth,
            "total_votes": total_votes,
            "dem_candidate": "",
            "rep_candidate": "",
            "margin": margin,
            "margin_pct": round(margin_pct, 2),
            "winner": winner,
            "competitiveness": {"color": calculate_competitiveness(margin_pct)},
        }
    return out, stats


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    data_dir = root / "data"
    in_json = data_dir / "nc_elections_aggregated.json"
    house_cw = data_dir / "crosswalks" / "precinct_to_2022_state_house.csv"
    senate_cw = data_dir / "crosswalks" / "precinct_to_2022_state_senate.csv"
    congress_cw = data_dir / "crosswalks" / "precinct_to_cd118.csv"
    voting_geojson = data_dir / "Voting_Precincts.geojson"
    vtd_2008 = data_dir / "census" / "tl_2008_37_vtd00_merged.geojson"
    vtd_2012 = data_dir / "census" / "tl_2012_37_vtd10" / "tl_2012_37_vtd10.shp"
    vtd_2020 = (data_dir / "tl_2020_37_vtd20" / "tl_2020_37_vtd20.shp")
    if not vtd_2020.exists():
        vtd_2020 = data_dir / "census" / "tl_2020_37_vtd20" / "tl_2020_37_vtd20.shp"

    if not in_json.exists():
        raise FileNotFoundError(f"Missing {in_json}")
    if not house_cw.exists() or not senate_cw.exists() or not congress_cw.exists():
        raise FileNotFoundError("Missing precinct crosswalk CSVs. Run build_precinct_crosswalks_to_2024.py first.")

    src = json.load(open(in_json, "r", encoding="utf-8"))
    house_map = load_crosswalk(house_cw)
    senate_map = load_crosswalk(senate_cw)
    congress_map = load_crosswalk(congress_cw)
    alias_index = build_precinct_alias_index(voting_geojson)
    added_2008 = enrich_alias_index_from_vtd(
        alias_index,
        vtd_path=vtd_2008,
        county_col="COUNTYFP00",
        code_col="VTDST00",
        name_col="NAME00",
    )
    added_2012 = enrich_alias_index_from_vtd(
        alias_index,
        vtd_path=vtd_2012,
        county_col="COUNTYFP10",
        code_col="VTDST10",
        name_col="NAME10",
    )
    added_2020 = enrich_alias_index_from_vtd(
        alias_index,
        vtd_path=vtd_2020,
        county_col="COUNTYFP20",
        code_col="VTDST20",
        name_col="NAME20",
    )
    print(
        f"Alias enrichment added mappings: 2008={added_2008}, "
        f"2012={added_2012}, 2020={added_2020}"
    )

    dst = {"results_by_year": {}}

    for year, year_data in src.get("results_by_year", {}).items():
        dst["results_by_year"][year] = {"state_house": {}, "state_senate": {}, "congressional": {}}
        for office_key, office_data in year_data.items():
            office_results = office_data.get("general", {}).get("results", {})
            if not office_results:
                continue

            house_results, hstats = allocate_office_results(office_results, house_map, alias_index)
            senate_results, sstats = allocate_office_results(office_results, senate_map, alias_index)
            congress_results, cstats = allocate_office_results(office_results, congress_map, alias_index)

            hcov = (hstats["crosswalk_matched"] / hstats["total"] * 100.0) if hstats["total"] else 0.0
            scov = (sstats["crosswalk_matched"] / sstats["total"] * 100.0) if sstats["total"] else 0.0
            ccov = (cstats["crosswalk_matched"] / cstats["total"] * 100.0) if cstats["total"] else 0.0

            dst["results_by_year"][year]["state_house"][office_key] = {
                "meta": {
                    "match_coverage_pct": round(hcov, 2),
                    "matched_precinct_keys": int(hstats["crosswalk_matched"]),
                    "total_precinct_keys": int(hstats["total"]),
                },
                "general": {"results": house_results},
            }
            dst["results_by_year"][year]["state_senate"][office_key] = {
                "meta": {
                    "match_coverage_pct": round(scov, 2),
                    "matched_precinct_keys": int(sstats["crosswalk_matched"]),
                    "total_precinct_keys": int(sstats["total"]),
                },
                "general": {"results": senate_results},
            }
            dst["results_by_year"][year]["congressional"][office_key] = {
                "meta": {
                    "match_coverage_pct": round(ccov, 2),
                    "matched_precinct_keys": int(cstats["crosswalk_matched"]),
                    "total_precinct_keys": int(cstats["total"]),
                },
                "general": {"results": congress_results},
            }
            print(
                f"{year} {office_key}: matched precinct keys -> "
                f"house {hstats['crosswalk_matched']}/{hstats['total']} ({hcov:.1f}%), "
                f"senate {sstats['crosswalk_matched']}/{sstats['total']} ({scov:.1f}%), "
                f"cd118 {cstats['crosswalk_matched']}/{cstats['total']} ({ccov:.1f}%)"
            )

    out_json = data_dir / "nc_district_results_2022_lines.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(dst, f, indent=2)
    print(f"\nWrote {out_json}")


if __name__ == "__main__":
    main()
