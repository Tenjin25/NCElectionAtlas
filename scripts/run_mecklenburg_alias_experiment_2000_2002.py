#!/usr/bin/env python3
from __future__ import annotations

"""Run a staging-only Mecklenburg 2000/2002 precinct alias experiment.

The script creates a report-scoped override CSV by copying the production
precinct overrides and appending only the six source-backed Mecklenburg aliases
under review. It then rebuilds the focused 2022-line State House/Senate slices
into a separate experiment directory and writes comparison/validation reports.
"""

import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

PRODUCTION_OVERRIDES = ROOT / "data/mappings/precinct_key_overrides.csv"
STAGED_OVERRIDES = ROOT / "data/reports/mecklenburg_2000_2002_alias_experiment_precinct_overrides.csv"
SOURCE_CD_CROSSWALK_CANDIDATES = (
    ROOT / "data/crosswalks/block20_to_cd118.csv",
    ROOT / "data/tmp/block_assign_extract/NC_CD118.csv",
)
STAGED_CD_FILE = ROOT / "data/reports/mecklenburg_2000_2002_alias_experiment_cd118_builder_input.csv"
PRODUCTION_DIR = ROOT / "data/district_contests"
COUNTY_WEIGHTS_DIR = ROOT / "data/district_contests_mecklenburg_alloc_experiment_county_weights"
STAGED_OUTPUT_DIR = ROOT / "data/district_contests_mecklenburg_alias_experiment_2000_2002"
COMPARE_CSV = ROOT / "data/reports/mecklenburg_2000_2002_alias_experiment_compare.csv"
SUMMARY_JSON = ROOT / "data/reports/mecklenburg_2000_2002_alias_experiment_summary.json"
AUDIT_MARGINS_CSV = ROOT / "data/reports/audit_mecklenburg_2000_2002_state_legislative_margins.csv"
MATCH_CROSSWALK = ROOT / "data/crosswalks/block20_to_sbe_2006_via_block00_nhgis_filled.csv"
DISTRICT_WEIGHTS_JSON = ROOT / "data/mappings/sbe2006_to_modern_district_weights.json"

ALIASES = {
    "78 78": "078.1",
    "107 107": "107.1",
    "139 139": "139.1",
    "204 204": "204.1",
    "223 223": "223.1",
    "238 238": "238.1",
}
YEARS = (2000, 2002)
BLOCKED_RAW_KEYS = ("900 900", "901 901")
NON_GEO_RAW_KEYS = ("ABSENTEE/PROVISIONAL",)

TARGET_DISTRICTS = {
    "state_house": ["88", "92", "98", "99", "100", "101", "102", "103", "104", "105", "106", "107", "112"],
    "state_senate": ["37", "38", "39", "40", "41", "42"],
}

RUNS = [
    {
        "year": 2000,
        "results_csv": ROOT / "data/2000/20001107__nc__general__precinct.csv",
        "contest_type_regex": "^(president|governor)$",
    },
    {
        "year": 2002,
        "results_csv": ROOT / "data/2002/20021105__nc__general__precinct.csv",
        "contest_type_regex": "^us_senate$",
    },
]

EXPECTED_FILES = [
    "state_house_president_2000.json",
    "state_senate_president_2000.json",
    "state_house_governor_2000.json",
    "state_senate_governor_2000.json",
    "state_house_us_senate_2002.json",
    "state_senate_us_senate_2002.json",
]

