"""
Split 2020 Iredell DV1A1A contest rows into DV1A1A + DV3A using
2020->2024 precinct overlap shares derived from SBE precinct geometries.

This patch is intentionally narrow:
- only applies to data/contests/*_2020.json
- only when a file has "IREDELL - DV1A1A" and does not already have "IREDELL - DV3A"
- only splits into DV1A1A and DV3A (renormalized from old DV1-A overlap)
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import geopandas as gpd


ROOT = Path(__file__).resolve().parent.parent
CONTESTS_DIR = ROOT / "data" / "contests"
SBE_2020 = ROOT / "data" / "census" / "SBE_PRECINCTS_20201018" / "SBE_PRECINCTS_20201018.shp"
SBE_2024 = ROOT / "data" / "census" / "SBE_PRECINCTS_20240723" / "SBE_PRECINCTS_20240723.shp"


def calc_color(margin_pct: float) -> str:
    abs_margin = abs(margin_pct)
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
    return "#f7f7f7"


def calc_dv3a_share() -> float:
    old = gpd.read_file(SBE_2020)
    new = gpd.read_file(SBE_2024)

    old = old[old["county_nam"].astype(str).str.upper() == "IREDELL"][["prec_id", "geometry"]].copy()
    new = new[new["county_nam"].astype(str).str.upper() == "IREDELL"][["prec_id", "geometry"]].copy()

    old["prec_id"] = old["prec_id"].astype(str).str.upper()
    new["prec_id"] = new["prec_id"].astype(str).str.upper()

    old = old[old["prec_id"] == "DV1-A"].copy()
    new = new[new["prec_id"].isin(["DV1A1A", "DV3A"])].copy()
    if old.empty or new.empty:
        raise RuntimeError("Could not locate required Iredell precincts (DV1-A / DV1A1A / DV3A).")

    old = old.to_crs("EPSG:2264")
    if new.crs != old.crs:
        new = new.to_crs(old.crs)

    inter = gpd.overlay(old, new, how="intersection", keep_geom_type=False)
    inter["a"] = inter.geometry.area
    inter = inter[inter["a"] > 0].copy()
    if inter.empty:
        raise RuntimeError("No geometry overlap found for DV1-A -> (DV1A1A,DV3A).")

    # old row is DV1-A only, so normalize overlap to compute split between DV1A1A and DV3A.
    by_new = inter.groupby("prec_id_2", as_index=False)["a"].sum()
    area_dv3a = float(by_new.loc[by_new["prec_id_2"] == "DV3A", "a"].sum())
    area_dv1a1a = float(by_new.loc[by_new["prec_id_2"] == "DV1A1A", "a"].sum())
    denom = area_dv3a + area_dv1a1a
    if denom <= 0:
        raise RuntimeError("Invalid split denominator for DV1-A overlap.")
    return area_dv3a / denom


def update_row_stats(row: dict) -> None:
    dem = int(row.get("dem_votes", 0) or 0)
    rep = int(row.get("rep_votes", 0) or 0)
    oth = int(row.get("other_votes", 0) or 0)
    total = dem + rep + oth
    margin = rep - dem
    margin_pct = (margin / total * 100.0) if total else 0.0
    row["total_votes"] = total
    row["margin"] = margin
    row["margin_pct"] = round(margin_pct, 4)
    row["winner"] = "REP" if margin > 0 else ("DEM" if margin < 0 else "TIE")
    row["color"] = calc_color(margin_pct)


def split_int_pair(value: int, share_to_second: float) -> tuple[int, int]:
    second = int(round(value * share_to_second))
    first = int(value - second)
    return first, second


def apply_split_to_file(path: Path, dv3a_share: float) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return False

    has_dv3a = any(str(r.get("county", "")).upper() == "IREDELL - DV3A" for r in rows)
    if has_dv3a:
        return False

    idx = next((i for i, r in enumerate(rows) if str(r.get("county", "")).upper() == "IREDELL - DV1A1A"), None)
    if idx is None:
        return False

    base = copy.deepcopy(rows[idx])
    dv3 = copy.deepcopy(rows[idx])
    base["county"] = "IREDELL - DV1A1A"
    dv3["county"] = "IREDELL - DV3A"

    for key in ("dem_votes", "rep_votes", "other_votes"):
        v = int(base.get(key, 0) or 0)
        v_base, v_dv3 = split_int_pair(v, dv3a_share)
        base[key] = v_base
        dv3[key] = v_dv3

    update_row_stats(base)
    update_row_stats(dv3)

    rows[idx] = base
    rows.insert(idx + 1, dv3)
    payload["rows"] = rows
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return True


def main() -> None:
    dv3a_share = calc_dv3a_share()
    changed = []
    for path in sorted(CONTESTS_DIR.glob("*_2020.json")):
        if apply_split_to_file(path, dv3a_share):
            changed.append(path.name)
    print(f"DV3A split share (DV1-A -> DV3A): {dv3a_share:.6f}")
    print(f"Updated files: {len(changed)}")
    for name in changed:
        print(name)


if __name__ == "__main__":
    main()

