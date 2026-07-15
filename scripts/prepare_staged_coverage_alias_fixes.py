#!/usr/bin/env python3
"""Prepare report-only staged coverage and alias-fix diagnostics.

This workflow is intentionally separate from the district aggregation builders.
It reads the already-generated staged coverage diagnostic plus lightweight
mapping/report artifacts, then emits corrected per-scope coverage diagnostics
and source-backed alias candidate buckets under data/reports.

It does not modify staged aggregation outputs, production contest directories,
or mapping files.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DIAGNOSTIC_CSV = (
    ROOT / "data" / "reports" / "coverage_decomposition_2024_2026_staged_low_years.csv"
)
DEFAULT_DIAGNOSTIC_SUMMARY = (
    ROOT / "data" / "reports" / "coverage_decomposition_2024_2026_staged_low_years_summary.json"
)
DEFAULT_OUTPUT_COVERAGE = (
    ROOT / "data" / "reports" / "staged_coverage_effective_coverage_2024_2026.csv"
)
DEFAULT_OUTPUT_CANDIDATES = (
    ROOT / "data" / "reports" / "staged_coverage_alias_candidates_2024_2026.csv"
)
DEFAULT_OUTPUT_SUMMARY = (
    ROOT / "data" / "reports" / "staged_coverage_alias_candidates_2024_2026_summary.json"
)

DEFAULT_LEGACY_ALIAS_CSV = (
    ROOT / "data" / "mappings" / "legacy_precinct_abbreviation_to_sbe2006.csv"
)
DEFAULT_VTD00_ALIAS_CSV = ROOT / "data" / "reports" / "vtd00_legacy_precinct_alias_candidates.csv"
DEFAULT_LEFTOVERS_2008_CSV = (
    ROOT / "data" / "reports" / "precinct_key_overrides_2008_sbe2006_leftovers_classified.csv"
)
DEFAULT_SBE2006_REVIEW_FILES = (
    ROOT / "data" / "reports" / "sbe2006_urban_precinct_bridge_focus_gaps.csv",
    ROOT / "data" / "reports" / "sbe2006_urban_precinct_bridge_manual_review.csv",
)

PRIORITY_COUNTIES = {
    "WAKE",
    "IREDELL",
    "DURHAM",
    "JOHNSTON",
    "NEW HANOVER",
    "FORSYTH",
    "DAVIDSON",
    "UNION",
}

CONFIDENCE_RANK = {
    "verified": 4,
    "high": 4,
    "medium": 3,
    "low": 2,
    "review_needed": 1,
    "none": 0,
}


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().upper())


def clean_name(value: object) -> str:
    text = norm(value)
    text = text.replace("&", " AND ")
    text = re.sub(r"\bNO\b", "", text)
    text = re.sub(r"\bPCT\b", "PRECINCT", text)
    text = re.sub(r"\bELEM\b", "ELEMENTARY", text)
    text = re.sub(r"\bSCH\b", "SCHOOL", text)
    text = re.sub(r"\bMTN\b", "MOUNTAIN", text)
    text = re.sub(r"\bMT\b", "MOUNT", text)
    text = text.replace("#", " ")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "", clean_name(value))


def split_precinct_key(value: object, fallback_county: object = "") -> tuple[str, str]:
    text = norm(value)
    if " - " in text:
        county, precinct = text.split(" - ", 1)
        return norm(county), norm(precinct)
    return norm(fallback_county), text


def float_or_none(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def int_or_none(value: object) -> int | None:
    number = float_or_none(value)
    if number is None:
        return None
    return int(round(number))


def pct(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return round(numerator / denominator * 100.0, 4)


def json_list(value: object) -> list[dict[str, Any]]:
    text = str(value or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def load_manifest_files(stage_dirs: set[str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for stage_dir in sorted(stage_dirs):
        manifest_path = ROOT / stage_dir / "manifest.json"
        if not manifest_path.exists():
            out[stage_dir] = set()
            continue
        manifest = load_json(manifest_path)
        files = manifest.get("files")
        if not isinstance(files, list):
            out[stage_dir] = set()
            continue
        out[stage_dir] = {
            str(item.get("file") or "")
            for item in files
            if isinstance(item, dict) and item.get("file")
        }
    return out


def alias_values(row: dict[str, str]) -> set[str]:
    aliases: set[str] = set()
    for field in ("alias_values", "precinct_abbrv", "sbe2006_seims_code", "vtdst00"):
        value = row.get(field)
        if not value:
            continue
        for part in str(value).replace(",", ";").split(";"):
            part_norm = norm(part)
            if part_norm:
                aliases.add(part_norm)
    return aliases


def evidence_record(
    source: str,
    confidence: str,
    target_key: str,
    alias_value: str,
    note: str,
    row: dict[str, str] | None = None,
) -> dict[str, str]:
    confidence = norm(confidence).lower() or "review_needed"
    return {
        "source": source,
        "confidence": confidence,
        "target_key": target_key,
        "alias_value": alias_value,
        "note": note,
        "raw": json.dumps(row or {}, sort_keys=True),
    }


def key_name_variants(row: dict[str, str], fields: tuple[str, ...]) -> set[str]:
    variants: set[str] = set()
    for field in fields:
        value = row.get(field)
        if not value:
            continue
        if field.endswith("_key") and " - " in value:
            _, value = str(value).split(" - ", 1)
        variants.add(clean_name(value))
        variants.add(compact(value))
    return {variant for variant in variants if variant}


def has_alias_plus_name_match(precinct: str, aliases: set[str], name_variants: set[str]) -> bool:
    cleaned = clean_name(precinct)
    compacted = compact(precinct)
    for alias in aliases:
        alias_clean = clean_name(alias)
        if not alias_clean:
            continue
        if cleaned == alias_clean or compacted == compact(alias_clean):
            return True
        if cleaned.startswith(alias_clean + " "):
            remainder = cleaned[len(alias_clean) :].strip()
            if clean_name(remainder) in name_variants or compact(remainder) in name_variants:
                return True
        for name_variant in name_variants:
            if not name_variant:
                continue
            if compact(f"{alias_clean} {name_variant}") == compacted:
                return True
    return False


def load_legacy_alias_evidence(path: Path) -> list[dict[str, str]]:
    rows = read_csv(path)
    evidence_rows: list[dict[str, str]] = []
    for row in rows:
        county = norm(row.get("county"))
        if not county:
            continue
        row["county"] = county
        evidence_rows.append(row)
    return evidence_rows


def load_vtd00_evidence(path: Path) -> list[dict[str, str]]:
    rows = read_csv(path)
    evidence_rows: list[dict[str, str]] = []
    for row in rows:
        county = norm(row.get("county"))
        if not county:
            continue
        row["county"] = county
        evidence_rows.append(row)
    return evidence_rows


def load_2008_leftover_evidence(path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row in read_csv(path):
        raw_key = norm(row.get("raw_precinct_key"))
        if raw_key:
            out[raw_key] = row
    return out


def load_review_evidence(paths: list[Path]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = defaultdict(list)
    for path in paths:
        for row in read_csv(path):
            example = norm(row.get("example_source"))
            county = norm(row.get("county"))
            source = norm(row.get("source_precinct"))
            if example:
                out[example].append(row)
            if county and source:
                out[f"{county} - {source}"].append(row)
    return out


def find_legacy_evidence(
    county: str,
    precinct: str,
    legacy_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    cleaned = clean_name(precinct)
    compacted = compact(precinct)
    for row in legacy_rows:
        if norm(row.get("county")) != county:
            continue
        names = key_name_variants(row, ("source_precinct", "sbe2006_precinct", "sbe2006_key"))
        aliases = alias_values(row)
        target_key = norm(row.get("sbe2006_key"))
        if cleaned in names or compacted in names:
            matches.append(
                evidence_record(
                    "legacy_precinct_abbreviation_to_sbe2006",
                    row.get("confidence") or "medium",
                    target_key,
                    precinct,
                    "unmatched key name matches audited SBE2006/source precinct name",
                    row,
                )
            )
            continue
        if has_alias_plus_name_match(precinct, aliases, names):
            matches.append(
                evidence_record(
                    "legacy_precinct_abbreviation_to_sbe2006",
                    row.get("confidence") or "medium",
                    target_key,
                    precinct,
                    "unmatched key combines audited code/alias with SBE2006/source precinct name",
                    row,
                )
            )
    return matches


def find_vtd00_evidence(
    county: str,
    precinct: str,
    vtd_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    cleaned = clean_name(precinct)
    compacted = compact(precinct)
    for row in vtd_rows:
        if norm(row.get("county")) != county:
            continue
        names = key_name_variants(
            row,
            ("name00", "sbe2006_key_by_code", "sbe2006_name_by_code", "sbe2006_name_match_keys"),
        )
        aliases = alias_values(row)
        target = norm(row.get("sbe2006_key_by_code") or row.get("sbe2006_name_match_keys"))
        if cleaned in names or compacted in names:
            matches.append(
                evidence_record(
                    "vtd00_legacy_precinct_alias_candidates",
                    "medium",
                    target,
                    precinct,
                    "unmatched key name matches VTD00/SBE2006 candidate evidence",
                    row,
                )
            )
            continue
        if has_alias_plus_name_match(precinct, aliases, names):
            matches.append(
                evidence_record(
                    "vtd00_legacy_precinct_alias_candidates",
                    "medium",
                    target,
                    precinct,
                    "unmatched key combines VTD00 code with SBE2006/name evidence",
                    row,
                )
            )
    return matches


def find_2008_leftover_evidence(
    source_key: str,
    leftovers: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    row = leftovers.get(norm(source_key))
    if not row:
        return []
    classification = norm(row.get("classification")).lower()
    confidence = row.get("confidence") or "medium"
    if classification in {"geographic_sbe2006", "resolvable_sbe2006_alias"}:
        target = norm(row.get("era_precinct_key") or row.get("canonical_precinct_key"))
        note = "2008 leftover classifier found source-backed SBE2006 geography/alias"
    else:
        target = norm(row.get("era_precinct_key") or row.get("canonical_precinct_key"))
        note = "2008 leftover classifier did not mark this as a resolvable geography"
        confidence = "review_needed"
    return [
        evidence_record(
            "precinct_key_overrides_2008_sbe2006_leftovers_classified",
            confidence,
            target,
            source_key,
            note,
            row,
        )
    ]


def find_review_evidence(
    source_key: str,
    review_rows: dict[str, list[dict[str, str]]],
) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for row in review_rows.get(norm(source_key), []):
        status = norm(row.get("status")).lower()
        confidence = "review_needed" if status in {"unmatched", "alias_key_mismatch"} else "low"
        matches.append(
            evidence_record(
                "sbe2006_urban_precinct_bridge_review",
                confidence,
                norm(row.get("targets")),
                source_key,
                row.get("reason") or "existing SBE2006 bridge review row references this key",
                row,
            )
        )
    return matches


def best_evidence(evidence: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    if not evidence:
        return "review_needed", []
    best_rank = max(CONFIDENCE_RANK.get(item.get("confidence", "none"), 0) for item in evidence)
    best = [
        item
        for item in evidence
        if CONFIDENCE_RANK.get(item.get("confidence", "none"), 0) == best_rank
    ]
    confidence = best[0].get("confidence") or "review_needed"
    return confidence, best


def classify_pattern(precinct: str) -> str:
    text = norm(precinct)
    tokens = text.split()
    if len(tokens) >= 2 and tokens[0] == tokens[1]:
        return "duplicate_code"
    if len(tokens) >= 2 and compact(tokens[0]) == compact(tokens[1]):
        return "duplicate_code"
    if text.startswith("PRECINCT "):
        return "precinct_prefix"
    if re.match(r"^[A-Z]{1,4}\d+[A-Z]?\b", text) and len(tokens) > 1:
        return "alpha_numeric_code_plus_name"
    if re.match(r"^\d+[A-Z]?\b", text) and len(tokens) > 1:
        return "numeric_code_plus_name"
    if re.search(r"\b\d{2}-\d{2}\b", text):
        return "hyphenated_numeric_code"
    if len(tokens) == 1:
        return "single_token_or_code"
    return "name_or_mixed"


def corrected_coverage(row: dict[str, str]) -> dict[str, Any]:
    selected_matched = int_or_none(row.get("source_keys_matched_to_selected_district_weights"))
    selected_unmatched = int_or_none(row.get("source_keys_unmatched_to_selected_district_weights"))
    selected_total = None
    if selected_matched is not None and selected_unmatched is not None:
        selected_total = selected_matched + selected_unmatched

    vintage_matched = int_or_none(row.get("matched_source_keys_to_vintage_bridge"))
    processed_total = int_or_none(row.get("processed_geo_key_count_after_alias_and_nongeo_allocation"))
    staged_matched = int_or_none(row.get("staged_matched_precinct_keys"))
    staged_total = int_or_none(row.get("staged_total_precinct_keys"))

    selected_pct = float_or_none(row.get("effective_selected_weight_key_coverage_pct"))
    if selected_pct is None:
        selected_pct = pct(selected_matched, selected_total)

    if selected_pct is not None and selected_matched is not None:
        corrected_matched = selected_matched
        corrected_total = selected_total or staged_total
        corrected_pct = selected_pct
        basis = "selected_district_weight_keys"
    elif vintage_matched is not None:
        corrected_matched = vintage_matched
        corrected_total = processed_total or staged_total
        corrected_pct = pct(corrected_matched, corrected_total)
        basis = "exact_vintage_bridge_keys"
    else:
        corrected_matched = staged_matched
        corrected_total = staged_total
        corrected_pct = pct(corrected_matched, corrected_total)
        basis = "staged_metadata_keys"

    staged_pct = float_or_none(row.get("staged_match_coverage_pct"))
    metadata_delta = None
    if staged_pct is not None and corrected_pct is not None:
        metadata_delta = round(corrected_pct - staged_pct, 4)

    return {
        "corrected_matched_keys": corrected_matched,
        "corrected_total_keys": corrected_total,
        "corrected_effective_key_coverage_pct": corrected_pct,
        "corrected_coverage_basis": basis,
        "staged_metadata_delta_pct": metadata_delta,
        "metadata_bug_flag": bool(metadata_delta is not None and abs(metadata_delta) >= 0.01),
    }


def build_coverage_rows(
    diagnostic_rows: list[dict[str, str]],
    manifest_files_by_stage: dict[str, set[str]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in diagnostic_rows:
        coverage = corrected_coverage(row)
        stage_dir = row.get("stage_dir") or ""
        representative_file = row.get("representative_file") or ""
        out.append(
            {
                "stage_key": row.get("stage_key"),
                "stage_dir": stage_dir,
                "year": row.get("year"),
                "scope": row.get("scope"),
                "representative_contest": row.get("representative_contest"),
                "representative_file": representative_file,
                "manifest_contains_representative_file": representative_file
                in manifest_files_by_stage.get(stage_dir, set()),
                "district_weight_plan": row.get("district_weight_plan"),
                "district_weight_scope": row.get("district_weight_scope"),
                "staged_match_coverage_pct": row.get("staged_match_coverage_pct"),
                "staged_matched_precinct_keys": row.get("staged_matched_precinct_keys"),
                "staged_total_precinct_keys": row.get("staged_total_precinct_keys"),
                "staged_metadata_coverage_source": row.get("staged_metadata_coverage_source"),
                "corrected_matched_keys": coverage["corrected_matched_keys"],
                "corrected_total_keys": coverage["corrected_total_keys"],
                "corrected_effective_key_coverage_pct": coverage[
                    "corrected_effective_key_coverage_pct"
                ],
                "corrected_coverage_basis": coverage["corrected_coverage_basis"],
                "staged_metadata_delta_pct": coverage["staged_metadata_delta_pct"],
                "metadata_bug_flag": coverage["metadata_bug_flag"],
                "root_cause": row.get("root_cause"),
            }
        )
    return out


def build_candidate_rows(
    diagnostic_rows: list[dict[str, str]],
    legacy_rows: list[dict[str, str]],
    vtd_rows: list[dict[str, str]],
    leftovers_2008: dict[str, dict[str, str]],
    review_rows: dict[str, list[dict[str, str]]],
    per_row_limit: int,
) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = {}

    for row in diagnostic_rows:
        raw_selected = json_list(row.get("top_unmatched_selected_district_weight_keys_json"))
        raw_vintage = json_list(row.get("top_unmatched_vintage_keys_json"))
        has_selected_weight_scope = bool(
            norm(row.get("district_weight_scope"))
            and str(row.get("source_keys_matched_to_selected_district_weights") or "").strip()
        )
        if has_selected_weight_scope and raw_selected:
            source_kind = "selected_district_weight"
            items = raw_selected
        else:
            source_kind = "vintage_bridge"
            items = raw_vintage or raw_selected
        if per_row_limit > 0:
            items = items[:per_row_limit]

        for rank, item in enumerate(items, start=1):
            source_key = norm(item.get("key"))
            if not source_key:
                continue
            county, precinct = split_precinct_key(source_key, item.get("county") or row.get("county"))
            key = (source_kind, source_key)
            bucket = buckets.setdefault(
                key,
                {
                    "source_kind": source_kind,
                    "source_key": source_key,
                    "county": county,
                    "source_precinct": precinct,
                    "pattern": classify_pattern(precinct),
                    "priority_county": county in PRIORITY_COUNTIES,
                    "stage_keys": set(),
                    "years": set(),
                    "scopes": set(),
                    "district_weight_scopes": set(),
                    "representative_contests": set(),
                    "root_causes": set(),
                    "row_occurrence_count": 0,
                    "best_rank": rank,
                    "total_reported_votes": 0,
                    "max_votes": 0,
                    "max_vote_share_pct": 0.0,
                    "example_rows": [],
                },
            )
            votes = int_or_none(item.get("votes")) or 0
            share = float_or_none(item.get("vote_share_pct")) or 0.0
            bucket["stage_keys"].add(row.get("stage_key") or "")
            bucket["years"].add(str(row.get("year") or ""))
            bucket["scopes"].add(row.get("scope") or "")
            if row.get("district_weight_scope"):
                bucket["district_weight_scopes"].add(row.get("district_weight_scope") or "")
            bucket["representative_contests"].add(row.get("representative_contest") or "")
            bucket["root_causes"].add(row.get("root_cause") or "")
            bucket["row_occurrence_count"] += 1
            bucket["best_rank"] = min(bucket["best_rank"], rank)
            bucket["total_reported_votes"] += votes
            bucket["max_votes"] = max(bucket["max_votes"], votes)
            bucket["max_vote_share_pct"] = max(bucket["max_vote_share_pct"], share)
            if len(bucket["example_rows"]) < 4:
                bucket["example_rows"].append(
                    f"{row.get('stage_key')}:{row.get('year')}:{row.get('scope')}:{rank}"
                )

    out: list[dict[str, Any]] = []
    for bucket in buckets.values():
        county = bucket["county"]
        precinct = bucket["source_precinct"]
        source_key = bucket["source_key"]

        evidence: list[dict[str, str]] = []
        evidence.extend(find_2008_leftover_evidence(source_key, leftovers_2008))
        evidence.extend(find_legacy_evidence(county, precinct, legacy_rows))
        evidence.extend(find_vtd00_evidence(county, precinct, vtd_rows))
        evidence.extend(find_review_evidence(source_key, review_rows))

        confidence, best = best_evidence(evidence)
        target_keys = sorted({item.get("target_key", "") for item in best if item.get("target_key")})
        evidence_sources = sorted({item.get("source", "") for item in best if item.get("source")})
        evidence_notes = sorted({item.get("note", "") for item in best if item.get("note")})
        review_status = (
            "source_backed_candidate"
            if confidence in {"verified", "high", "medium"}
            else "review_needed"
        )

        out.append(
            {
                "source_kind": bucket["source_kind"],
                "source_key": source_key,
                "county": county,
                "source_precinct": precinct,
                "pattern": bucket["pattern"],
                "priority_county": bucket["priority_county"],
                "row_occurrence_count": bucket["row_occurrence_count"],
                "best_rank": bucket["best_rank"],
                "years": ";".join(sorted(bucket["years"])),
                "scopes": ";".join(sorted(bucket["scopes"])),
                "stage_keys": ";".join(sorted(bucket["stage_keys"])),
                "district_weight_scopes": ";".join(sorted(bucket["district_weight_scopes"])),
                "representative_contests": ";".join(sorted(bucket["representative_contests"])),
                "root_causes": ";".join(sorted(bucket["root_causes"])),
                "total_reported_votes": bucket["total_reported_votes"],
                "max_votes": bucket["max_votes"],
                "max_vote_share_pct": round(bucket["max_vote_share_pct"], 4),
                "confidence": confidence,
                "review_status": review_status,
                "candidate_target_keys": ";".join(target_keys),
                "evidence_sources": ";".join(evidence_sources),
                "evidence_notes": " | ".join(evidence_notes),
                "all_evidence_count": len(evidence),
                "example_rows": ";".join(bucket["example_rows"]),
            }
        )

    return sorted(
        out,
        key=lambda row: (
            row["review_status"] != "source_backed_candidate",
            not row["priority_county"],
            row["source_kind"] != "selected_district_weight",
            -int(row["row_occurrence_count"]),
            -int(row["max_votes"]),
            row["county"],
            row["source_key"],
        ),
    )


def summarize(
    diagnostic_summary: dict[str, Any],
    diagnostic_rows: list[dict[str, str]],
    coverage_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    confidence_counts = Counter(row["confidence"] for row in candidate_rows)
    review_status_counts = Counter(row["review_status"] for row in candidate_rows)
    pattern_counts = Counter(row["pattern"] for row in candidate_rows)
    county_counts = Counter(row["county"] for row in candidate_rows)
    priority_county_counts = Counter(
        row["county"] for row in candidate_rows if row["priority_county"]
    )
    metadata_bug_rows = [
        row
        for row in coverage_rows
        if str(row.get("metadata_bug_flag")).lower() in {"true", "1"}
    ]
    biggest_metadata_deltas = sorted(
        metadata_bug_rows,
        key=lambda row: abs(float(row.get("staged_metadata_delta_pct") or 0.0)),
        reverse=True,
    )[:10]

    stage_summary = diagnostic_summary.get("stage_summary")
    if not isinstance(stage_summary, dict):
        stage_summary = {}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": (
            "Report-only staged coverage metadata correction and alias candidate "
            "preparation. No aggregation or mapping outputs are modified."
        ),
        "inputs": {
            "diagnostic_csv": str(args.diagnostic_csv),
            "diagnostic_summary": str(args.diagnostic_summary),
            "legacy_alias_csv": str(args.legacy_alias_csv),
            "vtd00_alias_csv": str(args.vtd00_alias_csv),
            "leftovers_2008_csv": str(args.leftovers_2008_csv),
            "sbe2006_review_csvs": [str(path) for path in args.sbe2006_review_csv],
        },
        "outputs": {
            "coverage_csv": str(args.output_coverage),
            "alias_candidates_csv": str(args.output_candidates),
            "summary_json": str(args.output_summary),
        },
        "diagnostic_stage_keys": sorted(stage_summary.keys()),
        "diagnostic_rows": len(diagnostic_rows),
        "coverage_rows": len(coverage_rows),
        "coverage_metadata_bug_rows": len(metadata_bug_rows),
        "coverage_metadata_bug_top_deltas": [
            {
                "stage_key": row.get("stage_key"),
                "year": row.get("year"),
                "scope": row.get("scope"),
                "staged_match_coverage_pct": row.get("staged_match_coverage_pct"),
                "corrected_effective_key_coverage_pct": row.get(
                    "corrected_effective_key_coverage_pct"
                ),
                "delta_pct": row.get("staged_metadata_delta_pct"),
                "basis": row.get("corrected_coverage_basis"),
            }
            for row in biggest_metadata_deltas
        ],
        "alias_candidate_rows": len(candidate_rows),
        "alias_candidate_confidence_counts": dict(sorted(confidence_counts.items())),
        "alias_candidate_review_status_counts": dict(sorted(review_status_counts.items())),
        "top_patterns": [
            {"pattern": pattern, "candidate_rows": count}
            for pattern, count in pattern_counts.most_common(12)
        ],
        "top_counties": [
            {"county": county, "candidate_rows": count}
            for county, count in county_counts.most_common(12)
        ],
        "priority_counties": sorted(PRIORITY_COUNTIES),
        "priority_county_candidate_counts": dict(sorted(priority_county_counts.items())),
        "top_source_backed_candidates": [
            {
                "source_key": row["source_key"],
                "county": row["county"],
                "pattern": row["pattern"],
                "years": row["years"],
                "row_occurrence_count": row["row_occurrence_count"],
                "max_votes": row["max_votes"],
                "confidence": row["confidence"],
                "candidate_target_keys": row["candidate_target_keys"],
                "evidence_sources": row["evidence_sources"],
            }
            for row in candidate_rows
            if row["review_status"] == "source_backed_candidate"
        ][:20],
        "notes": [
            "Rows marked source_backed_candidate are evidence for a future alias batch, not applied aliases.",
            "Rows marked review_needed should be checked against source files or GIS attributes before any mapping change.",
            "Coverage corrections are recomputed from diagnostic row fields and do not rerun aggregation.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare report-only corrected staged coverage diagnostics and "
            "source-backed alias candidate buckets for 2024/2026 staged rebuilds."
        )
    )
    parser.add_argument("--diagnostic-csv", type=Path, default=DEFAULT_DIAGNOSTIC_CSV)
    parser.add_argument("--diagnostic-summary", type=Path, default=DEFAULT_DIAGNOSTIC_SUMMARY)
    parser.add_argument("--legacy-alias-csv", type=Path, default=DEFAULT_LEGACY_ALIAS_CSV)
    parser.add_argument("--vtd00-alias-csv", type=Path, default=DEFAULT_VTD00_ALIAS_CSV)
    parser.add_argument("--leftovers-2008-csv", type=Path, default=DEFAULT_LEFTOVERS_2008_CSV)
    parser.add_argument(
        "--sbe2006-review-csv",
        type=Path,
        action="append",
        default=list(DEFAULT_SBE2006_REVIEW_FILES),
        help=(
            "Existing lightweight SBE2006 review CSV to use as evidence. "
            "May be supplied multiple times."
        ),
    )
    parser.add_argument("--output-coverage", type=Path, default=DEFAULT_OUTPUT_COVERAGE)
    parser.add_argument("--output-candidates", type=Path, default=DEFAULT_OUTPUT_CANDIDATES)
    parser.add_argument("--output-summary", type=Path, default=DEFAULT_OUTPUT_SUMMARY)
    parser.add_argument(
        "--per-row-limit",
        type=int,
        default=12,
        help="Maximum top unmatched keys to extract from each diagnostic row; use 0 for all.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    diagnostic_rows = read_csv(args.diagnostic_csv)
    if not diagnostic_rows:
        raise SystemExit(f"No diagnostic rows found in {args.diagnostic_csv}")

    diagnostic_summary = load_json(args.diagnostic_summary)
    stage_dirs = {row.get("stage_dir") or "" for row in diagnostic_rows if row.get("stage_dir")}
    manifest_files_by_stage = load_manifest_files(stage_dirs)

    legacy_rows = load_legacy_alias_evidence(args.legacy_alias_csv)
    vtd_rows = load_vtd00_evidence(args.vtd00_alias_csv)
    leftovers_2008 = load_2008_leftover_evidence(args.leftovers_2008_csv)
    review_rows = load_review_evidence(args.sbe2006_review_csv)

    coverage_rows = build_coverage_rows(diagnostic_rows, manifest_files_by_stage)
    candidate_rows = build_candidate_rows(
        diagnostic_rows=diagnostic_rows,
        legacy_rows=legacy_rows,
        vtd_rows=vtd_rows,
        leftovers_2008=leftovers_2008,
        review_rows=review_rows,
        per_row_limit=args.per_row_limit,
    )
    summary = summarize(diagnostic_summary, diagnostic_rows, coverage_rows, candidate_rows, args)

    write_csv(
        args.output_coverage,
        coverage_rows,
        [
            "stage_key",
            "stage_dir",
            "year",
            "scope",
            "representative_contest",
            "representative_file",
            "manifest_contains_representative_file",
            "district_weight_plan",
            "district_weight_scope",
            "staged_match_coverage_pct",
            "staged_matched_precinct_keys",
            "staged_total_precinct_keys",
            "staged_metadata_coverage_source",
            "corrected_matched_keys",
            "corrected_total_keys",
            "corrected_effective_key_coverage_pct",
            "corrected_coverage_basis",
            "staged_metadata_delta_pct",
            "metadata_bug_flag",
            "root_cause",
        ],
    )
    write_csv(
        args.output_candidates,
        candidate_rows,
        [
            "source_kind",
            "source_key",
            "county",
            "source_precinct",
            "pattern",
            "priority_county",
            "row_occurrence_count",
            "best_rank",
            "years",
            "scopes",
            "stage_keys",
            "district_weight_scopes",
            "representative_contests",
            "root_causes",
            "total_reported_votes",
            "max_votes",
            "max_vote_share_pct",
            "confidence",
            "review_status",
            "candidate_target_keys",
            "evidence_sources",
            "evidence_notes",
            "all_evidence_count",
            "example_rows",
        ],
    )
    args.output_summary.parent.mkdir(parents=True, exist_ok=True)
    with args.output_summary.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"Wrote coverage report: {args.output_coverage}")
    print(f"Wrote alias candidates: {args.output_candidates}")
    print(f"Wrote summary: {args.output_summary}")
    print(
        "Alias candidates: "
        f"{len(candidate_rows)} rows; "
        f"{summary['alias_candidate_review_status_counts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