COMPARE_FIELDS = [
    "file",
    "year",
    "scope",
    "contest_type",
    "district",
    "district_label",
    "available_baseline_source",
    "available_baseline_margin_pct",
    "production_dem_votes",
    "production_rep_votes",
    "production_other_votes",
    "production_total_votes",
    "production_margin",
    "production_margin_pct",
    "production_winner",
    "staged_dem_votes",
    "staged_rep_votes",
    "staged_other_votes",
    "staged_total_votes",
    "staged_margin",
    "staged_margin_pct",
    "staged_winner",
    "county_weights_dem_votes",
    "county_weights_rep_votes",
    "county_weights_other_votes",
    "county_weights_total_votes",
    "county_weights_margin",
    "county_weights_margin_pct",
    "county_weights_winner",
    "staged_minus_production_margin",
    "staged_minus_production_margin_pct_pp",
    "county_weights_minus_production_margin",
    "county_weights_minus_production_margin_pct_pp",
    "staged_minus_county_weights_margin",
    "staged_minus_county_weights_margin_pct_pp",
    "production_abs_delta_to_baseline_pp",
    "staged_abs_delta_to_baseline_pp",
    "county_weights_abs_delta_to_baseline_pp",
    "staged_improved_vs_production_baseline",
    "staged_closer_than_county_weights_baseline",
    "winner_flip_vs_production",
]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def to_int(value: Any) -> int:
    try:
        return int(round(float(value or 0)))
    except Exception:
        return 0


def to_float_or_none(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def round_or_blank(value: float | None, digits: int = 2) -> float | str:
    if value is None:
        return ""
    return round(float(value), digits)


def normalize_key(value: str) -> str:
    return " ".join(str(value or "").strip().upper().split())


def district_label(scope: str, district: str) -> str:
    prefix = "HD" if scope == "state_house" else "SD"
    return f"{prefix}-{int(district):03d}" if scope == "state_house" else f"{prefix}-{int(district):02d}"


def infer_contest_type(office: str) -> str | None:
    office_u = " ".join(str(office or "").strip().upper().split())
    if office_u in {
        "US PRESIDENT",
        "PRESIDENT",
        "PRESIDENT-VICE PRESIDENT",
        "PRESIDENT AND VICE PRESIDENT",
        "PRESIDENT-VICE-PRESIDENT",
    }:
        return "president"
    if office_u in {"NC GOVERNOR", "GOVERNOR"}:
        return "governor"
    if office_u in {"US SENATE", "UNITED STATES SENATE"}:
        return "us_senate"
    return None


def write_staged_overrides() -> dict[str, Any]:
    STAGED_OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
    with PRODUCTION_OVERRIDES.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        production_rows = list(reader)
        base_fields = list(reader.fieldnames or [])

    fields = list(base_fields)
    if "experiment_note" not in fields:
        fields.append("experiment_note")

    rows: list[dict[str, str]] = []
    existing_keys: set[tuple[str, str]] = set()
    for row in production_rows:
        out = {field: str(row.get(field, "") or "") for field in fields}
        rows.append(out)
        existing_keys.add((out.get("year", "").strip(), normalize_key(out.get("raw_precinct_key", ""))))

    alias_rows: list[dict[str, str]] = []
    for year in YEARS:
        for raw, target in ALIASES.items():
            raw_key = f"MECKLENBURG - {raw}"
            canonical_key = f"MECKLENBURG - {target}"
            key = (str(year), normalize_key(raw_key))
            if key in existing_keys:
                continue
            row = {field: "" for field in fields}
            row.update(
                {
                    "year": str(year),
                    "raw_precinct_key": raw_key,
                    "canonical_precinct_key": canonical_key,
                    "experiment_note": "staging-only source-backed Mecklenburg pre-2005 split alias",
                }
            )
            rows.append(row)
            alias_rows.append(row)

    with STAGED_OVERRIDES.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    return {
        "production_override_rows_copied": len(production_rows),
        "alias_rows_appended": len(alias_rows),
        "staged_override_rows": len(rows),
        "staged_override_file": rel(STAGED_OVERRIDES),
    }


def write_staged_cd_file() -> dict[str, Any]:
    """Create the CD118 input shape expected by the builder without touching source data."""
    source = next((path for path in SOURCE_CD_CROSSWALK_CANDIDATES if path.exists()), None)
    if source is None:
        tried = ", ".join(rel(path) for path in SOURCE_CD_CROSSWALK_CANDIDATES)
        raise FileNotFoundError(f"Missing CD118 block assignment; tried: {tried}")

    rows = 0
    with source.open(newline="", encoding="utf-8") as src, STAGED_CD_FILE.open(
        "w", newline="", encoding="utf-8"
    ) as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=["GEOID", "CDFP"], lineterminator="\n")
        writer.writeheader()
        for row in reader:
            geoid = str(row.get("block_geoid20") or row.get("GEOID") or "").strip()
            district = str(row.get("district") or row.get("CDFP") or "").strip()
            if not geoid or not district:
                continue
            writer.writerow({"GEOID": geoid, "CDFP": district})
            rows += 1
    return {"source": rel(source), "staged_cd_file": rel(STAGED_CD_FILE), "rows": rows}


