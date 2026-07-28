#!/usr/bin/env python3
"""Audit whether Mecklenburg 2000 precinct codes can use SBE 2006 geography.

Numeric precinct labels are not stable identifiers. This report combines the
district contests printed in the 2000 returns with the change in presidential
partisanship from 2000 to 2004 and the modern districts reached by the pilot
weights. Large discontinuities are quarantined rather than treated as valid
same-code geographic matches.
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RETURNS_2000 = ROOT / "data/2000/20001107__nc__general__precinct.csv"
RETURNS_2004 = ROOT / "data/2004/20041102__nc__general__precinct.csv"
ALIASES = ROOT / "data/mappings/legacy_precinct_abbreviation_to_sbe2006.csv"
WEIGHTS = (
    ROOT
    / "data/reports/sbe2006_to_legislative_weights_mecklenburg_vap2000_fractional.json"
)
OUT_CSV = ROOT / "data/reports/mecklenburg_2000_precinct_lineage_audit.csv"
OUT_JSON = ROOT / "data/reports/mecklenburg_2000_precinct_lineage_audit_summary.json"

SWING_QUARANTINE_PP = 35.0
HD98 = "98"
LEGISLATIVE_SCOPES = (
    "2022_state_house_mqp",
    "2022_state_senate_mqp",
    "2024_state_house",
    "2024_state_senate",
)


def precinct_code(value: str) -> str:
    """Return the leading election-system precinct code."""
    match = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)\b", value or "")
    return match.group(1) if match else ""


def pct_margin(dem: int, rep: int) -> float | None:
    total = dem + rep
    return ((dem - rep) / total * 100.0) if total else None


def signed(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:+.4f}"


def read_election(
    path: Path, president_offices: set[str]
) -> tuple[
    dict[str, dict[str, int]],
    dict[str, dict[str, set[str]]],
]:
    president: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    districts: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"house": set(), "senate": set(), "congressional": set()}
    )
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if (row.get("county") or "").strip().upper() != "MECKLENBURG":
                continue
            code = precinct_code(row.get("precinct") or "")
            if not code:
                continue
            office = (row.get("office") or "").strip().upper()
            party = (row.get("party") or "").strip().upper()
            district = (row.get("district") or "").strip().lstrip("0") or "0"
            try:
                votes = int(float(row.get("votes") or 0))
            except ValueError:
                votes = 0
            if office in president_offices and party in {"DEM", "REP"}:
                president[code][party] += votes
            if path == RETURNS_2000:
                if office.startswith("HOUSE DISTRICT "):
                    districts[code]["house"].add(district)
                elif office.startswith("SENATE DISTRICT "):
                    districts[code]["senate"].add(district)
                elif office.startswith("US HOUSE OF REP. DISTRICT "):
                    districts[code]["congressional"].add(district)
    return president, districts


def load_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    with ALIASES.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if (row.get("county") or "").upper() != "MECKLENBURG":
                continue
            if str(row.get("year") or "") != "2000":
                continue
            code = (row.get("precinct_abbrv") or "").strip()
            key = (row.get("sbe2006_key") or "").strip()
            if code and key:
                aliases.setdefault(code, key)
    return aliases


def load_modern_assignments() -> dict[str, dict[str, list[dict[str, Any]]]]:
    payload = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    scopes = payload.get("scopes") or {}
    output: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    for scope in LEGISLATIVE_SCOPES:
        precincts = (scopes.get(scope) or {}).get("precincts") or {}
        for key, shares in precincts.items():
            if key.startswith("MECKLENBURG - "):
                output[key][scope] = shares
    return output


def district_shares(
    assignments: dict[str, dict[str, list[dict[str, Any]]]],
    key: str,
    scope: str,
) -> str:
    parts = []
    for item in assignments.get(key, {}).get(scope, []):
        parts.append(f"{item.get('district')}:{float(item.get('share') or 0):.6f}")
    return "|".join(parts)


def district_id(value: Any) -> str:
    text = str(value or "").strip()
    return text.lstrip("0") or "0"


def main() -> None:
    p2000, source_districts = read_election(
        RETURNS_2000, {"PRESIDENT-VICE PRESIDENT"}
    )
    p2004, _ = read_election(RETURNS_2004, {"PRESIDENT"})
    aliases = load_aliases()
    modern = load_modern_assignments()

    rows: list[dict[str, Any]] = []
    for code in sorted(
        set(aliases) | set(p2000) | set(p2004),
        key=lambda value: (not value.replace(".", "").isdigit(), float(value)),
    ):
        key = aliases.get(code, "")
        dem00 = p2000.get(code, {}).get("DEM", 0)
        rep00 = p2000.get(code, {}).get("REP", 0)
        dem04 = p2004.get(code, {}).get("DEM", 0)
        rep04 = p2004.get(code, {}).get("REP", 0)
        margin00 = pct_margin(dem00, rep00)
        margin04 = pct_margin(dem04, rep04)
        swing = (margin04 - margin00) if margin00 is not None and margin04 is not None else None
        h2024 = district_shares(modern, key, "2024_state_house")
        feeds_hd98 = any(
            district_id(item.get("district")) == HD98
            and float(item.get("share") or 0) > 0
            for item in modern.get(key, {}).get("2024_state_house", [])
        )

        reasons: list[str] = []
        if swing is not None and abs(swing) >= SWING_QUARANTINE_PP:
            reasons.append(f"2000_to_2004_presidential_margin_change_{abs(swing):.2f}pp")
        if feeds_hd98 and reasons:
            reasons.append("invalidates_2024_HD98_same_code_input")
        elif feeds_hd98:
            reasons.append("HD98_same_code_lineage_unverified")
        if code not in aliases:
            reasons.append("no_SBE2006_alias")
        if margin00 is None:
            reasons.append("missing_2000_two_party_presidential_vote")
        if margin04 is None:
            reasons.append("missing_2004_two_party_presidential_vote")

        if feeds_hd98 and swing is not None and abs(swing) >= SWING_QUARANTINE_PP:
            status = "quarantine_hd98"
        elif swing is not None and abs(swing) >= SWING_QUARANTINE_PP:
            status = "quarantine"
        elif feeds_hd98:
            status = "unverified_hd98"
        elif reasons:
            status = "review"
        else:
            status = "no_discontinuity_flag"

        districts = source_districts.get(code) or {
            "house": set(),
            "senate": set(),
            "congressional": set(),
        }
        rows.append(
            {
                "precinct_code_2000": code,
                "assumed_sbe2006_key": key,
                "status": status,
                "reason": ";".join(reasons),
                "president_2000_dem": dem00,
                "president_2000_rep": rep00,
                "president_2000_two_party_votes": dem00 + rep00,
                "president_2000_dem_margin_pct": signed(margin00),
                "president_2004_dem": dem04,
                "president_2004_rep": rep04,
                "president_2004_two_party_votes": dem04 + rep04,
                "president_2004_dem_margin_pct": signed(margin04),
                "margin_change_2000_to_2004_pp": signed(swing),
                "source_2000_house_districts": "|".join(sorted(districts["house"], key=int)),
                "source_2000_senate_districts": "|".join(sorted(districts["senate"], key=int)),
                "source_2000_congressional_districts": "|".join(
                    sorted(districts["congressional"], key=int)
                ),
                "feeds_2022_house": district_shares(modern, key, "2022_state_house_mqp"),
                "feeds_2022_senate": district_shares(modern, key, "2022_state_senate_mqp"),
                "feeds_2024_house": h2024,
                "feeds_2024_senate": district_shares(modern, key, "2024_state_senate"),
                "feeds_2024_hd98": feeds_hd98,
            }
        )

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    quarantined = [row for row in rows if str(row["status"]).startswith("quarantine")]
    hd98_rows = [row for row in rows if row["feeds_2024_hd98"]]
    hd98_quarantined = [
        row for row in hd98_rows if str(row["status"]).startswith("quarantine")
    ]
    summary = {
        "schema": "mecklenburg_2000_precinct_lineage_audit.v1",
        "purpose": "Reject unsafe 2000-code-to-SBE2006-geography assumptions before legislative aggregation.",
        "swing_quarantine_threshold_pp": SWING_QUARANTINE_PP,
        "precinct_codes_audited": len(rows),
        "quarantined_precinct_codes": len(quarantined),
        "quarantined_codes": [row["precinct_code_2000"] for row in quarantined],
        "hd98_same_code_feeder_codes": [
            row["precinct_code_2000"] for row in hd98_rows
        ],
        "hd98_quarantined_codes": [
            row["precinct_code_2000"] for row in hd98_quarantined
        ],
        "hd98_lineage_valid": not hd98_quarantined,
        "production_safe": False,
        "production_safe_reason": (
            "The 2024 HD98 pilot includes 2000 precinct codes whose 2000-to-2004 "
            "returns change too sharply to represent stable same-code geography."
        ),
        "audit_csv": str(OUT_CSV.relative_to(ROOT)).replace("\\", "/"),
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Wrote {OUT_CSV}")
    print(f"Wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
