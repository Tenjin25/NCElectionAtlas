#!/usr/bin/env python3
from __future__ import annotations

"""
Calibrate district contest JSON slices to DRA-style district-statistics CSV margins.

This is stricter than calibrate_district_slices_from_stats_csv.py:
  - it can target the CSV's rounded district margin directly
  - it searches integer Dem/Rep/Other vote combinations so margin_pct and vote
    counts stay internally consistent
  - it emits an audit summary showing target vs output margins
  - it still preserves district total_votes by default

Typical usage from repo root:

  python scripts/calibrate_district_slices_to_stats_margins.py \
    --map "data/district_contests_2024_lines/state_house_president_2004.json=data/district_stats_2024_lines/NC-2024-State-House-district-statistics 2004 pres.csv" \
    --format pretty

CSV expectations:
  Required: ID, Dem, Rep
  Optional: Oth / Other, Total Votes / Votes
  Dem/Rep/Oth can be fractions (0.5740) or percents (57.40).
"""

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class StatsRow:
    district: str
    dem_share: float
    rep_share: float
    other_share: float
    target_margin_pct: float
    target_margin_display: float
    source_total_votes: int | None = None


@dataclass(frozen=True)
class SolvedVotes:
    dem_votes: int
    rep_votes: int
    other_votes: int
    margin: int
    margin_pct: float
    raw_margin_pct: float
    target_margin_delta: float
    score: tuple[float, float, float, int, int]


def _norm_header(value: str) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _field(row: dict[str, Any], *names: str, default: Any = None) -> Any:
    normalized = {_norm_header(k): v for k, v in row.items()}
    for name in names:
        key = _norm_header(name)
        if key in normalized:
            return normalized[key]
    return default


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    text = str(value).strip().replace(",", "")
    if not text:
        return default
    if text.endswith("%"):
        text = text[:-1].strip()
        try:
            return float(text) / 100.0
        except ValueError:
            return default
    try:
        return float(text)
    except ValueError:
        return default


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return int(round(float(text)))
    except ValueError:
        return None


def normalize_district_id(raw: Any) -> str:
    text = str(raw or "").strip().strip('"').strip("'")
    if not text:
        return ""
    if text.upper() in {"UN", "UND", "UNASSIGNED", "TOTAL", "STATEWIDE"}:
        return ""
    try:
        return str(int(float(text)))
    except ValueError:
        return text


def normalize_share_triplet(dem: float, rep: float, other: float) -> tuple[float, float, float]:
    vals = [max(0.0, dem), max(0.0, rep), max(0.0, other)]
    # CSVs may store 42.17 instead of 0.4217.
    if sum(vals) > 1.5:
        vals = [v / 100.0 for v in vals]
    total = sum(vals)
    if total <= 0:
        raise ValueError("Dem/Rep/Oth shares sum to zero")
    # District-statistics exports independently round each party share. Keep
    # near-100% triplets as printed so the solver can reproduce those displayed
    # percentages; normalize only materially incomplete or overfull inputs.
    if abs(total - 1.0) <= 0.005:
        return vals[0], vals[1], vals[2]
    return vals[0] / total, vals[1] / total, vals[2] / total