def run_builds() -> list[dict[str, Any]]:
    STAGED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in EXPECTED_FILES + ["manifest.json"]:
        target = STAGED_OUTPUT_DIR / name
        if target.exists():
            target.unlink()

    summaries = []
    builder = ROOT / "scripts/build_district_contests_from_batch_shatter.py"
    for run in RUNS:
        cmd = [
            sys.executable,
            str(builder),
            "--year",
            str(run["year"]),
            "--results-csv",
            str(run["results_csv"]),
            "--district-contests-dir",
            str(STAGED_OUTPUT_DIR),
            "--precinct-overrides-csv",
            str(STAGED_OVERRIDES),
            "--contest-type-regex",
            str(run["contest_type_regex"]),
            "--office-source",
            "auto",
            "--emit-scopes",
            "state_house,state_senate",
            "--cd-file",
            str(STAGED_CD_FILE),
            "--allocation-year",
            "2022",
            "--district-lines-year",
            "2022",
            "--district-lines-label",
            "2022 lines Mecklenburg alias experiment",
            "--nongeo-allocation-mode",
            "precinct_candidate",
        ]
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
        summaries.append(
            {
                "year": run["year"],
                "command": " ".join(cmd),
                "returncode": proc.returncode,
                "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-20:]),
                "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-20:]),
            }
        )
        if proc.returncode != 0:
            raise SystemExit(f"Build failed for {run['year']} with exit code {proc.returncode}:\n{proc.stderr}")
    return summaries


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def get_result(payload: dict[str, Any], district: str) -> dict[str, Any]:
    results = ((payload.get("general") or {}).get("results") or {})
    return dict(results.get(str(int(district))) or {})


def load_available_baselines() -> dict[tuple[str, int, str, str], dict[str, Any]]:
    if not AUDIT_MARGINS_CSV.exists():
        return {}
    out: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    with AUDIT_MARGINS_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            scope = str(row.get("scope", "")).strip()
            contest = str(row.get("contest", "")).strip()
            district = str(row.get("district", "")).strip().lstrip("0") or "0"
            try:
                year = int(row.get("year", "0"))
            except ValueError:
                continue
            existing = to_float_or_none(row.get("existing_snapshot_margin_pct"))
            dra = to_float_or_none(row.get("dra_review_margin_pct"))
            source = ""
            value = None
            if existing is not None:
                source = "existing_snapshot"
                value = existing
            elif dra is not None:
                source = "dra_review"
                value = dra
            out[(scope, year, contest, district)] = {"source": source, "margin_pct": value}
    return out


