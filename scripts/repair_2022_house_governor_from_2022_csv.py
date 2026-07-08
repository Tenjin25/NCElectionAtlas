#!/usr/bin/env python3
"""Repair 2022-line State House 2008 Governor districts from the 2022-line CSV.

This avoids using 2024-line district shares. It preserves each target district's
existing total_votes and reapportions Dem/Rep/Other using the 2022 State House
2008 Governor CSV that was previously uploaded.
"""
from __future__ import annotations

import csv
import io
import json
import subprocess
from pathlib import Path

TARGET = Path("data/district_contests/state_house_governor_2008.json")
CSV_REF = "74797d429c21829306dc0da81f8195a3efde9ca5:data/calibration_uploads/NC-2022-State-House-district-statistics 2008 gov.csv"
DISTRICTS = ["63", "64", *[str(i) for i in range(98, 113)]]


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


def norm_id(raw: str) -> str:
    v = str(raw or "").strip().strip('"')
    if not v or v.upper() == "UN":
        return ""
    try:
        return str(int(float(v)))
    except ValueError:
        return v


def load_csv_shares() -> dict[str, tuple[float, float, float]]:
    text = subprocess.check_output(["git", "show", CSV_REF], text=True)
    out: dict[str, tuple[float, float, float]] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        district = norm_id(row.get("ID", ""))
        if not district:
            continue
        dem = float(row.get("Dem", 0) or 0)
        rep = float(row.get("Rep", 0) or 0)
        oth = float(row.get("Oth", 0) or 0)
        total = dem + rep + oth
        if total > 0:
            out[district] = (dem / total, rep / total, oth / total)
    return out


def apportion(total: int, shares: tuple[float, float, float]) -> tuple[int, int, int]:
    raw = [total * x for x in shares]
    base = [int(x) for x in raw]
    remainder = total - sum(base)
    frac = sorted(((raw[i] - base[i], i) for i in range(3)), key=lambda x: (x[0], -x[1]), reverse=True)
    for _, idx in frac[:remainder]:
        base[idx] += 1
    return base[0], base[1], base[2]


def update_row(row: dict, shares: tuple[float, float, float]) -> None:
    total = int(row.get("total_votes", 0) or 0)
    if total <= 0:
        total = int(row.get("dem_votes", 0) or 0) + int(row.get("rep_votes", 0) or 0) + int(row.get("other_votes", 0) or 0)
    if total <= 0:
        return
    dem, rep, oth = apportion(total, shares)
    margin = rep - dem
    margin_pct = round((margin / total) * 100.0, 2)
    row["dem_votes"] = dem
    row["rep_votes"] = rep
    row["other_votes"] = oth
    row["total_votes"] = total
    row["margin"] = margin
    row["margin_pct"] = float(margin_pct)
    row["winner"] = "REP" if rep > dem else ("DEM" if dem > rep else "TIE")
    row["competitiveness"] = {"color": calculate_competitiveness(margin_pct)}


def main() -> None:
    raw = TARGET.read_text(encoding="utf-8")
    payload = json.loads(raw)
    results = payload["general"]["results"]
    shares = load_csv_shares()
    patched = []
    for district in DISTRICTS:
        if district in results and district in shares:
            update_row(results[district], shares[district])
            patched.append(district)
    TARGET.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"patched": {str(TARGET): patched}}, indent=2))


if __name__ == "__main__":
    main()
