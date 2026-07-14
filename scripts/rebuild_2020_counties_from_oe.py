"""Rebuild selected 2020 counties in precinct contest JSONs from OpenElections.

Uses build_precinct_party_votes (non-geo precinct_candidate) + Voting_Precincts
key matching. Replaces only TARGET_COUNTIES rows in each *_2020.json so the rest
of the state stays intact. Does not write district_contests*.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_district_contests_from_batch_shatter import (  # noqa: E402
    build_precinct_contest_payload,
    build_precinct_party_votes,
    infer_office_key,
    is_non_geographic_precinct,
    party_group,
)

OE_PATH = ROOT / "data/2020/20201103__nc__general__precinct.csv"
POLY_PATH = ROOT / "data/Voting_Precincts.geojson"
CONTESTS_DIR = ROOT / "data/contests"

TARGET_COUNTIES = {"RICHMOND", "HARNETT", "BLADEN", "WAKE"}


def norm(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().upper())


def load_poly() -> dict[str, set[str]]:
    gdf = gpd.read_file(POLY_PATH)
    out: dict[str, set[str]] = {}
    for _, r in gdf.iterrows():
        c = norm(r["county_nam"])
        out.setdefault(c, set()).add(norm(r["prec_id"]))
    return out


def wake_oem_aliases(code: str, poly: set[str]) -> str:
    """Map a few OE tokens onto current OneMap when exact key missing."""
    if code in poly:
        return code
    # Letter suffix collapsed onto base when base exists (already in PRECINCT_ALIASES).
    m = re.fullmatch(r"(.+[0-9])([A-Z])", code)
    if m and m.group(1) in poly:
        return m.group(1)
    # 03-00 retired → split 03-01/03-02: keep as 03-00 only if present; else leave
    # for residual handling (caller may drop or allocate).
    return code


def county_code_remap(county: str, code: str, poly: set[str]) -> str:
    if county == "WAKE":
        return wake_oem_aliases(code, poly)
    return code if code in poly else code


def load_oe() -> pd.DataFrame:
    src = pd.read_csv(OE_PATH, dtype=str, low_memory=False)
    src.columns = [c.lower() for c in src.columns]
    need = {"county", "precinct", "office", "party", "candidate", "votes"}
    missing = need - set(src.columns)
    if missing:
        raise SystemExit(f"OE missing columns: {missing}")
    src["county"] = src["county"].map(norm)
    src["precinct"] = src["precinct"].map(norm)
    src["office"] = src["office"].astype(str).str.strip()
    src["party"] = src["party"].astype(str)
    src["candidate"] = src["candidate"].astype(str)
    src["votes"] = pd.to_numeric(src["votes"], errors="coerce").fillna(0.0)
    src = src[src["county"].isin(TARGET_COUNTIES)].copy()
    return src


def color_for_winner(winner: str, margin_pct: float) -> str:
    # Match the committed contest palette roughly (red/blue stops).
    abs_m = abs(float(margin_pct or 0))
    if winner == "TIE":
        return "#f7f7f7"
    rep = winner == "REP"
    if abs_m >= 40:
        return "#67000d" if rep else "#08306b"
    if abs_m >= 30:
        return "#a50f15" if rep else "#08519c"
    if abs_m >= 20:
        return "#cb181d" if rep else "#3182bd"
    if abs_m >= 10:
        return "#ef3b2c" if rep else "#6baed6"
    if abs_m >= 5.5:
        return "#fb6a4a" if rep else "#9ecae1"
    if abs_m >= 1:
        return "#fcae91" if rep else "#c6dbef"
    return "#fee8c8" if rep else "#e1f5fe"


def party_df_to_rows(
    precinct_party: pd.DataFrame,
    year: int,
    dem_candidate: str,
    rep_candidate: str,
    poly: dict[str, set[str]],
) -> list[dict]:
    if precinct_party.empty:
        return []
    df = precinct_party.copy()
    matched: list[dict] = []
    residual: list[dict] = []
    for _, r in df.iterrows():
        pid = norm(r["precinct_id"])
        if " - " not in pid:
            continue
        county, code = pid.split(" - ", 1)
        if county not in TARGET_COUNTIES:
            continue
        code = county_code_remap(county, code, poly.get(county, set()))
        pid = f"{county} - {code}"
        dem = float(r.get("dem_votes") or 0)
        rep = float(r.get("rep_votes") or 0)
        oth = float(r.get("other_votes") or 0)
        item = {
            "year": year,
            "county": pid,
            "dem_votes": dem,
            "rep_votes": rep,
            "other_votes": oth,
            "total_votes": dem + rep + oth,
            "dem_candidate": dem_candidate,
            "rep_candidate": rep_candidate,
        }
        if code in poly.get(county, set()):
            matched.append(item)
        else:
            # OE geo codes that no longer exist on OneMap (e.g. Wake 03-00).
            residual.append(item)

    by_m: dict[str, list[dict]] = {}
    by_r: dict[str, list[dict]] = {}
    for item in matched:
        by_m.setdefault(norm(item["county"]).split(" - ", 1)[0], []).append(item)
    for item in residual:
        by_r.setdefault(norm(item["county"]).split(" - ", 1)[0], []).append(item)

    final: list[dict] = []
    for county in sorted(TARGET_COUNTIES):
        mrows = by_m.get(county, [])
        rrows = by_r.get(county, [])
        if rrows and mrows:
            dem_res = sum(x["dem_votes"] for x in rrows)
            rep_res = sum(x["rep_votes"] for x in rrows)
            oth_res = sum(x["other_votes"] for x in rrows)
            weights = [max(x["dem_votes"] + x["rep_votes"], 0.0) for x in mrows]
            wsum = sum(weights)
            if wsum <= 0:
                weights = [1.0] * len(mrows)
                wsum = float(len(mrows))
            for x, w in zip(mrows, weights):
                share = w / wsum
                x["dem_votes"] += dem_res * share
                x["rep_votes"] += rep_res * share
                x["other_votes"] += oth_res * share
                x["total_votes"] = x["dem_votes"] + x["rep_votes"] + x["other_votes"]
        for x in mrows:
            dem, rep = x["dem_votes"], x["rep_votes"]
            major = dem + rep
            if major > 0:
                if rep > dem:
                    winner, margin, mp = "REP", rep - dem, (rep - dem) / major * 100.0
                elif dem > rep:
                    winner, margin, mp = "DEM", dem - rep, (dem - rep) / major * 100.0
                else:
                    winner, margin, mp = "TIE", 0.0, 0.0
            else:
                winner, margin, mp = "TIE", 0.0, 0.0
            x["margin"] = margin
            x["margin_pct"] = round(mp, 4)
            x["winner"] = winner
            x["color"] = color_for_winner(winner, mp)
            final.append(x)

    buckets: dict[str, dict] = {}
    order: list[str] = []
    for r in final:
        k = r["county"]
        if k not in buckets:
            buckets[k] = dict(r)
            order.append(k)
        else:
            b = buckets[k]
            b["dem_votes"] += r["dem_votes"]
            b["rep_votes"] += r["rep_votes"]
            b["other_votes"] += r["other_votes"]
            b["total_votes"] = b["dem_votes"] + b["rep_votes"] + b["other_votes"]
            dem, rep = b["dem_votes"], b["rep_votes"]
            major = dem + rep
            if major > 0:
                if rep > dem:
                    b["winner"], b["margin"], b["margin_pct"] = (
                        "REP",
                        rep - dem,
                        round((rep - dem) / major * 100, 4),
                    )
                elif dem > rep:
                    b["winner"], b["margin"], b["margin_pct"] = (
                        "DEM",
                        dem - rep,
                        round((dem - rep) / major * 100, 4),
                    )
                else:
                    b["winner"], b["margin"], b["margin_pct"] = "TIE", 0.0, 0.0
                b["color"] = color_for_winner(b["winner"], b["margin_pct"])
    return [buckets[k] for k in order]


def rebuild_office(src: pd.DataFrame, office: str, poly: dict[str, set[str]]) -> list[dict]:
    party, dem_c, rep_c = build_precinct_party_votes(src, office, election_year=2020)
    return party_df_to_rows(party, 2020, dem_c, rep_c, poly)


def patch_contest_file(path: Path, new_by_county: dict[str, list[dict]]) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    old_rows = data.get("rows") or []
    kept = [r for r in old_rows if norm(r.get("county")).split(" - ", 1)[0] not in TARGET_COUNTIES]
    added: list[dict] = []
    for county in sorted(TARGET_COUNTIES):
        added.extend(new_by_county.get(county, []))
    rows = kept + added
    rows.sort(key=lambda r: norm(r.get("county")))
    dem = sum(float(r.get("dem_votes") or 0) for r in rows)
    rep = sum(float(r.get("rep_votes") or 0) for r in rows)
    oth = sum(float(r.get("other_votes") or 0) for r in rows)
    meta = dict(data.get("meta") or {})
    meta["dem_total"] = dem
    meta["rep_total"] = rep
    meta["other_total"] = oth
    meta["total_votes"] = dem + rep + oth
    meta["nongeo_allocation_mode"] = "precinct_candidate"
    meta["oe_county_rebuild"] = ",".join(sorted(TARGET_COUNTIES))
    data["meta"] = meta
    data["rows"] = rows
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {
        "file": path.name,
        "kept": len(kept),
        "added": len(added),
        "total": len(rows),
    }


def coverage_report(label: str, rows: list[dict], poly: dict[str, set[str]]) -> None:
    print(f"\n=== {label} ===")
    for county in sorted(TARGET_COUNTIES):
        crows = [r for r in rows if norm(r.get("county")).startswith(county + " - ")]
        codes = {norm(r["county"]).split(" - ", 1)[-1] for r in crows}
        p = poly[county]
        dem = sum(float(r["dem_votes"]) for r in crows)
        rep = sum(float(r["rep_votes"]) for r in crows)
        dmaj = sum(1 for r in crows if float(r["dem_votes"]) > float(r["rep_votes"]))
        rmaj = sum(1 for r in crows if float(r["rep_votes"]) > float(r["dem_votes"]))
        print(
            f"{county}: n={len(crows)} covered={len(codes & p)}/{len(p)} "
            f"empty={sorted(p - codes)} Dmaj/Rmaj={dmaj}/{rmaj} "
            f"m={100 * (dem - rep) / (dem + rep) if dem + rep else float('nan'):.2f}%"
        )


def main() -> None:
    poly = load_poly()
    src = load_oe()
    # Sanity: print non-geo flags for Bladen/Richmond samples
    for county in TARGET_COUNTIES:
        labs = sorted(src.loc[src["county"] == county, "precinct"].unique())
        ng = [x for x in labs if is_non_geographic_precinct(x, county)]
        geo = [x for x in labs if not is_non_geographic_precinct(x, county)]
        print(f"{county}: OE geo={len(geo)} nongeo={len(ng)} nongeo_sample={ng[:8]}")

    # BEFORE snapshot from president
    before = json.loads((CONTESTS_DIR / "president_2020.json").read_text(encoding="utf-8"))
    coverage_report("BEFORE president", before["rows"], poly)

    # Build per-office county replacement maps for every contest file that has a matching OE office
    offices = sorted(src["office"].dropna().unique())
    # Map contest filename stem -> OE office string via infer_office_key
    office_by_key: dict[str, str] = {}
    for office in offices:
        key = infer_office_key(office)
        if key:
            office_by_key[key] = office

    # Always rebuild president + statewide offices present in OE
    contest_files = sorted(CONTESTS_DIR.glob("*_2020.json"))
    for path in contest_files:
        stem = path.name[: -len("_2020.json")]
        office = office_by_key.get(stem)
        if not office:
            # Try fuzzy: president
            if stem == "president":
                office = next((o for o in offices if "PRESIDENT" in o.upper()), None)
            elif stem == "us_senate":
                office = next((o for o in offices if "US SENATE" in o.upper() or "U.S. SENATE" in o.upper()), None)
            else:
                # skip courts if not in OE batch the same way — still try key match
                continue
        if not office:
            print(f"skip {path.name}: no OE office")
            continue
        party_rows = rebuild_office(src, office, poly)
        by_county: dict[str, list[dict]] = {c: [] for c in TARGET_COUNTIES}
        for r in party_rows:
            c = norm(r["county"]).split(" - ", 1)[0]
            by_county.setdefault(c, []).append(r)
        # Verify county totals ≈ OE for president once
        stats = patch_contest_file(path, by_county)
        print(f"patched {stats}")

    after = json.loads((CONTESTS_DIR / "president_2020.json").read_text(encoding="utf-8"))
    coverage_report("AFTER president", after["rows"], poly)

    # County margin vs OE for president
    print("\n=== margin check vs OE (president) ===")
    oe = src[src["office"].str.upper().str.contains("PRESIDENT")].copy()
    oe["pg"] = oe["party"].map(party_group)
    for county in sorted(TARGET_COUNTIES):
        c = oe[oe["county"] == county]
        od = float(c.loc[c["pg"] == "dem_votes", "votes"].sum())
        or_ = float(c.loc[c["pg"] == "rep_votes", "votes"].sum())
        rows = [r for r in after["rows"] if norm(r["county"]).startswith(county + " - ")]
        ad = sum(float(r["dem_votes"]) for r in rows)
        ar = sum(float(r["rep_votes"]) for r in rows)
        print(
            f"{county}: OE m={100*(od-or_)/(od+or_):.3f}% atlas m={100*(ad-ar)/(ad+ar):.3f}% "
            f"dD={ad-od:.1f} dR={ar-or_:.1f}"
        )


if __name__ == "__main__":
    main()