def compare_outputs() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    baselines = load_available_baselines()
    rows: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    vote_errors: list[str] = []
    file_meta: dict[str, Any] = {}

    for name in EXPECTED_FILES:
        staged_path = STAGED_OUTPUT_DIR / name
        production_path = PRODUCTION_DIR / name
        county_path = COUNTY_WEIGHTS_DIR / name
        try:
            staged_payload = load_json(staged_path)
            production_payload = load_json(production_path)
            county_payload = load_json(county_path) if county_path.exists() else {}
        except Exception as exc:
            parse_errors.append(f"{name}: {exc}")
            continue

        scope = str(staged_payload.get("scope") or "")
        year = int(staged_payload.get("year") or 0)
        contest_type = str(staged_payload.get("contest_type") or "")
        file_meta[name] = {
            "match_coverage_pct": (staged_payload.get("meta") or {}).get("match_coverage_pct"),
            "matched_precinct_keys": (staged_payload.get("meta") or {}).get("matched_precinct_keys"),
            "total_precinct_keys": (staged_payload.get("meta") or {}).get("total_precinct_keys"),
            "nongeo_allocation_mode": (staged_payload.get("meta") or {}).get("nongeo_allocation_mode"),
            "district_lines_year": (staged_payload.get("meta") or {}).get("district_lines_year"),
            "district_lines_label": (staged_payload.get("meta") or {}).get("district_lines_label"),
        }

        for district in TARGET_DISTRICTS.get(scope, []):
            prod = get_result(production_payload, district)
            staged = get_result(staged_payload, district)
            county = get_result(county_payload, district) if county_payload else {}
            baseline = baselines.get((scope, year, contest_type, district), {})
            baseline_pct = baseline.get("margin_pct")
            baseline_source = baseline.get("source") or ""

            for label, result in (("staged", staged), ("production", prod), ("county_weights", county)):
                if not result:
                    continue
                dem = to_int(result.get("dem_votes"))
                rep = to_int(result.get("rep_votes"))
                other = to_int(result.get("other_votes"))
                total = to_int(result.get("total_votes"))
                margin = to_int(result.get("margin"))
                if total != dem + rep + other:
                    vote_errors.append(f"{name} {district} {label}: total mismatch")
                if margin != rep - dem:
                    vote_errors.append(f"{name} {district} {label}: margin mismatch")

            production_margin_pct = to_float_or_none(prod.get("margin_pct"))
            staged_margin_pct = to_float_or_none(staged.get("margin_pct"))
            county_margin_pct = to_float_or_none(county.get("margin_pct"))
            production_abs = abs(production_margin_pct - baseline_pct) if baseline_pct is not None and production_margin_pct is not None else None
            staged_abs = abs(staged_margin_pct - baseline_pct) if baseline_pct is not None and staged_margin_pct is not None else None
            county_abs = abs(county_margin_pct - baseline_pct) if baseline_pct is not None and county_margin_pct is not None else None

            row = {
                "file": name,
                "year": year,
                "scope": scope,
                "contest_type": contest_type,
                "district": district,
                "district_label": district_label(scope, district),
                "available_baseline_source": baseline_source,
                "available_baseline_margin_pct": round_or_blank(baseline_pct),
                "production_dem_votes": to_int(prod.get("dem_votes")),
                "production_rep_votes": to_int(prod.get("rep_votes")),
                "production_other_votes": to_int(prod.get("other_votes")),
                "production_total_votes": to_int(prod.get("total_votes")),
                "production_margin": to_int(prod.get("margin")),
                "production_margin_pct": round_or_blank(production_margin_pct),
                "production_winner": prod.get("winner", ""),
                "staged_dem_votes": to_int(staged.get("dem_votes")),
                "staged_rep_votes": to_int(staged.get("rep_votes")),
                "staged_other_votes": to_int(staged.get("other_votes")),
                "staged_total_votes": to_int(staged.get("total_votes")),
                "staged_margin": to_int(staged.get("margin")),
                "staged_margin_pct": round_or_blank(staged_margin_pct),
                "staged_winner": staged.get("winner", ""),
                "county_weights_dem_votes": to_int(county.get("dem_votes")),
                "county_weights_rep_votes": to_int(county.get("rep_votes")),
                "county_weights_other_votes": to_int(county.get("other_votes")),
                "county_weights_total_votes": to_int(county.get("total_votes")),
                "county_weights_margin": to_int(county.get("margin")),
                "county_weights_margin_pct": round_or_blank(county_margin_pct),
                "county_weights_winner": county.get("winner", ""),
                "staged_minus_production_margin": to_int(staged.get("margin")) - to_int(prod.get("margin")),
                "staged_minus_production_margin_pct_pp": round_or_blank(
                    staged_margin_pct - production_margin_pct
                    if staged_margin_pct is not None and production_margin_pct is not None
                    else None
                ),
                "county_weights_minus_production_margin": to_int(county.get("margin")) - to_int(prod.get("margin")) if county else "",
                "county_weights_minus_production_margin_pct_pp": round_or_blank(
                    county_margin_pct - production_margin_pct
                    if county_margin_pct is not None and production_margin_pct is not None
                    else None
                ),
                "staged_minus_county_weights_margin": to_int(staged.get("margin")) - to_int(county.get("margin")) if county else "",
                "staged_minus_county_weights_margin_pct_pp": round_or_blank(
                    staged_margin_pct - county_margin_pct
                    if staged_margin_pct is not None and county_margin_pct is not None
                    else None
                ),
                "production_abs_delta_to_baseline_pp": round_or_blank(production_abs),
                "staged_abs_delta_to_baseline_pp": round_or_blank(staged_abs),
                "county_weights_abs_delta_to_baseline_pp": round_or_blank(county_abs),
                "staged_improved_vs_production_baseline": (
                    staged_abs is not None and production_abs is not None and staged_abs < production_abs
                ),
                "staged_closer_than_county_weights_baseline": (
                    staged_abs is not None and county_abs is not None and staged_abs < county_abs
                ),
                "winner_flip_vs_production": bool(staged.get("winner") and prod.get("winner") and staged.get("winner") != prod.get("winner")),
            }
            rows.append(row)

    COMPARE_CSV.parent.mkdir(parents=True, exist_ok=True)
    with COMPARE_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COMPARE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    validation = {
        "json_parse_errors": parse_errors,
        "vote_consistency_errors": vote_errors,
        "json_files_parsed": len(file_meta),
        "file_meta": file_meta,
    }
    return rows, validation


