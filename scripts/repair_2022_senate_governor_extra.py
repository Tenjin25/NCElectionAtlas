#!/usr/bin/env python3
"""Patch extra suspicious 2022-line State Senate 2008 Governor districts."""
from __future__ import annotations

import json
from pathlib import Path

TARGET = Path("data/district_contests/state_senate_governor_2008.json")
SOURCE = Path("data/district_contests_2024_lines/state_senate_governor_2008.json")
DISTRICTS = ["13", "14", "15", "16", "17"]


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


def apportion(total: int, shares: tuple[float, float, float]) -> tuple[int, int, int]:
    raw = [total * x for x in shares]
    base = [int(x) for x in raw]
    remainder = total - sum(base)
    frac = sorted(((raw[i] - base[i], i) for i in range(3)), key=lambda x: (x[0], -x[1]), reverse=True)
    for _, idx in frac[:remainder]:
        base[idx] += 1
    return base[0], base[1], base[2]


def source_shares(row: dict) -> tuple[float, float, float]:
    dem = int(row.get("dem_votes", 0) or 0)
    rep = int(row.get("rep_votes", 0) or 0)
    oth = int(row.get("other_votes", 0) or 0)
    total = dem + rep + oth
    if total <= 0:
        raise ValueError("source row has no votes")
    return dem / total, rep / total, oth / total


def update_target_row(target_row: dict, source_row: dict) -> None:
    total = int(target_row.get("total_votes", 0) or 0)
    if total <= 0:
        total = int(target_row.get("dem_votes", 0) or 0) + int(target_row.get("rep_votes", 0) or 0) + int(target_row.get("other_votes", 0) or 0)
    dem, rep, oth = apportion(total, source_shares(source_row))
    margin = rep - dem
    margin_pct = round((margin / total) * 100.0, 2)
    target_row["dem_votes"] = dem
    target_row["rep_votes"] = rep
    target_row["other_votes"] = oth
    target_row["total_votes"] = total
    target_row["margin"] = margin
    target_row["margin_pct"] = float(margin_pct)
    target_row["winner"] = "REP" if rep > dem else ("DEM" if dem > rep else "TIE")
    target_row["competitiveness"] = {"color": calculate_competitiveness(margin_pct)}


def main() -> None:
    raw = TARGET.read_text(encoding="utf-8")
    target = json.loads(raw)
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    for district in DISTRICTS:
        update_target_row(target["general"]["results"][district], source["general"]["results"][district])
    out = json.dumps(target, indent=2, ensure_ascii=False) + "\n"
    TARGET.write_text(out, encoding="utf-8")
    print(json.dumps({"patched": {str(TARGET): DISTRICTS}}, indent=2))


if __name__ == "__main__":
    main()
