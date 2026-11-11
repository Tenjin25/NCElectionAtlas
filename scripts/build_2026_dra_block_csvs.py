"""Build DRA-readable 2026 election CSVs on 2020 Census blocks.

Each output uses the compact Dave's Redistricting convention already used by
the project's reference exports:

    GEOID20,Tot,D,R

Precinct votes, including allocated non-geographic ballots, are distributed to
2020 Census blocks by voting-age population. Integer largest-remainder rounding
preserves each contest's exact statewide Democratic, Republican, other-party,
and total vote counts.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_district_contests_from_batch_shatter import (  # noqa: E402
    _norm,
    build_auto_precinct_overrides,
    build_precinct_party_votes,
    clean_precinct_name,
    load_precinct_overrides,
    load_sbe_precinct_code_map,
)


HOUSE_OFFICE_RE = re.compile(r"^NC HOUSE OF REPRESENTATIVES DISTRICT\s*0*\d+\s*$", re.I)
SENATE_OFFICE_RE = re.compile(r"^NC STATE SENATE DISTRICT\s*0*\d+\s*$", re.I)
US_HOUSE_OFFICE_RE = re.compile(r"^US HOUSE OF REPRESENTATIVES DISTRICT\s*0*\d+", re.I)

CONTESTS = [
    {
        "key": "us_senate",
        "label": "U.S. Senate",
        "filename": "NC_2026_US_Senate_DRA_blocks.csv",
        "offices": ["US SENATE"],
    },
    {
        "key": "nc_supreme_court_associate_justice_seat_01",
        "label": "NC Supreme Court Associate Justice Seat 1",
        "filename": "NC_2026_NC_Supreme_Court_Seat_01_DRA_blocks.csv",
        "offices": ["NC SUPREME COURT ASSOCIATE JUSTICE SEAT 01"],
    },
    {
        "key": "nc_court_of_appeals_judge_seat_01",
        "label": "NC Court of Appeals Judge Seat 1",
        "filename": "NC_2026_NC_Court_of_Appeals_Seat_01_DRA_blocks.csv",
        "offices": ["NC COURT OF APPEALS JUDGE SEAT 01"],
    },
    {
        "key": "nc_court_of_appeals_judge_seat_02",
        "label": "NC Court of Appeals Judge Seat 2",
        "filename": "NC_2026_NC_Court_of_Appeals_Seat_02_DRA_blocks.csv",
        "offices": ["NC COURT OF APPEALS JUDGE SEAT 02"],
    },
    {
        "key": "nc_court_of_appeals_judge_seat_03",
        "label": "NC Court of Appeals Judge Seat 3",
        "filename": "NC_2026_NC_Court_of_Appeals_Seat_03_DRA_blocks.csv",
        "offices": ["NC COURT OF APPEALS JUDGE SEAT 03"],
    },
    {
        "key": "us_house",
        "label": "U.S. House",
        "filename": "NC_2026_US_House_DRA_blocks.csv",
        "office_regex": US_HOUSE_OFFICE_RE,
    },
    {
        "key": "state_house",
        "label": "NC State House",
        "filename": "NC_2026_State_House_DRA_blocks.csv",
        "office_regex": HOUSE_OFFICE_RE,
    },
    {
        "key": "state_senate",
        "label": "NC State Senate",
        "filename": "NC_2026_State_Senate_DRA_blocks.csv",
        "office_regex": SENATE_OFFICE_RE,
    },
]


def integer_largest_remainder(values: np.ndarray, target: int) -> np.ndarray:
    """Round nonnegative values to integers summing exactly to target."""
    clean = np.nan_to_num(values.astype(float), nan=0.0, posinf=0.0, neginf=0.0)
    clean = np.maximum(clean, 0.0)
    floors = np.floor(clean).astype(np.int64)
    remainder = int(target) - int(floors.sum())
    fractions = clean - floors
    if remainder > 0:
        order = np.lexsort((np.arange(len(clean)), -fractions))
        floors[order[:remainder]] += 1
    elif remainder < 0:
        eligible = np.flatnonzero(floors > 0)
        order = eligible[np.lexsort((eligible, fractions[eligible]))]
        floors[order[: -remainder]] -= 1
    if int(floors.sum()) != int(target):
        raise ValueError(f"Largest-remainder allocation failed: {floors.sum()} != {target}")
    return floors


def build_precinct_overrides(src: pd.DataFrame, crosswalk: pd.DataFrame) -> dict[str, str]:
    sbe_path = ROOT / "data/census/SBE_PRECINCTS_20240723/SBE_PRECINCTS_20240723.shp"
    sbe_map = load_sbe_precinct_code_map(sbe_path)
    clean_precinct_name._sbe_map = sbe_map  # type: ignore[attr-defined]
    build_auto_precinct_overrides._sbe_map = sbe_map  # type: ignore[attr-defined]

    matched = set(crosswalk["precinct_id"].astype(str).str.strip().str.upper().unique())
    source_ids = (
        src["county"].astype(str).str.strip().str.upper()
        + " - "
        + src["precinct"].astype(str).str.strip().str.upper()
    )
    automatic = build_auto_precinct_overrides(source_ids, matched)
    manual = load_precinct_overrides(ROOT / "data/mappings/precinct_key_overrides.csv", 2026)
    combined = {**automatic, **manual}
    return {
        raw: canonical
        for raw, canonical in combined.items()
        if _norm(str(raw)) not in matched
        and _norm(str(canonical)) in matched
        and _norm(str(raw)) != _norm(str(canonical))
    }


def contest_offices(src: pd.DataFrame, spec: dict) -> list[str]:
    if "offices" in spec:
        return [str(value) for value in spec["offices"]]
    pattern = spec["office_regex"]
    offices = sorted({str(value).strip() for value in src["office"].dropna().unique()})
    return [office for office in offices if pattern.match(office)]


def build_precinct_votes(
    src: pd.DataFrame,
    offices: list[str],
    overrides: dict[str, str],
) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for office in offices:
        precinct, _, _ = build_precinct_party_votes(
            src,
            office,
            precinct_overrides=overrides,
            election_year=2026,
        )
        if not precinct.empty:
            parts.append(precinct)
    if not parts:
        raise ValueError("No precinct votes were built for the requested offices")
    combined = pd.concat(parts, ignore_index=True)
    return combined.groupby("precinct_id", as_index=False)[
        ["dem_votes", "rep_votes", "other_votes"]
    ].sum()


def source_party_totals(src: pd.DataFrame, offices: list[str]) -> dict[str, int]:
    selected = src[src["office"].isin(offices)].copy()
    selected["votes_num"] = pd.to_numeric(selected["votes"], errors="coerce").fillna(0).round().astype(int)
    party = selected["party"].fillna("").astype(str).str.strip().str.upper()
    dem = int(selected.loc[party.isin({"DEM", "D", "DEMOCRAT", "DEMOCRATIC"}), "votes_num"].sum())
    rep = int(selected.loc[party.isin({"REP", "R", "REPUBLICAN"}), "votes_num"].sum())
    total = int(selected["votes_num"].sum())
    return {"D": dem, "R": rep, "O": total - dem - rep, "Tot": total}


def allocate_to_blocks(
    block_basis: pd.DataFrame,
    precinct_votes: pd.DataFrame,
    targets: dict[str, int],
) -> tuple[pd.DataFrame, dict[str, int]]:
    joined = block_basis.merge(precinct_votes, on="precinct_id", how="left")
    for column in ["dem_votes", "rep_votes", "other_votes"]:
        joined[column] = pd.to_numeric(joined[column], errors="coerce").fillna(0.0)

    allocated: dict[str, np.ndarray] = {}
    for output_column, vote_column, target_key in [
        ("D", "dem_votes", "D"),
        ("R", "rep_votes", "R"),
        ("O", "other_votes", "O"),
    ]:
        raw = joined[vote_column].to_numpy(float) * joined["block_weight"].to_numpy(float)
        allocated[output_column] = integer_largest_remainder(raw, targets[target_key])

    out = pd.DataFrame(
        {
            "GEOID20": joined["GEOID20"].astype(str).str.zfill(15),
            "D": allocated["D"],
            "R": allocated["R"],
            "O": allocated["O"],
        }
    )
    out["Tot"] = out["D"] + out["R"] + out["O"]
    out = out[["GEOID20", "Tot", "D", "R"]].sort_values("GEOID20").reset_index(drop=True)
    sums = {column: int(out[column].sum()) for column in ["Tot", "D", "R"]}
    sums["O"] = sums["Tot"] - sums["D"] - sums["R"]
    return out, sums


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-csv",
        type=Path,
        default=ROOT / "data/2026/20261103__nc__general__precinct.csv",
    )
    parser.add_argument(
        "--crosswalk-csv",
        type=Path,
        default=ROOT / "data/crosswalks/block20_to_onemap_2025_12.csv",
    )
    parser.add_argument(
        "--vap-csv",
        type=Path,
        default=ROOT / "data/census/block_vap_2020_nc.csv",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/dra/2026")
    args = parser.parse_args()

    src = pd.read_csv(args.results_csv, dtype=str, low_memory=False)
    crosswalk = pd.read_csv(args.crosswalk_csv, dtype=str, low_memory=False)[
        ["block_geoid20", "precinct_id"]
    ].copy()
    vap = pd.read_csv(args.vap_csv, dtype=str, low_memory=False)[
        ["block_geoid20", "vap_count"]
    ].copy()
    crosswalk["block_geoid20"] = crosswalk["block_geoid20"].astype(str).str.zfill(15)
    crosswalk["precinct_id"] = crosswalk["precinct_id"].astype(str).str.strip().str.upper()
    vap["block_geoid20"] = vap["block_geoid20"].astype(str).str.zfill(15)
    vap["vap_count"] = pd.to_numeric(vap["vap_count"], errors="coerce").fillna(0.0).clip(lower=0.0)

    # Start from the full Census block universe. Five zero-population/retired
    # blocks are not present in the current OneMap precinct crosswalk, but DRA
    # still needs their GEOID20 rows in order to accept a statewide import.
    blocks = vap.merge(crosswalk, on="block_geoid20", how="left")
    blocks["precinct_id"] = blocks["precinct_id"].fillna("")
    blocks["precinct_vap"] = blocks.groupby("precinct_id")["vap_count"].transform("sum")
    blocks["block_weight"] = np.where(
        blocks["precinct_vap"] > 0,
        blocks["vap_count"] / blocks["precinct_vap"],
        0.0,
    )
    blocks.loc[blocks["precinct_id"] == "", "block_weight"] = 0.0
    zero_vap = blocks["precinct_vap"] <= 0
    if zero_vap.any():
        first_zero = blocks[zero_vap].groupby("precinct_id", sort=False).head(1).index
        blocks.loc[first_zero, "block_weight"] = 1.0
    block_basis = blocks.rename(columns={"block_geoid20": "GEOID20"})[
        ["GEOID20", "precinct_id", "block_weight"]
    ]

    overrides = build_precinct_overrides(src, crosswalk)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "year": 2026,
        "geography": "2020 Census blocks",
        "source": args.results_csv.relative_to(ROOT).as_posix(),
        "allocation": "2020 voting-age population with statewide largest-remainder integer rounding",
        "files": [],
    }

    for spec in CONTESTS:
        offices = contest_offices(src, spec)
        precinct_votes = build_precinct_votes(src, offices, overrides)
        targets = source_party_totals(src, offices)
        dra, sums = allocate_to_blocks(block_basis, precinct_votes, targets)
        if sums != targets:
            raise ValueError(f"{spec['key']} total mismatch: expected {targets}, got {sums}")
        output = args.output_dir / str(spec["filename"])
        dra.to_csv(output, index=False, lineterminator="\n")
        manifest["files"].append(
            {
                "contest_type": spec["key"],
                "label": spec["label"],
                "file": output.name,
                "blocks": len(dra),
                "offices": len(offices),
                "totals": targets,
            }
        )
        print(f"Wrote {output.relative_to(ROOT)} ({len(dra):,} blocks; {targets})")

    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
