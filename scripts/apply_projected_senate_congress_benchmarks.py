#!/usr/bin/env python3
"""Audit or apply NCSBE/MGGG projections without replacing NCGA-locked totals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from calibrate_district_slices_from_stats_csv import calculate_competitiveness


ROOT = Path(__file__).resolve().parents[1]
VALUE_KEYS = (
    "dem_votes",
    "rep_votes",
    "other_votes",
    "total_votes",
    "margin",
    "margin_pct",
    "winner",
    "competitiveness",
)


def resolve_project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def source_values(row: dict[str, Any]) -> dict[str, Any]:
    margin_pct = float(row.get("margin_pct") or 0.0)
    return {
        "dem_votes": int(row.get("dem_votes") or 0),
        "rep_votes": int(row.get("rep_votes") or 0),
        "other_votes": int(row.get("other_votes") or 0),
        "total_votes": int(row.get("total_votes") or 0),
        "margin": int(row.get("margin") or 0),
        "margin_pct": margin_pct,
        "winner": str(row.get("winner") or "TIE"),
        "competitiveness": {"color": calculate_competitiveness(margin_pct)},
    }


def snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in VALUE_KEYS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--min-vote-coverage", type=float, default=97.0)
    args = parser.parse_args()

    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    schema = str(benchmark.get("schema") or "")
    source_kind = "ncsbe" if schema.startswith("ncsbe_") else "mggg" if schema.startswith("mggg_") else ""
    if not source_kind:
        raise ValueError(f"Unsupported benchmark schema: {schema}")

    changes: list[dict[str, Any]] = []
    protected_files: list[str] = []
    low_coverage: list[dict[str, Any]] = []
    missing_files: list[str] = []
    missing_districts: list[dict[str, str]] = []
    applied_files: set[str] = set()

    for plan_name, plan in benchmark.get("plans", {}).items():
        spec = plan.get("spec") or {}
        scope = str(spec.get("scope") or "")
        live_dir = resolve_project_path(str(spec.get("live_dir") or ""))
        for contest_key, contest in (plan.get("contests") or {}).items():
            year = int(contest.get("year") or 0)
            slug = str(contest.get("contest_type") or "")
            path = live_dir / f"{scope}_{slug}_{year}.json"
            if not path.exists():
                missing_files.append(path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path))
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            meta = payload.get("meta") or {}
            relative_path = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
            if meta.get("ncga_statpack_calibrated"):
                protected_files.append(relative_path)
                continue
            if source_kind == "mggg" and meta.get("ncsbe_projected_calibrated"):
                protected_files.append(relative_path)
                continue
            coverage = float((contest.get("coverage") or {}).get("vote_coverage_pct") or 0.0)
            if coverage < args.min_vote_coverage:
                low_coverage.append({"file": relative_path, "contest": contest_key, "vote_coverage_pct": coverage})
                continue

            results = ((payload.get("general") or {}).get("results") or {})
            changed = False
            for district, projected in (contest.get("results") or {}).items():
                row = results.get(str(district))
                if not isinstance(row, dict):
                    missing_districts.append({"file": relative_path, "district": str(district)})
                    continue
                before = snapshot(row)
                after = source_values(projected)
                if before == after:
                    continue
                changes.append({
                    "plan": plan_name,
                    "file": relative_path,
                    "district": str(district),
                    "contest": contest_key,
                    "vote_coverage_pct": coverage,
                    "before": before,
                    "after": after,
                    "margin_pct_delta": round(after["margin_pct"] - float(before.get("margin_pct") or 0.0), 2),
                })
                if args.write:
                    row.update(after)
                    if source_kind == "ncsbe":
                        if contest.get("dem_candidate"):
                            row["dem_candidate"] = contest["dem_candidate"]
                        if contest.get("rep_candidate"):
                            row["rep_candidate"] = contest["rep_candidate"]
                    changed = True
            if args.write and changed:
                meta = payload.setdefault("meta", {})
                meta[f"{source_kind}_projected_calibrated"] = True
                meta[f"{source_kind}_projected_source"] = contest.get("source_file") or benchmark.get("source")
                meta[f"{source_kind}_projected_method"] = benchmark.get("method")
                meta[f"{source_kind}_projected_vote_coverage_pct"] = coverage
                path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                applied_files.add(relative_path)

    report = {
        "mode": "write" if args.write else "audit",
        "source_kind": source_kind,
        "benchmark": args.benchmark.as_posix(),
        "minimum_vote_coverage_pct": args.min_vote_coverage,
        "changed_rows": len(changes),
        "applied_files": sorted(applied_files),
        "protected_files": sorted(set(protected_files)),
        "low_coverage": low_coverage,
        "missing_files": sorted(set(missing_files)),
        "missing_districts": missing_districts,
        "changes": changes,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = {key: report[key] for key in (
        "mode", "source_kind", "changed_rows", "applied_files", "protected_files",
        "low_coverage", "missing_files", "missing_districts",
    )}
    print(json.dumps(summary, indent=2))
    return 1 if low_coverage or missing_districts else 0


if __name__ == "__main__":
    raise SystemExit(main())