def load_stats(path: Path, *, margin_basis: str, precision: int, total_votes_column: str = "") -> dict[str, StatsRow]:
    out: dict[str, StatsRow] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            district = normalize_district_id(_field(raw, "ID", "District", "District ID"))
            if not district:
                continue

            dem = _as_float(_field(raw, "Dem", "Democratic", "D"))
            rep = _as_float(_field(raw, "Rep", "Republican", "R"))
            oth = _as_float(_field(raw, "Oth", "Other", "Others", "Third Party"), default=0.0)

            try:
                dem_share, rep_share, other_share = normalize_share_triplet(dem, rep, oth)
            except ValueError:
                continue

            if margin_basis == "two_party":
                two_party = dem_share + rep_share
                if two_party <= 0:
                    continue
                target_margin_pct = ((rep_share - dem_share) / two_party) * 100.0
            else:
                target_margin_pct = (rep_share - dem_share) * 100.0

            source_total_votes = None
            if total_votes_column:
                source_total_votes = _as_int(_field(raw, total_votes_column))
            else:
                source_total_votes = _as_int(
                    _field(raw, "Total Votes", "TotalVotes", "Votes", "Total", "Ballots")
                )

            out[district] = StatsRow(
                district=district,
                dem_share=dem_share,
                rep_share=rep_share,
                other_share=other_share,
                target_margin_pct=target_margin_pct,
                target_margin_display=round(target_margin_pct, precision),
                source_total_votes=source_total_votes,
            )

    if not out:
        raise ValueError(f"No usable district rows loaded from {path}")
    return out


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


def _candidate_margin_values(major_votes: int, desired_margin: float, span: int) -> Iterable[int]:
    nearest = int(round(desired_margin))
    # rep + dem = major_votes and rep - dem = margin must have same parity.
    if (nearest - major_votes) % 2:
        nearest += 1 if desired_margin >= nearest else -1
    seen: set[int] = set()
    for offset in range(0, span + 1):
        for sign in ((-1, 1) if offset else (1,)):
            m = nearest + sign * offset
            if m in seen:
                continue
            seen.add(m)
            if -major_votes <= m <= major_votes and (m - major_votes) % 2 == 0:
                yield m


def solve_votes_for_margin(
    *,
    total_votes: int,
    stats: StatsRow,
    precision: int,
    margin_basis: str,
    exact_rounded_margin: bool,
    other_search_radius: int,
    margin_search_radius: int,
) -> SolvedVotes:
    if total_votes <= 0:
        raise ValueError("total_votes must be positive")

    target_display = stats.target_margin_display
    desired_other = total_votes * stats.other_share
    desired_total_margin_votes = stats.target_margin_pct / 100.0 * total_votes

    best: SolvedVotes | None = None

    other_center = int(round(desired_other))
    other_candidates: list[int] = []
    for offset in range(0, other_search_radius + 1):
        for sign in ((-1, 1) if offset else (1,)):
            other = other_center + sign * offset
            if 0 <= other <= total_votes and other not in other_candidates:
                other_candidates.append(other)

    # Make the search robust for small totals or weird CSV rounding.
    if 0 not in other_candidates:
        other_candidates.append(0)
    if total_votes not in other_candidates:
        other_candidates.append(total_votes)

    for other_votes in other_candidates:
        major_votes = total_votes - other_votes
        if major_votes < 0:
            continue

        if margin_basis == "two_party":
            desired_margin_votes = stats.target_margin_pct / 100.0 * major_votes
        else:
            desired_margin_votes = desired_total_margin_votes

        for margin in _candidate_margin_values(major_votes, desired_margin_votes, margin_search_radius):
            rep_votes = (major_votes + margin) // 2
            dem_votes = major_votes - rep_votes
            if dem_votes < 0 or rep_votes < 0:
                continue

            if margin_basis == "two_party":
                denom = max(1, major_votes)
            else:
                denom = total_votes
            raw_margin_pct = (margin / denom) * 100.0
            rounded_margin_pct = round(raw_margin_pct, precision)
            display_delta = abs(rounded_margin_pct - target_display)

            if exact_rounded_margin and display_delta > 0:
                continue

            dem_share = dem_votes / total_votes
            rep_share = rep_votes / total_votes
            other_share = other_votes / total_votes
            share_error = (
                (dem_share - stats.dem_share) ** 2
                + (rep_share - stats.rep_share) ** 2
                + (other_share - stats.other_share) ** 2
            )
            raw_delta = abs(raw_margin_pct - stats.target_margin_pct)
            other_delta = abs(other_votes - desired_other)
            total_margin_delta = abs(margin - desired_total_margin_votes)

            # Sort by user-visible rounded margin, then the supplied party shares,
            # then raw margin closeness. DRA share columns are independently rounded,
            # so share fidelity must win among solutions with the same display margin.
            score = (
                display_delta,
                share_error,
                raw_delta,
                int(round(other_delta * 1000)),
                int(round(total_margin_delta * 1000)),
            )

            solved = SolvedVotes(
                dem_votes=int(dem_votes),
                rep_votes=int(rep_votes),
                other_votes=int(other_votes),
                margin=int(margin),
                margin_pct=float(rounded_margin_pct),
                raw_margin_pct=float(raw_margin_pct),
                target_margin_delta=float(raw_delta),
                score=score,
            )
            if best is None or solved.score < best.score:
                best = solved

    if best is None and exact_rounded_margin:
        # Fall back rather than failing the whole file; report the miss in audit.
        return solve_votes_for_margin(
            total_votes=total_votes,
            stats=stats,
            precision=precision,
            margin_basis=margin_basis,
            exact_rounded_margin=False,
            other_search_radius=max(other_search_radius, 100),
            margin_search_radius=max(margin_search_radius, 1000),
        )

    if best is None:
        raise ValueError(f"Could not solve integer votes for district {stats.district}")

    return best


