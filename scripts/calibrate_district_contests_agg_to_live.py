#!/usr/bin/env python3
"""Calibrate sandbox district contest margins to DRA stats CSVs and/or live layers.

Preserves each district's shatter total_votes; retunes Dem/Rep/Other so margin_pct
matches the DRA-calibrated target. Vote totals need not match live.

Typical usage:
  python scripts/calibrate_district_contests_agg_to_live.py \\
    --agg-dir data/district_contests_agg \\
    --live-dir data/district_contests \\
    --years 2012,2014,2016,2018,2020,2022,2024
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from calibrate_district_slices_to_stats_margins import (  # noqa: E402
    StatsRow,
    calculate_competitiveness,
    calibrate_slice,
    load_stats,
    normalize_district_id,
    solve_votes_for_margin,
)

# Explicit DRA district-statistics paths (2022 lines unless noted).
# Also discovers aliases via resolve_stats_csv() for judicial / Downloads imports.
STATS_CSV_BY_KEY: dict[tuple[int, str, str], Path] = {
    (2004, "state_house", "president"): Path(
        "data/NC-2022-State-House-district-statistics 2004 pres.csv"
    ),
    (2004, "state_senate", "president"): Path(
        "data/NC-2022-State-Senate-district-statistics 2004 pres.csv"
    ),
    (2020, "state_house", "president"): Path("data/district-statistics 2020 Pres State House 2022.csv"),
    (2020, "state_house", "governor"): Path("data/district-statistics 2020 Gov State House 2022.csv"),
    (2020, "state_house", "lieutenant_governor"): Path("data/district-statistics 2020 LtGov State House 2022.csv"),
    (2020, "state_house", "us_senate"): Path("data/district-statistics 2020 USSenate State House 2022.csv"),
    (2020, "state_house", "auditor"): Path("data/district-statistics 2020 Auditor State House 2022.csv"),
    (2020, "state_house", "treasurer"): Path("data/district-statistics 2020 Treasurer State House 2022.csv"),
    (2020, "state_house", "secretary_of_state"): Path("data/district-statistics 2020 SOS State House 2022.csv"),
    # Statewide appellate / supreme (drop DRA exports into data/ using these names, or import aliases).
    (2020, "state_house", "nc_supreme_court_chief_justice_seat_01"): Path(
        "data/district-statistics 2020 SC_CJ_01 State House 2022.csv"
    ),
    (2020, "state_house", "nc_supreme_court_associate_justice_seat_02"): Path(
        "data/district-statistics 2020 SC_AJ_02 State House 2022.csv"
    ),
    (2020, "state_house", "nc_supreme_court_associate_justice_seat_04"): Path(
        "data/district-statistics 2020 SC_AJ_04 State House 2022.csv"
    ),
    (2020, "state_house", "nc_court_of_appeals_judge_seat_04"): Path(
        "data/district-statistics 2020 COA_04 State House 2022.csv"
    ),
    (2020, "state_house", "nc_court_of_appeals_judge_seat_05"): Path(
        "data/district-statistics 2020 COA_05 State House 2022.csv"
    ),
    (2020, "state_house", "nc_court_of_appeals_judge_seat_06"): Path(
        "data/district-statistics 2020 COA_06 State House 2022.csv"
    ),
    (2020, "state_house", "nc_court_of_appeals_judge_seat_07"): Path(
        "data/district-statistics 2020 COA_07 State House 2022.csv"
    ),
    (2020, "state_house", "nc_court_of_appeals_judge_seat_13"): Path(
        "data/district-statistics 2020 COA_13 State House 2022.csv"
    ),
    (2020, "state_senate", "president"): Path("data/district-statistics 2020 Pres State Senate 2022.csv"),
    (2020, "congressional", "president"): Path("data/district-statistics 2020 Pres Congress.csv"),
    (2024, "state_house", "president"): Path("data/district-statistics 2024 Pres State House 2022.csv"),
    (2024, "congressional", "president"): Path("data/district-statistics 2024 Pres Congress.csv"),
    (2024, "state_house", "governor"): Path("data/district-statistics 2024 gov.csv"),
}

# Keep the July 28 geographic rebuild for 2022-line House districts outside
# Mecklenburg and Buncombe. District contest files are aggregates, so districts
# touching either county are calibrated as a whole.
PARTIAL_STATS_DISTRICTS: dict[tuple[int, str, str], frozenset[str]] = {
    (2004, "state_house", "president"): frozenset(
        {
            "88",
            "92",
            "98",
            "99",
            "100",
            "101",
            "102",
            "103",
            "104",
            "105",
            "106",
            "107",
            "112",
            "114",
            "115",
            "116",
        }
    )
}

# DRA Downloads short labels -> contest_type (State House / 2022 lines).
DRA_DOWNLOAD_ALIAS_TO_CONTEST: dict[str, str] = {
    "president": "president",
    "pres": "president",
    "gov": "governor",
    "governor": "governor",
    "lt gov": "lieutenant_governor",
    "ltgov": "lieutenant_governor",
    "lieutenant governor": "lieutenant_governor",
    "us senate": "us_senate",
    "ussenate": "us_senate",
    "senate": "us_senate",
    "auditor": "auditor",
    "treasurer": "treasurer",
    "sos": "secretary_of_state",
    "secretary of state": "secretary_of_state",
    # Judicial — match flexible DRA export labels once dropped in Downloads.
    "sc cj": "nc_supreme_court_chief_justice_seat_01",
    "sc cj 01": "nc_supreme_court_chief_justice_seat_01",
    "chief justice": "nc_supreme_court_chief_justice_seat_01",
    "sc aj 02": "nc_supreme_court_associate_justice_seat_02",
    "sc seat 02": "nc_supreme_court_associate_justice_seat_02",
    "sc aj 04": "nc_supreme_court_associate_justice_seat_04",
    "sc seat 04": "nc_supreme_court_associate_justice_seat_04",
    "coa 04": "nc_court_of_appeals_judge_seat_04",
    "coa seat 04": "nc_court_of_appeals_judge_seat_04",
    "coa 05": "nc_court_of_appeals_judge_seat_05",
    "coa seat 05": "nc_court_of_appeals_judge_seat_05",
    "coa 06": "nc_court_of_appeals_judge_seat_06",
    "coa seat 06": "nc_court_of_appeals_judge_seat_06",
    "coa 07": "nc_court_of_appeals_judge_seat_07",
    "coa seat 07": "nc_court_of_appeals_judge_seat_07",
    "coa 13": "nc_court_of_appeals_judge_seat_13",
    "coa seat 13": "nc_court_of_appeals_judge_seat_13",
}

CANONICAL_STATS_NAME: dict[str, str] = {
    "president": "Pres",
    "governor": "Gov",
    "lieutenant_governor": "LtGov",
    "us_senate": "USSenate",
    "auditor": "Auditor",
    "treasurer": "Treasurer",
    "secretary_of_state": "SOS",
    "nc_supreme_court_chief_justice_seat_01": "SC_CJ_01",
    "nc_supreme_court_associate_justice_seat_02": "SC_AJ_02",
    "nc_supreme_court_associate_justice_seat_04": "SC_AJ_04",
    "nc_court_of_appeals_judge_seat_04": "COA_04",
    "nc_court_of_appeals_judge_seat_05": "COA_05",
    "nc_court_of_appeals_judge_seat_06": "COA_06",
    "nc_court_of_appeals_judge_seat_07": "COA_07",
    "nc_court_of_appeals_judge_seat_13": "COA_13",
}


def import_dra_downloads(
    downloads_dir: Path,
    *,
    year: int = 2020,
    scope: str = "state_house",
    lines: str = "2022",
) -> list[tuple[str, Path]]:
    """Copy DRA Exports from Downloads into data/ with canonical names."""
    import shutil

    if scope != "state_house" or lines != "2022":
        return []
    pattern = f"NC-2022-State-House-district-statistics {year} *.csv"
    imported: list[tuple[str, Path]] = []
    for src in sorted(downloads_dir.glob(pattern)):
        # filename: NC-2022-State-House-district-statistics 2020 gov.csv
        stem = src.name
        prefix = f"NC-2022-State-House-district-statistics {year} "
        if not stem.lower().startswith(prefix.lower()) or not stem.lower().endswith(".csv"):
            continue
        label = stem[len(prefix) : -4].strip().lower()
        contest = DRA_DOWNLOAD_ALIAS_TO_CONTEST.get(label)
        if contest is None:
            # Flexible judicial: "coa 04", "sc aj 02", etc.
            for alias, ct in DRA_DOWNLOAD_ALIAS_TO_CONTEST.items():
                if label == alias or label.replace("-", " ") == alias:
                    contest = ct
                    break
        if contest is None:
            print(f"  (skip unrecognized DRA export label: {label!r} from {src.name})")
            continue
        short = CANONICAL_STATS_NAME.get(contest, contest)
        dst = Path(f"data/district-statistics {year} {short} State House {lines}.csv")
        shutil.copy2(src, dst)
        STATS_CSV_BY_KEY[(year, scope, contest)] = dst
        imported.append((contest, dst))
        print(f"  imported {src.name} -> {dst} ({contest})")
    return imported


def resolve_stats_csv(year: int, scope: str, contest_type: str) -> Path | None:
    key = (year, scope, contest_type)
    path = STATS_CSV_BY_KEY.get(key)
    if path is not None and path.exists():
        return path
    if scope == "state_house":
        aliases = sorted(
            {
                alias
                for alias, mapped_contest in DRA_DOWNLOAD_ALIAS_TO_CONTEST.items()
                if mapped_contest == contest_type
            }
        )
        for alias in aliases:
            cand = Path(f"data/calibration_csvs/NC-2022-State-House-district-statistics {year} {alias}.csv")
            if cand.exists():
                STATS_CSV_BY_KEY[key] = cand
                return cand
    short = CANONICAL_STATS_NAME.get(contest_type)
    if short and scope == "state_house":
        cand = Path(f"data/district-statistics {year} {short} State House 2022.csv")
        if cand.exists():
            STATS_CSV_BY_KEY[key] = cand
            return cand
    return path if path is not None and path.exists() else None


DEFAULT_SKIP_CSV = Path("data/mappings/snapshot_margin_trust_skip.csv")
DEFAULT_OVERRIDE_CSV = Path("data/mappings/margin_override_targets.csv")


def is_judicial_contest(contest_type: str) -> bool:
    c = str(contest_type or "")
    return c.startswith("nc_court_of_appeals") or c.startswith("nc_supreme_court")


def load_snapshot_skip_keys(path: Path) -> set[tuple[int, str, str]]:
    """Contests whose existing_snapshot margins are known-bad; keep shatter unless overridden."""
    out: set[tuple[int, str, str]] = set()
    if not path.exists():
        return out
    import csv

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                year = int(str(row.get("year") or "").strip())
            except ValueError:
                continue
            scope = str(row.get("scope") or "").strip()
            contest_type = str(row.get("contest_type") or "").strip()
            if year and scope and contest_type:
                out.add((year, scope, contest_type))
    return out


def load_margin_overrides(path: Path) -> dict[tuple[int, str, str], dict[str, float]]:
    """Optional per-district target margin_pct (JSON convention: + = Rep lead)."""
    out: dict[tuple[int, str, str], dict[str, float]] = {}
    if not path.exists():
        return out
    import csv

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                year = int(str(row.get("year") or "").strip())
                target = float(str(row.get("target_margin_pct") or "").strip())
            except ValueError:
                continue
            scope = str(row.get("scope") or "").strip()
            contest_type = str(row.get("contest_type") or "").strip()
            district = normalize_district_id(row.get("district"))
            if not (year and scope and contest_type and district):
                continue
            out.setdefault((year, scope, contest_type), {})[district] = target
    return out


def stats_rows_from_margin_targets(
    target_json: Path,
    targets: dict[str, float],
    *,
    precision: int,
) -> dict[str, StatsRow]:
    """Build StatsRows for listed districts only; uses current other-share / totals from agg."""
    payload = json.loads(target_json.read_text(encoding="utf-8"))
    results = (payload.get("general") or {}).get("results") or {}
    out: dict[str, StatsRow] = {}
    for raw_id, row in results.items():
        if not isinstance(row, dict):
            continue
        district = normalize_district_id(raw_id)
        if district not in targets:
            continue
        dem = float(row.get("dem_votes") or 0)
        rep = float(row.get("rep_votes") or 0)
        oth = float(row.get("other_votes") or 0)
        total = dem + rep + oth
        if total <= 0:
            continue
        other_share = oth / total
        # Approximate dem/rep shares around the target margin for solver scoring.
        # margin_pct = (rep-dem)/total*100 => dem_share - rep_share = -target/100
        # dem+rep = 1-other; solve shares.
        two = 1.0 - other_share
        # (rep-dem) = target/100 * total / total = target/100; with dem+rep=two:
        # rep = (two + target/100)/2, dem = (two - target/100)/2
        t = targets[district] / 100.0
        dem_share = max(0.0, (two - t) / 2.0)
        rep_share = max(0.0, (two + t) / 2.0)
        s = dem_share + rep_share + other_share
        if s > 0:
            dem_share, rep_share, other_share = dem_share / s, rep_share / s, other_share / s
        out[district] = StatsRow(
            district=district,
            dem_share=dem_share,
            rep_share=rep_share,
            other_share=other_share,
            target_margin_pct=targets[district],
            target_margin_display=round(targets[district], precision),
            source_total_votes=None,
        )
    return out


def parse_years(raw: str) -> set[int] | None:
    if not str(raw or "").strip():
        return None
    out: set[int] = set()
    for token in raw.split(","):
        t = token.strip()
        if t:
            out.add(int(t))
    return out


def stats_rows_from_live_slice(live_payload: dict[str, Any], *, precision: int) -> dict[str, StatsRow]:
    """Build StatsRow targets from a live (DRA-calibrated) contest JSON."""
    results = (live_payload.get("general") or {}).get("results") or {}
    out: dict[str, StatsRow] = {}
    for raw_id, row in results.items():
        if not isinstance(row, dict):
            continue
        district = normalize_district_id(raw_id)
        if not district:
            continue
        dem = float(row.get("dem_votes") or 0)
        rep = float(row.get("rep_votes") or 0)
        oth = float(row.get("other_votes") or 0)
        total = dem + rep + oth
        if total <= 0:
            continue
        dem_share, rep_share, other_share = dem / total, rep / total, oth / total
        if "margin_pct" in row and row["margin_pct"] is not None:
            target_margin_pct = float(row["margin_pct"])
        else:
            target_margin_pct = ((rep - dem) / total) * 100.0
        out[district] = StatsRow(
            district=district,
            dem_share=dem_share,
            rep_share=rep_share,
            other_share=other_share,
            target_margin_pct=target_margin_pct,
            target_margin_display=round(target_margin_pct, precision),
            source_total_votes=None,
        )
    return out


def margin_delta_summary(target_json: Path, stats_rows: dict[str, StatsRow]) -> dict[str, Any]:
    payload = json.loads(target_json.read_text(encoding="utf-8"))
    results = (payload.get("general") or {}).get("results") or {}
    deltas: list[float] = []
    for raw_id, row in results.items():
        if not isinstance(row, dict):
            continue
        district = normalize_district_id(raw_id)
        stats = stats_rows.get(district)
        if stats is None:
            continue
        total = float(row.get("total_votes") or 0)
        if total <= 0:
            dem = float(row.get("dem_votes") or 0)
            rep = float(row.get("rep_votes") or 0)
            oth = float(row.get("other_votes") or 0)
            total = dem + rep + oth
        if total <= 0:
            continue
        if row.get("margin_pct") is not None:
            margin_pct = float(row.get("margin_pct") or 0)
        else:
            dem = float(row.get("dem_votes") or 0)
            rep = float(row.get("rep_votes") or 0)
            margin_pct = ((rep - dem) / total) * 100.0
        deltas.append(margin_pct - stats.target_margin_display)
    if not deltas:
        return {"rows": 0, "mean_abs": None, "max_abs": None}
    return {
        "rows": len(deltas),
        "mean_abs": sum(abs(d) for d in deltas) / len(deltas),
        "max_abs": max(abs(d) for d in deltas),
    }


def calibrate_slice_from_stats_rows(
    target_json: Path,
    stats_rows: dict[str, StatsRow],
    *,
    precision: int = 2,
    margin_basis: str = "total",
    audit_only: bool = False,
) -> dict[str, Any]:
    raw_text = target_json.read_text(encoding="utf-8")
    payload = json.loads(raw_text)
    results = payload.get("general", {}).get("results", {})
    if not isinstance(results, dict):
        raise ValueError(f"Unexpected payload format in {target_json}")

    calibrated = 0
    exact_matches = 0
    missing = 0
    misses: list[dict[str, Any]] = []
    max_display_delta = 0.0
    max_district: str | None = None

    for raw_district, row in results.items():
        district = normalize_district_id(raw_district)
        stats = stats_rows.get(district)
        if not stats:
            missing += 1
            continue
        if not isinstance(row, dict):
            continue

        old_dem = int(row.get("dem_votes", 0) or 0)
        old_rep = int(row.get("rep_votes", 0) or 0)
        old_oth = int(row.get("other_votes", 0) or 0)
        total_votes = int(row.get("total_votes", old_dem + old_rep + old_oth) or 0)
        if total_votes <= 0:
            continue

        solved = solve_votes_for_margin(
            total_votes=total_votes,
            stats=stats,
            precision=precision,
            margin_basis=margin_basis,
            exact_rounded_margin=True,
            other_search_radius=50,
            margin_search_radius=500,
        )
        display_delta = abs(solved.margin_pct - stats.target_margin_display)
        if display_delta == 0:
            exact_matches += 1
        else:
            misses.append(
                {
                    "district": district,
                    "target_margin_pct": stats.target_margin_display,
                    "output_margin_pct": solved.margin_pct,
                    "delta": round(display_delta, precision + 2),
                }
            )
        if display_delta > max_display_delta:
            max_display_delta = display_delta
            max_district = district

        if not audit_only:
            row["dem_votes"] = solved.dem_votes
            row["rep_votes"] = solved.rep_votes
            row["other_votes"] = solved.other_votes
            row["total_votes"] = int(total_votes)
            row["margin"] = solved.margin
            row["margin_pct"] = solved.margin_pct
            row["winner"] = (
                "REP"
                if solved.rep_votes > solved.dem_votes
                else ("DEM" if solved.dem_votes > solved.rep_votes else "TIE")
            )
            if isinstance(row.get("competitiveness"), dict):
                row["competitiveness"]["color"] = calculate_competitiveness(solved.margin_pct)
            else:
                row["competitiveness"] = {"color": calculate_competitiveness(solved.margin_pct)}

        calibrated += 1

    if not audit_only:
        meta = payload.setdefault("meta", {})
        if isinstance(meta, dict):
            meta["margin_calibrated_to"] = "dra_stats_or_live"
        was_pretty = ("\n" in raw_text.strip()) and (len(raw_text.strip().splitlines()) > 1)
        if was_pretty:
            out_text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        else:
            out_text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        target_json.write_text(out_text, encoding="utf-8")

    return {
        "target_json": str(target_json),
        "calibrated": calibrated,
        "exact_rounded_margin_matches": exact_matches,
        "missing_stats_rows": missing,
        "max_display_delta_pct": round(max_display_delta, precision + 2),
        "max_display_delta_district": max_district,
        "miss_count": len(misses),
        "misses": misses[:15],
        "audit_only": audit_only,
    }


def calibrate_agg_dir(
    *,
    agg_dir: Path,
    live_dir: Path,
    president_live_dir: Path | None,
    years: set[int] | None,
    audit_only: bool,
    prefer_stats_csv: bool,
    skip_csv: Path,
    override_csv: Path,
) -> list[dict[str, Any]]:
    """Hybrid margin calibration.

    Priority per contest file:
      1) DRA district-statistics CSV when available (and prefer_stats_csv)
      2) Explicit margin_override_targets
      3) President DRA-review JSON fallback when available
      4) Trusted snapshot/live fallback for recent non-judicial contests only
      5) Otherwise keep rebuilt shatter output
    """
    summaries: list[dict[str, Any]] = []
    live_files = {p.name: p for p in live_dir.glob("*_*_*.json") if p.name != "manifest.json"}
    president_live_files: dict[str, Path] = {}
    if president_live_dir is not None and president_live_dir.exists():
        president_live_files = {
            p.name: p
            for pattern in ("*_president_*.json", "*_governor_*.json")
            for p in president_live_dir.glob(pattern)
        }
    skip_keys = load_snapshot_skip_keys(skip_csv)
    overrides = load_margin_overrides(override_csv)
    if skip_keys:
        print(f"Snapshot trust-skip: {len(skip_keys)} contest key(s) from {skip_csv}")
    if overrides:
        print(f"Margin overrides: {sum(len(v) for v in overrides.values())} district target(s) from {override_csv}")

    for agg_path in sorted(agg_dir.glob("*_*_*.json")):
        if agg_path.name == "manifest.json":
            continue
        live_path = live_files.get(agg_path.name)
        try:
            payload = json.loads(agg_path.read_text(encoding="utf-8"))
        except Exception as exc:
            summaries.append({"target_json": str(agg_path), "error": str(exc)})
            continue

        year = int(payload.get("year") or 0)
        scope = str(payload.get("scope") or "")
        contest_type = str(payload.get("contest_type") or "")
        if year >= 2020 and contest_type == "president" and agg_path.name in president_live_files:
            live_path = president_live_files[agg_path.name]
            live_source = "president_dra_review"
        else:
            live_source = "snapshot"
        if years is not None and year not in years:
            continue

        key = (year, scope, contest_type)
        district_targets = overrides.get(key) or {}
        if district_targets:
            stats_rows = stats_rows_from_margin_targets(agg_path, district_targets, precision=2)
            summary = calibrate_slice_from_stats_rows(
                agg_path,
                stats_rows,
                precision=2,
                margin_basis="total",
                audit_only=audit_only,
            )
            summary["source"] = "override_targets"
            summary["file"] = agg_path.name
            summary["note"] = f"applied {len(stats_rows)} explicit district override(s)"
            summaries.append(summary)
            continue

        # Explicit district-statistics exports are trusted calibration targets
        # even for early years. Apply them after the geographic rebuild rather
        # than bypassing them under the general 2000-2006 keep-shatter policy.
        stats_csv = resolve_stats_csv(year, scope, contest_type)
        if prefer_stats_csv and stats_csv is not None and stats_csv.exists():
            partial_districts = PARTIAL_STATS_DISTRICTS.get(key)
            if partial_districts:
                stats_rows = {
                    district: row
                    for district, row in load_stats(
                        stats_csv, margin_basis="total", precision=2
                    ).items()
                    if district in partial_districts
                }
                summary = calibrate_slice_from_stats_rows(
                    agg_path,
                    stats_rows,
                    precision=2,
                    margin_basis="total",
                    audit_only=audit_only,
                )
                summary["note"] = (
                    "calibrated only districts touching Mecklenburg or Buncombe; "
                    "kept the July 28 geographic rebuild elsewhere"
                )
            else:
                summary = calibrate_slice(
                    agg_path,
                    stats_csv,
                    format_mode="auto",
                    precision=2,
                    margin_basis="total",
                    exact_rounded_margin=True,
                    total_votes_mode="existing",
                    total_votes_column="",
                    other_search_radius=50,
                    margin_search_radius=500,
                    audit_only=audit_only,
                )
            summary["source"] = f"{year}_csv"
            summary["file"] = agg_path.name
            summaries.append(summary)
            continue

        if year in {2000, 2002, 2004, 2006}:
            summaries.append(
                {
                    "target_json": str(agg_path),
                    "file": agg_path.name,
                    "source": "kept_shatter_by_policy",
                    "calibrated": 0,
                    "exact_rounded_margin_matches": 0,
                    "miss_count": 0,
                    "max_display_delta_pct": 0.0,
                    "note": "kept rebuilt 2000-2006 shatter output by policy",
                    "audit_only": audit_only,
                }
            )
            continue

        if year == 2020 and scope == "congressional" and contest_type == "president" and agg_path.name in president_live_files:
            live_payload = json.loads(president_live_files[agg_path.name].read_text(encoding="utf-8"))
            stats_rows = stats_rows_from_live_slice(live_payload, precision=2)
            summary = calibrate_slice_from_stats_rows(
                agg_path,
                stats_rows,
                precision=2,
                margin_basis="total",
                audit_only=audit_only,
            )
            summary["source"] = "2020_dra_review_president_congressional"
            summary["file"] = agg_path.name
            summaries.append(summary)
            continue

        if key in skip_keys:
            summaries.append(
                {
                    "target_json": str(agg_path),
                    "file": agg_path.name,
                    "source": "shatter_keep",
                    "calibrated": 0,
                    "exact_rounded_margin_matches": 0,
                    "miss_count": 0,
                    "max_display_delta_pct": 0.0,
                    "note": "skipped: snapshot margins untrusted; kept rebuilt output",
                    "audit_only": audit_only,
                }
            )
            continue

        if year != 2020 and year not in {2000, 2002, 2004, 2006} and contest_type in {"president", "governor"}:
            review_path = president_live_files.get(agg_path.name)
            if review_path is not None:
                live_payload = json.loads(review_path.read_text(encoding="utf-8"))
                stats_rows = stats_rows_from_live_slice(live_payload, precision=2)
                delta = margin_delta_summary(agg_path, stats_rows)
                mean_abs = delta.get("mean_abs")
                max_abs = delta.get("max_abs")
                if (
                    isinstance(mean_abs, (int, float))
                    and isinstance(max_abs, (int, float))
                    and (float(mean_abs) > 1.0 or float(max_abs) > 2.0)
                ):
                    summary = calibrate_slice_from_stats_rows(
                        agg_path,
                        stats_rows,
                        precision=2,
                        margin_basis="total",
                        audit_only=audit_only,
                    )
                    summary["source"] = "pres_gov_dra_review_large_delta"
                    summary["file"] = agg_path.name
                    summary["note"] = (
                        f"DRA-review delta exceeded threshold "
                        f"(mean_abs={float(mean_abs):.3f}, max_abs={float(max_abs):.3f})"
                    )
                    summaries.append(summary)
                else:
                    summaries.append(
                        {
                            "target_json": str(agg_path),
                            "file": agg_path.name,
                            "source": "kept_shatter_pres_gov_small_delta",
                            "calibrated": 0,
                            "exact_rounded_margin_matches": 0,
                            "miss_count": 0,
                            "max_display_delta_pct": 0.0,
                            "note": (
                                "kept rebuilt president/governor output; DRA-review delta within threshold "
                                f"(rows={delta.get('rows')}, mean_abs={mean_abs}, max_abs={max_abs})"
                            ),
                            "audit_only": audit_only,
                        }
                    )
                continue
            summaries.append(
                {
                    "target_json": str(agg_path),
                    "file": agg_path.name,
                    "source": "kept_shatter_no_target",
                    "calibrated": 0,
                    "exact_rounded_margin_matches": 0,
                    "miss_count": 0,
                    "max_display_delta_pct": 0.0,
                    "note": "kept rebuilt president/governor output; no DRA-review target",
                    "audit_only": audit_only,
                }
            )
            continue

        if is_judicial_contest(contest_type):
            summaries.append(
                {
                    "target_json": str(agg_path),
                    "file": agg_path.name,
                    "source": "shatter_keep",
                    "calibrated": 0,
                    "exact_rounded_margin_matches": 0,
                    "miss_count": 0,
                    "max_display_delta_pct": 0.0,
                    "note": "kept rebuilt judicial output; no reliable post-override target",
                    "audit_only": audit_only,
                }
            )
            continue

        if year < 2020:
            summaries.append(
                {
                    "target_json": str(agg_path),
                    "file": agg_path.name,
                    "source": "shatter_keep",
                    "calibrated": 0,
                    "exact_rounded_margin_matches": 0,
                    "miss_count": 0,
                    "max_display_delta_pct": 0.0,
                    "note": "kept rebuilt early-year output; no explicit calibration target",
                    "audit_only": audit_only,
                }
            )
            continue

        summaries.append(
            {
                "target_json": str(agg_path),
                "file": agg_path.name,
                "source": "kept_shatter_no_target",
                "calibrated": 0,
                "exact_rounded_margin_matches": 0,
                "miss_count": 0,
                "max_display_delta_pct": 0.0,
                "note": "kept rebuilt output; no explicit trusted calibration target",
                "audit_only": audit_only,
            }
        )

    return summaries


def main() -> None:
    p = argparse.ArgumentParser(
        description="Hybrid-calibrate sandbox district margins (DRA stats > snapshot > overrides > shatter)."
    )
    p.add_argument("--agg-dir", type=Path, default=Path("data/district_contests_agg"))
    p.add_argument(
        "--live-dir",
        type=Path,
        default=Path("data/district_contests_existing_snapshot"),
        help="existing_snapshot (or live) JSON margins used when no DRA stats CSV",
    )
    p.add_argument(
        "--president-live-dir",
        type=Path,
        default=Path("data/district_contests_dra_review"),
        help="Preferred president-contest fallback margin baseline when no DRA stats CSV exists.",
    )
    p.add_argument("--years", type=str, default="")
    p.add_argument("--audit-only", action="store_true")
    p.add_argument(
        "--no-stats-csv",
        action="store_true",
        help="Do not use district-statistics CSVs (snapshot / skip / overrides only).",
    )
    p.add_argument(
        "--skip-csv",
        type=Path,
        default=DEFAULT_SKIP_CSV,
        help="Contests whose snapshot margins are untrusted.",
    )
    p.add_argument(
        "--override-csv",
        type=Path,
        default=DEFAULT_OVERRIDE_CSV,
        help="Per-district target margin_pct for untrusted / corrected seats.",
    )
    p.add_argument(
        "--import-downloads",
        type=Path,
        default=None,
        help="Optional Downloads folder to import NC-2022-State-House-district-statistics YEAR *.csv "
        "(includes judicial aliases once present).",
    )
    p.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="Optional path to write calibration source/keep summary JSON.",
    )
    args = p.parse_args()

    if not args.agg_dir.exists():
        raise FileNotFoundError(args.agg_dir)
    if not args.live_dir.exists():
        raise FileNotFoundError(args.live_dir)

    years = parse_years(args.years)
    if args.import_downloads is not None:
        print(f"Importing DRA exports from {args.import_downloads}")
        for y in sorted(years or {2020}):
            import_dra_downloads(args.import_downloads, year=y)
    summaries = calibrate_agg_dir(
        agg_dir=args.agg_dir,
        live_dir=args.live_dir,
        president_live_dir=args.president_live_dir,
        years=years,
        audit_only=args.audit_only,
        prefer_stats_csv=not args.no_stats_csv,
        skip_csv=args.skip_csv,
        override_csv=args.override_csv,
    )
    n = len(summaries)
    by_src: dict[str, int] = {}
    for s in summaries:
        by_src[str(s.get("source") or "unknown")] = by_src.get(str(s.get("source") or "unknown"), 0) + 1
    cal = sum(int(s.get("calibrated") or 0) for s in summaries)
    exact = sum(int(s.get("exact_rounded_margin_matches") or 0) for s in summaries)
    misses = sum(int(s.get("miss_count") or 0) for s in summaries)
    print(f"Touched {n} slices ({cal} districts calibrated; exact={exact}; miss_count={misses})")
    print("sources:", ", ".join(f"{k}={v}" for k, v in sorted(by_src.items())))
    kept = [s for s in summaries if s.get("source") in {"shatter_keep", "override_targets"}]
    if kept:
        print(f"Untrusted-snapshot handling: {len(kept)}")
        for s in kept[:25]:
            print(f"  {s.get('file')}: source={s.get('source')} {s.get('note') or ''}")
    worst = sorted(
        (
            s
            for s in summaries
            if s.get("max_display_delta_pct") is not None and s.get("source") not in {"shatter_keep"}
        ),
        key=lambda s: float(s.get("max_display_delta_pct") or 0),
        reverse=True,
    )[:10]
    if worst:
        print("Largest per-file max |delta margin| among calibrated:")
        for s in worst:
            print(
                f"  {s.get('file')}: max_delta={s.get('max_display_delta_pct')} "
                f"district={s.get('max_display_delta_district')} source={s.get('source')}"
            )
    if args.summary_json is not None:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(
            json.dumps(
                {
                    "summary": {
                        "slices": n,
                        "districts_calibrated": cal,
                        "exact_rounded_margin_matches": exact,
                        "miss_count": misses,
                        "sources": by_src,
                    },
                    "kept_original": kept,
                    "worst_calibrated": worst,
                    "files": summaries,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {args.summary_json}")


if __name__ == "__main__":
    main()