def load_match_precincts() -> set[str]:
    precincts: set[str] = set()
    with MATCH_CROSSWALK.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = normalize_key(row.get("precinct_id", ""))
            if key:
                precincts.add(key)
    return precincts


def load_weight_precincts() -> set[str]:
    try:
        payload = load_json(DISTRICT_WEIGHTS_JSON)
    except Exception:
        return set()
    scope_sets = payload.get("scope_sets") or {}
    scopes = payload.get("scopes") or {}
    scope_names = (scope_sets.get("2022") or {})
    out: set[str] = set()
    for district_type in ("state_house", "state_senate"):
        scope_name = scope_names.get(district_type)
        scope = scopes.get(scope_name) if scope_name else None
        precincts = (scope or {}).get("precincts") or {}
        out.update(normalize_key(key) for key in precincts)
    return {key for key in out if key}


def source_key_validation(staged_override_info: dict[str, Any]) -> dict[str, Any]:
    match_precincts = load_match_precincts()
    weight_precincts = load_weight_precincts()
    alias_targets = {f"MECKLENBURG - {target}" for target in ALIASES.values()}
    alias_raw_keys = {f"MECKLENBURG - {raw}" for raw in ALIASES}
    blocked_keys = {f"MECKLENBURG - {raw}" for raw in BLOCKED_RAW_KEYS}
    non_geo_keys = {"MECKLENBURG - ABSENTEE/PROVISIONAL", "MECKLENBURG - ABSENTEE/PROVISIONAL".replace("/", " ")}

    staged_rows: list[dict[str, str]] = []
    with STAGED_OVERRIDES.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            staged_rows.append({k: str(v or "") for k, v in row.items()})

    overrides_by_year = {
        (row.get("year", "").strip(), normalize_key(row.get("raw_precinct_key", ""))): normalize_key(
            row.get("canonical_precinct_key", "")
        )
        for row in staged_rows
    }

    source_rows: dict[str, dict[str, Any]] = {}
    for run in RUNS:
        year = int(run["year"])
        with Path(run["results_csv"]).open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                contest_type = infer_contest_type(row.get("office", ""))
                if year == 2000 and contest_type not in {"president", "governor"}:
                    continue
                if year == 2002 and contest_type != "us_senate":
                    continue
                county = str(row.get("county", "")).strip().upper()
                if county != "MECKLENBURG":
                    continue
                raw_precinct = str(row.get("precinct", "")).strip()
                raw_key = f"{county} - {raw_precinct}"
                raw_key_norm = normalize_key(raw_key)
                raw_precinct_norm = normalize_key(raw_precinct)
                if raw_precinct_norm not in {normalize_key(x) for x in [*ALIASES.keys(), *BLOCKED_RAW_KEYS, "absentee/provisional"]}:
                    continue
                key = f"{year}:{contest_type}:{raw_key_norm}"
                entry = source_rows.setdefault(
                    key,
                    {
                        "year": year,
                        "contest_type": contest_type,
                        "raw_precinct_key": raw_key_norm,
                        "votes": 0,
                        "mapped_key_after_staged_overrides": overrides_by_year.get((str(year), raw_key_norm), raw_key_norm),
                    },
                )
                entry["votes"] += to_int(row.get("votes"))

    return {
        "alias_targets_present_in_match_crosswalk": {
            key: normalize_key(key) in match_precincts for key in sorted(alias_targets)
        },
        "alias_targets_present_in_2022_district_weights": {
            key: normalize_key(key) in weight_precincts for key in sorted(alias_targets)
        },
        "raw_alias_keys_present_in_match_crosswalk": {
            key: normalize_key(key) in match_precincts for key in sorted(alias_raw_keys)
        },
        "blocked_900_901_present_in_staged_overrides": any(
            normalize_key(row.get("raw_precinct_key", "")) in {normalize_key(key) for key in blocked_keys}
            for row in staged_rows
        ),
        "blocked_900_901_present_in_match_crosswalk": {
            key: normalize_key(key) in match_precincts for key in sorted(blocked_keys)
        },
        "blocked_900_901_present_in_2022_district_weights": {
            key: normalize_key(key) in weight_precincts for key in sorted(blocked_keys)
        },
        "absentee_provisional_present_in_staged_overrides": any(
            "ABSENTEE" in normalize_key(row.get("raw_precinct_key", ""))
            or "PROVISIONAL" in normalize_key(row.get("raw_precinct_key", ""))
            for row in staged_rows
        ),
        "absentee_provisional_classification": "non_geographic_allocation_bucket",
        "source_special_key_totals_after_staged_overrides": list(source_rows.values()),
        "staged_override_info": staged_override_info,
    }


