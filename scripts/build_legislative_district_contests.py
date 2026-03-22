"""
Build direct district-contest slices for NC legislative races.

This script reads a precinct-level general-election CSV where the `office` field
contains district-specific labels (for example, "NC HOUSE OF REPRESENTATIVES DISTRICT 001"),
aggregates votes by district, and writes district contest slices:

  - state_house_state_house_<year>.json
  - state_senate_state_senate_<year>.json

It also updates data/district_contests/manifest.json entries for those slices.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


HOUSE_OFFICE_RE = re.compile(r"^NC HOUSE OF REPRESENTATIVES DISTRICT\s*0*([0-9]+)\s*$", re.IGNORECASE)
SENATE_OFFICE_RE = re.compile(r"^NC STATE SENATE DISTRICT\s*0*([0-9]+)\s*$", re.IGNORECASE)

DEM_PARTY_CODES = {"DEM", "D", "DEMOCRAT", "DEMOCRATIC"}
REP_PARTY_CODES = {"REP", "R", "REPUBLICAN"}


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


def party_group(raw_party: str) -> str:
    p = str(raw_party or "").strip().upper()
    if p in DEM_PARTY_CODES:
        return "dem_votes"
    if p in REP_PARTY_CODES:
        return "rep_votes"
    return "other_votes"


def _extract_district_number(office: str, chamber: str) -> str | None:
    office_u = str(office or "").strip().upper()
    pattern = HOUSE_OFFICE_RE if chamber == "state_house" else SENATE_OFFICE_RE
    m = pattern.match(office_u)
    if not m:
        return None
    return str(int(m.group(1)))


def _top_candidate(cand_votes: dict[str, int]) -> str:
    if not cand_votes:
        return ""
    return sorted(cand_votes.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)[0][0]


def _candidate_with_fallback(candidate: str, *, votes: int, party: str) -> str:
    """
    Ensure district rows do not emit empty major-party candidate labels.
    """
    c = str(candidate or "").strip()
    if c:
        return c
    if votes <= 0:
        if party == "dem":
            return "No Democratic Candidate"
        if party == "rep":
            return "No Republican Candidate"
        return ""
    if party == "dem":
        return "Democratic Candidate (Unspecified)"
    if party == "rep":
        return "Republican Candidate (Unspecified)"
    return ""


def _build_payload_from_aggregates(
    district_totals: dict[str, dict[str, int]],
    district_dem_candidates: dict[str, dict[str, int]],
    district_rep_candidates: dict[str, dict[str, int]],
    *,
    year: int,
    scope: str,
    contest_type: str,
    office_label: str,
) -> tuple[dict, int]:
    if not district_totals:
        payload = {
            "year": int(year),
            "scope": scope,
            "contest_type": contest_type,
            "meta": {
                "match_coverage_pct": 0.0,
                "matched_precinct_keys": 0,
                "total_precinct_keys": 0,
                "source": "ncsbe_legislative_district_totals",
                "office": office_label,
                "nongeo_allocation_mode": "direct_district_totals",
            },
            "general": {"results": {}},
        }
        return payload, 0

    results: dict[str, dict] = {}
    for district in sorted(district_totals.keys(), key=lambda d: int(str(d))):
        totals = district_totals.get(district, {})
        dem = int(totals.get("dem_votes", 0) or 0)
        rep = int(totals.get("rep_votes", 0) or 0)
        oth = int(totals.get("other_votes", 0) or 0)
        total_votes = dem + rep + oth
        margin = rep - dem
        margin_pct = (margin / total_votes * 100.0) if total_votes else 0.0
        if margin > 0:
            winner = "REP"
        elif margin < 0:
            winner = "DEM"
        else:
            winner = "TIE"
        dem_candidate = _candidate_with_fallback(
            _top_candidate(district_dem_candidates.get(district, {})),
            votes=dem,
            party="dem",
        )
        rep_candidate = _candidate_with_fallback(
            _top_candidate(district_rep_candidates.get(district, {})),
            votes=rep,
            party="rep",
        )

        results[district] = {
            "dem_votes": dem,
            "rep_votes": rep,
            "other_votes": oth,
            "total_votes": total_votes,
            "dem_candidate": dem_candidate,
            "rep_candidate": rep_candidate,
            "margin": margin,
            "margin_pct": round(margin_pct, 2),
            "winner": winner,
            "competitiveness": {"color": calculate_competitiveness(margin_pct)},
        }

    district_count = len(results)
    payload = {
        "year": int(year),
        "scope": scope,
        "contest_type": contest_type,
        "meta": {
            "match_coverage_pct": 100.0,
            "matched_precinct_keys": district_count,
            "total_precinct_keys": district_count,
            "source": "ncsbe_legislative_district_totals",
            "office": office_label,
            "nongeo_allocation_mode": "direct_district_totals",
        },
        "general": {"results": results},
    }
    return payload, district_count


def _update_district_manifest(manifest_path: Path, entries: list[dict]) -> None:
    manifest = {"files": []}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = list(manifest.get("files") or [])

    index = {}
    for i, e in enumerate(files):
        key = (int(e.get("year", -1)), str(e.get("scope", "")), str(e.get("contest_type", "")))
        index[key] = i

    for e in entries:
        key = (int(e["year"]), str(e["scope"]), str(e["contest_type"]))
        if key in index:
            files[index[key]] = e
        else:
            files.append(e)
            index[key] = len(files) - 1

    files.sort(key=lambda x: (int(x.get("year", 0)), str(x.get("scope", "")), str(x.get("contest_type", ""))))
    manifest_path.write_text(json.dumps({"files": files}, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build direct NC legislative district contest slices.")
    parser.add_argument("--year", type=int, default=2022)
    parser.add_argument("--results-csv", type=Path, default=Path("data/2022/20221108__nc__general__precinct.csv"))
    parser.add_argument("--district-contests-dir", type=Path, default=Path("data/district_contests"))
    args = parser.parse_args()

    house_totals: dict[str, dict[str, int]] = {}
    senate_totals: dict[str, dict[str, int]] = {}
    house_dem_cands: dict[str, dict[str, int]] = {}
    house_rep_cands: dict[str, dict[str, int]] = {}
    senate_dem_cands: dict[str, dict[str, int]] = {}
    senate_rep_cands: dict[str, dict[str, int]] = {}

    with args.results_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"office", "party", "candidate", "votes"}
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"results CSV missing required columns: {', '.join(missing)}")

        for row in reader:
            office = str(row.get("office") or "")
            house_district = _extract_district_number(office, "state_house")
            senate_district = _extract_district_number(office, "state_senate")
            if not house_district and not senate_district:
                continue

            try:
                votes = int(round(float(str(row.get("votes") or "0").strip() or "0")))
            except ValueError:
                votes = 0
            if votes == 0:
                continue

            group = party_group(str(row.get("party") or ""))
            candidate = str(row.get("candidate") or "").strip()

            if house_district:
                h = house_totals.setdefault(house_district, {"dem_votes": 0, "rep_votes": 0, "other_votes": 0})
                h[group] = int(h.get(group, 0) + votes)
                if candidate:
                    if group == "dem_votes":
                        dmap = house_dem_cands.setdefault(house_district, {})
                        dmap[candidate] = int(dmap.get(candidate, 0) + votes)
                    elif group == "rep_votes":
                        rmap = house_rep_cands.setdefault(house_district, {})
                        rmap[candidate] = int(rmap.get(candidate, 0) + votes)

            if senate_district:
                s = senate_totals.setdefault(senate_district, {"dem_votes": 0, "rep_votes": 0, "other_votes": 0})
                s[group] = int(s.get(group, 0) + votes)
                if candidate:
                    if group == "dem_votes":
                        dmap = senate_dem_cands.setdefault(senate_district, {})
                        dmap[candidate] = int(dmap.get(candidate, 0) + votes)
                    elif group == "rep_votes":
                        rmap = senate_rep_cands.setdefault(senate_district, {})
                        rmap[candidate] = int(rmap.get(candidate, 0) + votes)

    args.district_contests_dir.mkdir(parents=True, exist_ok=True)

    payload_house, districts_house = _build_payload_from_aggregates(
        house_totals,
        house_dem_cands,
        house_rep_cands,
        year=int(args.year),
        scope="state_house",
        contest_type="state_house",
        office_label="NC HOUSE OF REPRESENTATIVES",
    )
    payload_senate, districts_senate = _build_payload_from_aggregates(
        senate_totals,
        senate_dem_cands,
        senate_rep_cands,
        year=int(args.year),
        scope="state_senate",
        contest_type="state_senate",
        office_label="NC STATE SENATE",
    )

    out_house = args.district_contests_dir / f"state_house_state_house_{int(args.year)}.json"
    out_senate = args.district_contests_dir / f"state_senate_state_senate_{int(args.year)}.json"
    out_house.write_text(json.dumps(payload_house, separators=(",", ":")), encoding="utf-8")
    out_senate.write_text(json.dumps(payload_senate, separators=(",", ":")), encoding="utf-8")

    manifest_entries = [
        {
            "year": int(args.year),
            "scope": "state_house",
            "contest_type": "state_house",
            "file": out_house.name,
            "districts": int(districts_house),
        },
        {
            "year": int(args.year),
            "scope": "state_senate",
            "contest_type": "state_senate",
            "file": out_senate.name,
            "districts": int(districts_senate),
        },
    ]
    _update_district_manifest(args.district_contests_dir / "manifest.json", manifest_entries)

    print(f"Wrote {out_house} ({districts_house} districts)")
    print(f"Wrote {out_senate} ({districts_senate} districts)")
    print(f"Updated {(args.district_contests_dir / 'manifest.json')}")


if __name__ == "__main__":
    main()