def calibrate_slice(
    target_json: Path,
    stats_csv: Path,
    *,
    format_mode: str,
    precision: int,
    margin_basis: str,
    exact_rounded_margin: bool,
    total_votes_mode: str,
    total_votes_column: str,
    other_search_radius: int,
    margin_search_radius: int,
    audit_only: bool,
) -> dict[str, Any]:
    raw_text = target_json.read_text(encoding="utf-8")
    payload = json.loads(raw_text)
    stats_rows = load_stats(
        stats_csv,
        margin_basis=margin_basis,
        precision=precision,
        total_votes_column=total_votes_column,
    )

    results = payload.get("general", {}).get("results", {})
    if not isinstance(results, dict):
        raise ValueError(f"Unexpected payload format in {target_json}")

    calibrated = 0
    missing_stats_rows = 0
    exact_matches = 0
    misses: list[dict[str, Any]] = []
    max_display_delta = 0.0
    max_display_delta_district: str | None = None

    for raw_district, row in results.items():
        district = normalize_district_id(raw_district)
        stats = stats_rows.get(district)
        if not stats:
            missing_stats_rows += 1
            continue
        if not isinstance(row, dict):
            continue

        old_dem = int(row.get("dem_votes", 0) or 0)
        old_rep = int(row.get("rep_votes", 0) or 0)
        old_oth = int(row.get("other_votes", 0) or 0)
        existing_total = int(row.get("total_votes", old_dem + old_rep + old_oth) or 0)

        total_votes = existing_total
        if total_votes_mode == "stats" and stats.source_total_votes:
            total_votes = stats.source_total_votes
        if total_votes <= 0:
            continue

        solved = solve_votes_for_margin(
            total_votes=total_votes,
            stats=stats,
            precision=precision,
            margin_basis=margin_basis,
            exact_rounded_margin=exact_rounded_margin,
            other_search_radius=other_search_radius,
            margin_search_radius=margin_search_radius,
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
            max_display_delta_district = district

        if not audit_only:
            row["dem_votes"] = solved.dem_votes
            row["rep_votes"] = solved.rep_votes
            row["other_votes"] = solved.other_votes
            row["total_votes"] = int(total_votes)
            row["margin"] = solved.margin
            row["margin_pct"] = solved.margin_pct
            row["winner"] = "REP" if solved.rep_votes > solved.dem_votes else ("DEM" if solved.dem_votes > solved.rep_votes else "TIE")
            if isinstance(row.get("competitiveness"), dict):
                row["competitiveness"]["color"] = calculate_competitiveness(solved.margin_pct)
            else:
                row["competitiveness"] = {"color": calculate_competitiveness(solved.margin_pct)}

        calibrated += 1

    if not audit_only:
        was_pretty = ("\n" in raw_text.strip()) and (len(raw_text.strip().splitlines()) > 1)
        if format_mode == "auto":
            format_mode = "pretty" if was_pretty else "minify"

        if format_mode == "pretty":
            out_text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        elif format_mode == "minify":
            out_text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        else:
            raise ValueError(f"Unexpected format_mode: {format_mode}")

        target_json.write_text(out_text, encoding="utf-8")

    return {
        "target_json": str(target_json),
        "stats_csv": str(stats_csv),
        "margin_basis": margin_basis,
        "precision": precision,
        "total_votes_mode": total_votes_mode,
        "calibrated": calibrated,
        "exact_rounded_margin_matches": exact_matches,
        "missing_stats_rows": missing_stats_rows,
        "max_display_delta_pct": round(max_display_delta, precision + 2),
        "max_display_delta_district": max_display_delta_district,
        "misses": misses[:25],
        "miss_count": len(misses),
        "audit_only": audit_only,
    }


def parse_map_arg(raw: str) -> tuple[Path, Path]:
    if "=" not in raw:
        raise ValueError(f"--map value must be target_json=stats_csv, got: {raw}")
    left, right = raw.split("=", 1)
    target = Path(left.strip().strip('"').strip("'"))
    stats = Path(right.strip().strip('"').strip("'"))
    if not target.exists():
        raise FileNotFoundError(f"Missing target json: {target}")
    if not stats.exists():
        raise FileNotFoundError(f"Missing stats csv: {stats}")
    return target, stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calibrate district JSON slices to CSV target margins with deterministic integer vote solving."
    )
    parser.add_argument(
        "--map",
        action="append",
        required=True,
        help="Mapping of target_json=stats_csv. Repeat for multiple files.",
    )
    parser.add_argument(
        "--format",
        choices=["auto", "pretty", "minify"],
        default="auto",
        help="Output JSON formatting. auto preserves the target file style.",
    )
    parser.add_argument(
        "--precision",
        type=int,
        default=2,
        help="Rounded margin precision to match. Default: 2.",
    )
    parser.add_argument(
        "--margin-basis",
        choices=["total", "two_party"],
        default="total",
        help="Match Rep-Dem margin as share of total votes or two-party votes. Default: total.",
    )
    parser.add_argument(
        "--allow-nearest-margin",
        action="store_true",
        help="Allow nearest integer margin if exact rounded margin is impossible. Default requires exact rounded margin when possible.",
    )
    parser.add_argument(
        "--total-votes-mode",
        choices=["existing", "stats"],
        default="existing",
        help="Keep JSON total_votes or use a vote-total column from the stats CSV when available. Default: existing.",
    )
    parser.add_argument(
        "--total-votes-column",
        default="",
        help="Optional explicit stats CSV column to use with --total-votes-mode stats.",
    )
    parser.add_argument(
        "--other-search-radius",
        type=int,
        default=50,
        help="Integer search radius around target Other votes. Increase if audit shows misses.",
    )
    parser.add_argument(
        "--margin-search-radius",
        type=int,
        default=500,
        help="Integer search radius around target margin votes. Increase if audit shows misses.",
    )
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="Print what would be calibrated without writing files.",
    )
    args = parser.parse_args()

    summaries: list[dict[str, Any]] = []
    for raw_map in args.map:
        target, stats = parse_map_arg(raw_map)
        summaries.append(
            calibrate_slice(
                target,
                stats,
                format_mode=args.format,
                precision=args.precision,
                margin_basis=args.margin_basis,
                exact_rounded_margin=not args.allow_nearest_margin,
                total_votes_mode=args.total_votes_mode,
                total_votes_column=args.total_votes_column,
                other_search_radius=args.other_search_radius,
                margin_search_radius=args.margin_search_radius,
                audit_only=args.audit_only,
            )
        )

    print(json.dumps({"updated": summaries}, indent=2))


if __name__ == "__main__":
    main()