def summarize(rows: list[dict[str, Any]], build_summaries: list[dict[str, Any]], validation: dict[str, Any]) -> dict[str, Any]:
    def numeric(row: dict[str, Any], key: str) -> float | None:
        value = row.get(key)
        if value == "":
            return None
        return to_float_or_none(value)

    with_baseline = [r for r in rows if numeric(r, "available_baseline_margin_pct") is not None]
    improved = [r for r in with_baseline if r.get("staged_improved_vs_production_baseline") is True]
    worsened = [
        r
        for r in with_baseline
        if numeric(r, "staged_abs_delta_to_baseline_pp") is not None
        and numeric(r, "production_abs_delta_to_baseline_pp") is not None
        and numeric(r, "staged_abs_delta_to_baseline_pp") > numeric(r, "production_abs_delta_to_baseline_pp")
    ]

    def mean_abs_delta(key: str) -> float | None:
        vals = [numeric(row, key) for row in with_baseline]
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    by_contest_scope: dict[str, Any] = {}
    for row in rows:
        group_key = f"{row['scope']}_{row['contest_type']}_{row['year']}"
        g = by_contest_scope.setdefault(
            group_key,
            {
                "districts_reported": 0,
                "max_abs_staged_minus_production_margin_pct_pp": 0.0,
                "staged_winner_flips_vs_production": [],
                "baseline_rows": 0,
                "baseline_rows_improved_vs_production": 0,
                "baseline_rows_worsened_vs_production": 0,
            },
        )
        g["districts_reported"] += 1
        delta = abs(float(row.get("staged_minus_production_margin_pct_pp") or 0.0))
        g["max_abs_staged_minus_production_margin_pct_pp"] = max(
            float(g["max_abs_staged_minus_production_margin_pct_pp"]), delta
        )
        if row.get("winner_flip_vs_production"):
            g["staged_winner_flips_vs_production"].append(row["district_label"])
        if numeric(row, "available_baseline_margin_pct") is not None:
            g["baseline_rows"] += 1
            staged_abs = numeric(row, "staged_abs_delta_to_baseline_pp")
            prod_abs = numeric(row, "production_abs_delta_to_baseline_pp")
            if staged_abs is not None and prod_abs is not None:
                if staged_abs < prod_abs:
                    g["baseline_rows_improved_vs_production"] += 1
                elif staged_abs > prod_abs:
                    g["baseline_rows_worsened_vs_production"] += 1

    validation_ok = not validation.get("json_parse_errors") and not validation.get("vote_consistency_errors")
    overall_staged_delta = [
        abs(float(row.get("staged_minus_production_margin_pct_pp") or 0.0)) for row in rows
    ]
    max_move = max(overall_staged_delta) if overall_staged_delta else 0.0
    mean_move = sum(overall_staged_delta) / len(overall_staged_delta) if overall_staged_delta else 0.0
    baseline_prod = mean_abs_delta("production_abs_delta_to_baseline_pp")
    baseline_staged = mean_abs_delta("staged_abs_delta_to_baseline_pp")
    improved_overall = (
        baseline_prod is not None
        and baseline_staged is not None
        and baseline_staged < baseline_prod
        and len(improved) > len(worsened)
    )

    return {
        "schema": "mecklenburg_2000_2002_alias_experiment.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Staging-only six-alias Mecklenburg 2000/2002 experiment on 2022-line State House/Senate outputs.",
        "aliases_tested": {raw.split()[0]: target for raw, target in ALIASES.items()},
        "production_dir": rel(PRODUCTION_DIR),
        "county_weights_dir": rel(COUNTY_WEIGHTS_DIR),
        "staged_output_dir": rel(STAGED_OUTPUT_DIR),
        "reports": {
            "compare_csv": rel(COMPARE_CSV),
            "summary_json": rel(SUMMARY_JSON),
            "staged_overrides_csv": rel(STAGED_OVERRIDES),
        },
        "outputs_written": [rel(STAGED_OUTPUT_DIR / name) for name in EXPECTED_FILES] + [rel(STAGED_OUTPUT_DIR / "manifest.json")],
        "builds": build_summaries,
        "row_count": len(rows),
        "baseline_row_count": len(with_baseline),
        "baseline_rows_improved_vs_production": len(improved),
        "baseline_rows_worsened_vs_production": len(worsened),
        "mean_abs_delta_to_available_baseline_pct": {
            "production": baseline_prod,
            "staged_alias_experiment": baseline_staged,
            "county_weights": mean_abs_delta("county_weights_abs_delta_to_baseline_pp"),
        },
        "max_abs_staged_minus_production_margin_pct_pp": round(max_move, 4),
        "mean_abs_staged_minus_production_margin_pct_pp": round(mean_move, 4),
        "winner_flips_vs_production": [
            {
                "year": row["year"],
                "contest_type": row["contest_type"],
                "scope": row["scope"],
                "district_label": row["district_label"],
                "production_winner": row["production_winner"],
                "staged_winner": row["staged_winner"],
            }
            for row in rows
            if row.get("winner_flip_vs_production")
        ],
        "by_contest_scope": by_contest_scope,
        "validation": validation,
        "interpretation": {
            "improved_suspect_districts": improved_overall,
            "safe_enough_for_later_production_mapping": bool(validation_ok and improved_overall),
            "notes": [
                "ABSENTEE/PROVISIONAL was not included in staged overrides and remains a non-geographic allocation bucket.",
                "900 and 901 were not included in staged overrides and remain blocked/unmapped.",
                "Production alias/mapping files and data/district_contests were not modified.",
            ],
        },
    }


def main() -> None:
    staged_override_info = write_staged_overrides()
    staged_cd_info = write_staged_cd_file()
    build_summaries = run_builds()
    rows, validation = compare_outputs()
    validation["source_key_validation"] = source_key_validation(staged_override_info)
    validation["staged_cd_input"] = staged_cd_info
    summary = summarize(rows, build_summaries, validation)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["interpretation"], indent=2))
    print(f"Wrote staged outputs: {rel(STAGED_OUTPUT_DIR)}")
    print(f"Wrote comparison CSV: {rel(COMPARE_CSV)}")
    print(f"Wrote summary JSON: {rel(SUMMARY_JSON)}")


if __name__ == "__main__":
    main()
