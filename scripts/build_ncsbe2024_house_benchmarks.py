#!/usr/bin/env python3
"""Build reconciled 2024 statewide-contest results on both modern NC House plans."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = (
    "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/2024_11_05/"
    "results_precinct_sort/STATEWIDE_PRECINCT_SORT.txt"
)
CONTESTS = {
    "US PRESIDENT": "president_2024",
    "NC GOVERNOR": "governor_2024",
    "NC LIEUTENANT GOVERNOR": "lieutenant_governor_2024",
    "NC ATTORNEY GENERAL": "attorney_general_2024",
    "NC AUDITOR": "auditor_2024",
    "NC COMMISSIONER OF AGRICULTURE": "agriculture_commissioner_2024",
    "NC COMMISSIONER OF INSURANCE": "insurance_commissioner_2024",
    "NC COMMISSIONER OF LABOR": "labor_commissioner_2024",
    "NC SECRETARY OF STATE": "secretary_of_state_2024",
    "NC SUPERINTENDENT OF PUBLIC INSTRUCTION": "superintendent_2024",
    "NC TREASURER": "treasurer_2024",
    "NC SUPREME COURT ASSOCIATE JUSTICE SEAT 06": "nc_supreme_court_associate_justice_seat_06_2024",
    "NC COURT OF APPEALS JUDGE SEAT 12": "nc_court_of_appeals_judge_seat_12_2024",
    "NC COURT OF APPEALS JUDGE SEAT 14": "nc_court_of_appeals_judge_seat_14_2024",
    "NC COURT OF APPEALS JUDGE SEAT 15": "nc_court_of_appeals_judge_seat_15_2024",
}
KEYS = ["county", "contest", "bucket"]
SOURCE_ALIASES = {
    "UNION - 0020B": "UNION - 020B",
    "UNION - 0044": "UNION - 044",
    "UNION - 0045": "UNION - 045",
    "WAKE - 01-07A": "WAKE - 01-07",
    "WAKE - 07-07A": "WAKE - 07-07",
}


def clean(series: pd.Series) -> pd.Series:
    return (
        series.fillna("")
        .astype(str)
        .str.replace("\x00", "", regex=False)
        .str.strip()
        .str.upper()
    )


def party_bucket(series: pd.Series) -> pd.Series:
    party = clean(series)
    return party.map(lambda value: "dem" if value == "DEM" else ("rep" if value == "REP" else "other"))


def load_precinct_sort(path: Path, chunksize: int) -> pd.DataFrame:
    usecols = [
        "county",
        "result_type_lbl",
        "contest_title",
        "precinct_code",
        "candidate_name",
        "candidate_party_lbl",
        "vote_ct",
    ]
    pieces: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        path,
        sep="\t",
        dtype=str,
        encoding="utf-8-sig",
        usecols=usecols,
        chunksize=chunksize,
        low_memory=False,
    ):
        chunk["result_type_lbl"] = clean(chunk["result_type_lbl"])
        chunk["contest_title"] = clean(chunk["contest_title"])
        chunk["candidate_name"] = clean(chunk["candidate_name"])
        chunk = chunk[
            (chunk["result_type_lbl"] == "STD") & chunk["contest_title"].isin(CONTESTS)
            & ~chunk["candidate_name"].isin({"UNDER VOTE", "OVER VOTE"})
        ].copy()
        if chunk.empty:
            continue
        chunk["county"] = clean(chunk["county"])
        chunk["precinct_code"] = clean(chunk["precinct_code"])
        chunk = chunk[chunk["precinct_code"] != ""].copy()
        chunk["precinct_id"] = chunk["county"] + " - " + chunk["precinct_code"]
        chunk["precinct_id"] = chunk["precinct_id"].replace(SOURCE_ALIASES)
        chunk["contest"] = chunk["contest_title"].map(CONTESTS)
        chunk["bucket"] = party_bucket(chunk["candidate_party_lbl"])
        chunk["votes"] = pd.to_numeric(chunk["vote_ct"], errors="raise")
        pieces.append(
            chunk.groupby(["county", "precinct_id", "contest", "bucket"], as_index=False)[
                "votes"
            ].sum()
        )
    if not pieces:
        raise ValueError("No target contests found in the precinct-sort export")
    return (
        pd.concat(pieces, ignore_index=True)
        .groupby(["county", "precinct_id", "contest", "bucket"], as_index=False)["votes"]
        .sum()
    )


def load_official_totals(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(
        path,
        dtype=str,
        usecols=["county", "office", "party", "votes"],
        low_memory=False,
    )
    frame["office"] = clean(frame["office"])
    frame = frame[frame["office"].isin(CONTESTS)].copy()
    frame["county"] = clean(frame["county"])
    frame["contest"] = frame["office"].map(CONTESTS)
    frame["bucket"] = party_bucket(frame["party"])
    frame["official_votes"] = pd.to_numeric(frame["votes"], errors="raise")
    return frame.groupby(KEYS, as_index=False)["official_votes"].sum()


def reconcile_to_official(precinct: pd.DataFrame, official: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    sorted_totals = precinct.groupby(KEYS, as_index=False)["votes"].sum().rename(
        columns={"votes": "sorted_votes"}
    )
    comparison = sorted_totals.merge(official, on=KEYS, how="outer").fillna(0)
    impossible = comparison[
        (comparison["official_votes"] > 0) & (comparison["sorted_votes"] <= 0)
    ]
    if not impossible.empty:
        raise ValueError(
            "Official county/contest/party totals lack precinct-sort votes: "
            + impossible[KEYS].to_dict(orient="records").__repr__()
        )
    scale = comparison.copy()
    scale["factor"] = scale.apply(
        lambda row: float(row["official_votes"]) / float(row["sorted_votes"])
        if float(row["sorted_votes"]) > 0
        else 0.0,
        axis=1,
    )
    reconciled = precinct.merge(scale[KEYS + ["factor"]], on=KEYS, how="left")
    reconciled["votes"] = reconciled["votes"] * reconciled["factor"]
    audit = comparison.assign(
        raw_difference=lambda x: x["sorted_votes"] - x["official_votes"]
    ).to_dict(orient="records")
    return reconciled, audit


def load_plan_weights(
    assignment_path: Path, *, assignment_block: str, assignment_district: str
) -> pd.DataFrame:
    bridge = pd.read_csv(
        ROOT / "data/crosswalks/block20_to_sbe_2024.csv", dtype=str
    )[["block_geoid20", "precinct_id"]].rename(columns={"block_geoid20": "block"})
    bridge["block"] = bridge["block"].str.zfill(15)
    bridge["precinct_id"] = clean(bridge["precinct_id"])
    # Carolina Village (CV) is absent from the 2024 SBE geometry package but
    # remains a real 2024 precinct. Its stable official block lineage is
    # available in the 2015 SBE bridge and is used only for this missing key.
    fallback = pd.read_csv(
        ROOT / "data/crosswalks/block20_to_sbe_2015.csv", dtype=str
    )[["block_geoid20", "precinct_id"]].rename(columns={"block_geoid20": "block"})
    fallback["block"] = fallback["block"].str.zfill(15)
    fallback["precinct_id"] = clean(fallback["precinct_id"])
    fallback = fallback[fallback["precinct_id"] == "HENDERSON - CV"]
    bridge = pd.concat([bridge, fallback], ignore_index=True).drop_duplicates(
        ["block", "precinct_id"]
    )

    vap = pd.read_csv(
        ROOT / "data/census/block_vap_2020_nc.csv", dtype={"block_geoid20": str}
    ).rename(columns={"block_geoid20": "block"})[["block", "vap_count"]]
    vap["block"] = vap["block"].str.zfill(15)
    vap["vap_count"] = pd.to_numeric(vap["vap_count"], errors="coerce").fillna(0.0)

    assignments = pd.read_csv(assignment_path, dtype=str).rename(
        columns={assignment_block: "block", assignment_district: "district"}
    )[["block", "district"]]
    assignments["block"] = assignments["block"].str.zfill(15)
    assignments["district"] = assignments["district"].str.lstrip("0").replace("", "0")

    joined = bridge.merge(vap, on="block", how="left").merge(assignments, on="block", how="inner")
    joined["block_count"] = 1
    grouped = joined.groupby(["precinct_id", "district"], as_index=False).agg(
        vap_count=("vap_count", "sum"), block_count=("block_count", "sum")
    )
    grouped["total_vap"] = grouped.groupby("precinct_id")["vap_count"].transform("sum")
    grouped["total_blocks"] = grouped.groupby("precinct_id")["block_count"].transform("sum")
    grouped["share"] = grouped.apply(
        lambda row: row["vap_count"] / row["total_vap"]
        if row["total_vap"] > 0
        else row["block_count"] / row["total_blocks"],
        axis=1,
    )
    return grouped[["precinct_id", "district", "share"]]


def largest_remainder(values: dict[str, float], target: int) -> dict[str, int]:
    floors = {district: math.floor(value) for district, value in values.items()}
    remainder = target - sum(floors.values())
    ranked = sorted(
        values,
        key=lambda district: (values[district] - floors[district], -int(district)),
        reverse=True,
    )
    if remainder < 0 or remainder > len(ranked):
        raise ValueError(f"Unexpected rounding remainder {remainder} for target {target}")
    for district in ranked[:remainder]:
        floors[district] += 1
    return floors


def is_nongeographic(precinct_id: str) -> bool:
    code = precinct_id.split(" - ", 1)[-1].strip().upper()
    return (
        code.startswith(("EV ", "EV-", "EV_", "EARLY VOTING", "ONE STOP", "ONE-STOP", "OS ", "OS-", "ABS"))
        or "ABSENTEE" in code
        or "ONE STOP" in code
        or "PROVISIONAL" in code
        or code.startswith(("TRANSFER", "CURBSIDE"))
        or code.endswith(" OS")
        or code in {"PROV"}
        or code.startswith("ADD ABS")
    )


def allocate_nongeographic(
    precinct: pd.DataFrame, weights: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    weight_ids = set(weights["precinct_id"])
    positive_ids = set(precinct.loc[precinct["votes"] > 0, "precinct_id"])
    unmatched_ids = positive_ids - weight_ids
    unexpected = sorted(value for value in unmatched_ids if not is_nongeographic(value))
    if unexpected:
        raise ValueError(f"Unmatched geographic precincts: {unexpected}")

    geographic = precinct[precinct["precinct_id"].isin(weight_ids)].copy()
    nongeo = precinct[
        precinct["precinct_id"].isin(unmatched_ids) & (precinct["votes"] > 0)
    ].copy()
    nongeo_totals = nongeo.groupby(KEYS, as_index=False)["votes"].sum().rename(
        columns={"votes": "nongeo_votes"}
    )
    geo_totals = geographic.groupby(KEYS, as_index=False)["votes"].sum().rename(
        columns={"votes": "geo_votes"}
    )
    allocation = nongeo_totals.merge(geo_totals, on=KEYS, how="left")
    impossible = allocation[(allocation["nongeo_votes"] > 0) & (allocation["geo_votes"] <= 0)]
    if not impossible.empty:
        raise ValueError(
            "Non-geographic votes lack a geographic allocation denominator: "
            + impossible[KEYS].to_dict(orient="records").__repr__()
        )
    geographic = geographic.merge(nongeo_totals, on=KEYS, how="left").merge(
        geo_totals, on=KEYS, how="left"
    )
    geographic["nongeo_votes"] = geographic["nongeo_votes"].fillna(0.0)
    geographic["votes"] = geographic["votes"] + (
        geographic["nongeo_votes"] * geographic["votes"] / geographic["geo_votes"]
    ).fillna(0.0)
    return geographic[precinct.columns], {
        "positive_source_precincts": len(positive_ids),
        "matched_geographic_precincts": len(positive_ids - unmatched_ids),
        "allocated_nongeographic_precincts": len(unmatched_ids),
        "allocated_nongeographic_votes": round(float(nongeo["votes"].sum()), 3),
        "nongeographic_precinct_ids": sorted(unmatched_ids),
        "unmatched_geographic_precincts": unexpected,
    }


def project(
    precinct: pd.DataFrame,
    weights: pd.DataFrame,
    official: pd.DataFrame,
    *,
    district_count: int = 120,
    contests: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    geographic, coverage = allocate_nongeographic(precinct, weights)
    joined = geographic.merge(weights, on="precinct_id", how="inner")
    joined["allocated"] = joined["votes"] * joined["share"]
    allocated = joined.groupby(["contest", "bucket", "district"], as_index=False)[
        "allocated"
    ].sum()
    official_state = official.groupby(["contest", "bucket"], as_index=False)[
        "official_votes"
    ].sum()
    official_lookup = {
        (row.contest, row.bucket): int(row.official_votes)
        for row in official_state.itertuples(index=False)
    }

    contest_names = sorted(contests if contests is not None else CONTESTS.values())
    rounded: dict[tuple[str, str], dict[str, int]] = {}
    districts = [str(value) for value in range(1, district_count + 1)]
    for contest in contest_names:
        for bucket in ("dem", "rep", "other"):
            subset = allocated[(allocated["contest"] == contest) & (allocated["bucket"] == bucket)]
            values = {district: 0.0 for district in districts}
            values.update({str(row.district): float(row.allocated) for row in subset.itertuples(index=False)})
            rounded[(contest, bucket)] = largest_remainder(
                values, official_lookup.get((contest, bucket), 0)
            )

    results: dict[str, dict[str, Any]] = {}
    totals_audit: list[dict[str, Any]] = []
    for contest in contest_names:
        rows: dict[str, Any] = {}
        for district in districts:
            dem = rounded[(contest, "dem")][district]
            rep = rounded[(contest, "rep")][district]
            other = rounded[(contest, "other")][district]
            total = dem + rep + other
            margin = rep - dem
            rows[district] = {
                "dem_votes": dem,
                "rep_votes": rep,
                "other_votes": other,
                "total_votes": total,
                "margin": margin,
                "margin_pct": round((margin / total) * 100.0, 2) if total else 0.0,
                "winner": "REP" if margin > 0 else ("DEM" if margin < 0 else "TIE"),
            }
        results[contest] = rows
        for bucket in ("dem", "rep", "other"):
            projected_total = sum(rounded[(contest, bucket)].values())
            official_total = official_lookup.get((contest, bucket), 0)
            totals_audit.append(
                {
                    "contest": contest,
                    "bucket": bucket,
                    "official_votes": official_total,
                    "projected_votes": projected_total,
                    "difference": projected_total - official_total,
                }
            )
    return results, {
        **coverage,
        "statewide_totals": totals_audit,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("precinct_sort", type=Path)
    parser.add_argument(
        "--official-results",
        type=Path,
        default=ROOT / "data/2024/20241105__nc__general__precinct.csv",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chunksize", type=int, default=300_000)
    args = parser.parse_args()

    precinct_sort = load_precinct_sort(args.precinct_sort, args.chunksize)
    official = load_official_totals(args.official_results)
    reconciled, reconciliation = reconcile_to_official(precinct_sort, official)
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
    audits: dict[str, Any] = {}
    for name, (path, block_col, district_col, plan_id) in plan_specs.items():
        results, audit = project(
            reconciled,
            load_plan_weights(path, assignment_block=block_col, assignment_district=district_col),
            official,
        )
        plans[name] = results
        audits[name] = {"plan_id": plan_id, **audit}

    payload = {
        "schema": "ncsbe2024_house_benchmarks.v1",
        "source": SOURCE_URL,
        "official_totals_source": str(args.official_results),
        "method": (
            "Official 2024 precinct-sort distributions reconciled by county/contest/party "
            "to non-noised NCSBE totals, then 2020-VAP weighted to official block assignments"
        ),
        "contests": sorted(CONTESTS.values()),
        "source_precinct_aliases": SOURCE_ALIASES,
        "geometry_fallbacks": {
            "HENDERSON - CV": "data/crosswalks/block20_to_sbe_2015.csv"
        },
        "reconciliation": reconciliation,
        "audits": audits,
        "plans": plans,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "contests": len(CONTESTS),
                "precinct_sort_rows": len(precinct_sort),
                "plans": audits,
            },
            indent=2,
        )
    )
    failed = any(audit["unmatched_geographic_precincts"] for audit in audits.values()) or any(
        row["difference"] for audit in audits.values() for row in audit["statewide_totals"]
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
