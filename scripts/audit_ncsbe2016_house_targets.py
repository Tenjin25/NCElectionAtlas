#!/usr/bin/env python3
"""Project official NCSBE 2016 precinct-sort results onto modern House plans."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"108", "109", "110"}
COUNTIES = ("CLEVELAND", "GASTON", "LINCOLN")
CONTESTS = {
    "US PRESIDENT": "president_2016",
    "US SENATE": "us_senate_2016",
    "NC GOVERNOR": "governor_2016",
    "NC LIEUTENANT GOVERNOR": "lieutenant_governor_2016",
    "NC ATTORNEY GENERAL": "attorney_general_2016",
    "NC AUDITOR": "auditor_2016",
    "NC COMMISSIONER OF AGRICULTURE": "agriculture_commissioner_2016",
    "NC COMMISSIONER OF INSURANCE": "insurance_commissioner_2016",
    "NC COMMISSIONER OF LABOR": "labor_commissioner_2016",
    "NC SECRETARY OF STATE": "secretary_of_state_2016",
    "NC SUPERINTENDENT OF PUBLIC INSTRUCTION": "superintendent_2016",
    "NC TREASURER": "treasurer_2016",
}


def precinct_key(county: str, precinct_name: str) -> str:
    """Convert NCSBE's CODE_CODE_DESCRIPTION field to the bridge's COUNTY - CODE key."""
    code = precinct_name.split("_", 1)[0].strip()
    return f"{county.strip().upper()} - {code}"


def load_precinct_votes(source_dir: Path) -> pd.DataFrame:
    totals: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"dem": 0.0, "rep": 0.0, "other": 0.0}
    )
    for county in COUNTIES:
        path = source_dir / f"{county}_PRECINCT_SORT.txt"
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row.get("result_type_lbl") != "STD":
                    continue
                slug = CONTESTS.get((row.get("contest_title") or "").strip())
                if not slug:
                    continue
                key = precinct_key(county, row.get("precinct_name") or "")
                party = (row.get("candidate_party_lbl") or "").strip().upper()
                bucket = "dem" if party == "DEM" else ("rep" if party == "REP" else "other")
                totals[(key, slug)][bucket] += float(row.get("vote_ct") or 0)

    frame = pd.DataFrame(
        [
            {"precinct_id": key, "contest": contest, **votes}
            for (key, contest), votes in sorted(totals.items())
        ]
    )
    # Precinct-sort exports retain zero-only administrative placeholders. They
    # are not geographic precincts and the NCGA report explicitly excludes them.
    return frame[(frame[["dem", "rep", "other"]].sum(axis=1)) > 0].copy()


def load_weights(assignment_path: Path, *, assignment_block: str, assignment_district: str) -> pd.DataFrame:
    bridge = pd.read_csv(
        ROOT / "data/crosswalks/block20_to_sbe_2016_via_block10.csv", dtype=str
    )[["block_geoid20", "precinct_id"]].rename(columns={"block_geoid20": "block"})
    bridge = bridge[bridge["precinct_id"].str.split(" - ", n=1).str[0].isin(COUNTIES)]

    vap = pd.read_csv(
        ROOT / "data/census/block_vap_2020_nc.csv", dtype={"block_geoid20": str}
    ).rename(columns={"block_geoid20": "block"})[["block", "vap_count"]]
    vap["vap_count"] = pd.to_numeric(vap["vap_count"], errors="coerce").fillna(0.0)

    assignments = pd.read_csv(assignment_path, dtype=str).rename(
        columns={assignment_block: "block", assignment_district: "district"}
    )[["block", "district"]]
    assignments["block"] = assignments["block"].str.zfill(15)
    assignments["district"] = assignments["district"].str.lstrip("0").replace("", "0")

    joined = bridge.merge(vap, on="block", how="left").merge(assignments, on="block", how="inner")
    grouped = joined.groupby(["precinct_id", "district"], as_index=False)["vap_count"].sum()
    totals = grouped.groupby("precinct_id")["vap_count"].transform("sum")
    grouped["share"] = (grouped["vap_count"] / totals).where(totals > 0, 0.0)
    return grouped[["precinct_id", "district", "share"]]


def project(votes: pd.DataFrame, weights: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    joined = weights.merge(votes, on="precinct_id", how="inner")
    matched = set(joined["precinct_id"])
    source = set(votes["precinct_id"])
    output: dict[str, dict[str, dict[str, float]]] = {}
    for contest in sorted(votes["contest"].unique()):
        frame = joined[joined["contest"] == contest].copy()
        for bucket in ("dem", "rep", "other"):
            frame[f"{bucket}_alloc"] = frame[bucket] * frame["share"]
        grouped = frame.groupby("district")[["dem_alloc", "rep_alloc", "other_alloc"]].sum()
        rows: dict[str, dict[str, float]] = {}
        for district in sorted(TARGETS, key=int):
            if district not in grouped.index:
                continue
            row = grouped.loc[district]
            dem, rep, other = (float(row[f"{party}_alloc"]) for party in ("dem", "rep", "other"))
            total = dem + rep + other
            rows[district] = {
                "dem_votes_float": round(dem, 3),
                "rep_votes_float": round(rep, 3),
                "other_votes_float": round(other, 3),
                "total_votes_float": round(total, 3),
                "margin_pct": round(((rep - dem) / total) * 100.0, 2) if total else 0.0,
            }
        output[contest] = rows
    coverage = {
        "source_precincts": len(source),
        "matched_precincts": len(matched),
        "unmatched_precincts": sorted(source - matched),
    }
    return output, coverage


def official_validation(
    plans: dict[str, Any], benchmark_paths: list[Path]
) -> list[dict[str, Any]]:
    title_to_slug = {title: slug for title, slug in CONTESTS.items()}
    validation: list[dict[str, Any]] = []
    for benchmark_path in benchmark_paths:
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
        plan_id = benchmark.get("plan_id")
        plan_name = "2022_lines" if plan_id == "SL 2022-4" else "2024_lines"
        projected = plans[plan_name]
        for contest in benchmark.get("contests", []):
            year = int(contest.get("election_year") or 0)
            slug = title_to_slug.get(str(contest.get("contest") or "").upper())
            if year != 2016 or not slug or slug not in projected:
                continue
            for district, parties in (contest.get("districts") or {}).items():
                values = projected[slug].get(district)
                if not values:
                    continue
                dem = int((parties.get("Dem") or {}).get("votes") or 0)
                rep = int((parties.get("Rep") or {}).get("votes") or 0)
                other = sum(
                    int((item or {}).get("votes") or 0)
                    for party, item in parties.items()
                    if party not in {"Dem", "Rep"}
                )
                total = dem + rep + other
                official_margin = round(((rep - dem) / total) * 100.0, 2) if total else 0.0
                validation.append(
                    {
                        "plan": plan_name,
                        "plan_id": plan_id,
                        "contest": slug,
                        "district": district,
                        "projected_margin_pct": values["margin_pct"],
                        "official_margin_pct": official_margin,
                        "difference_points": round(values["margin_pct"] - official_margin, 2),
                    }
                )
    return validation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ncga-benchmark", type=Path, action="append", default=[])
    args = parser.parse_args()

    votes = load_precinct_votes(args.source_dir)
    plan_specs = {
        "2022_lines": (
            ROOT / "data/tmp/block_assign_extract/SL 2022-4.csv",
            "Block",
            "District",
            "SL 2022-4",
        ),
        "2024_lines": (
            ROOT / "data/crosswalks/block20_to_2024_state_house.csv",
            "block_geoid20",
            "district",
            "SL 2023-149",
        ),
    }
    plans: dict[str, Any] = {}
    coverage: dict[str, Any] = {}
    for name, (path, block_col, district_col, plan_id) in plan_specs.items():
        projected, plan_coverage = project(
            votes,
            load_weights(path, assignment_block=block_col, assignment_district=district_col),
        )
        plans[name] = projected
        coverage[name] = {"plan_id": plan_id, **plan_coverage}

    validation = official_validation(plans, args.ncga_benchmark)
    payload = {
        "schema": "ncsbe2016_house_targets.v1",
        "source": "https://dl.ncsbe.gov/?prefix=ENRS/2016_11_08/results_precinct_sort/",
        "method": "2020-VAP-weighted official 2016 SBE-precinct allocation to official block assignments",
        "target_districts": sorted(TARGETS, key=int),
        "counties": list(COUNTIES),
        "coverage": coverage,
        "ncga_validation": validation,
        "plans": plans,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "contests": len(CONTESTS),
                "coverage": coverage,
                "validation_rows": len(validation),
                "max_validation_difference_points": max(
                    (abs(row["difference_points"]) for row in validation), default=None
                ),
            },
            indent=2,
        )
    )
    return 1 if any(item["unmatched_precincts"] for item in coverage.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
