"""Build a compact frontend bridge from SBE 2006 names to OneMap precinct IDs.

The source summary is generated from the NHGIS-backed SBE 2006 bridge and maps
each current OneMap precinct to its dominant SBE 2006 precinct. The atlas needs
the inverse lookup while rendering early-era precinct results on current
polygons: county + SBE 2006 result label -> one or more current precinct IDs.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from legacy_precinct_aliases import DEFAULT_MAPPING_CSV as DEFAULT_LEGACY_ABBREVIATION_ALIASES
from legacy_precinct_aliases import legacy_abbreviation_aliases_for_name


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "reports" / "centroid_sbe2006_nhgis_bridge_summary.csv"
DEFAULT_OUTPUT = ROOT / "data" / "mappings" / "sbe2006_to_onemap_precinct_bridge.json"
DEFAULT_SBE_BLOCK_MAP = ROOT / "data" / "crosswalks" / "block20_to_sbe_2006_via_block00_nhgis_filled.csv"
DEFAULT_ONEMAP_BLOCK_MAP = ROOT / "data" / "crosswalks" / "block20_to_onemap_2025_12.csv"
DEFAULT_VAP_CSV = ROOT / "data" / "census" / "block_vap_2020_nc.csv"
DEFAULT_WEIGHTS_OUTPUT = ROOT / "data" / "mappings" / "sbe2006_to_onemap_precinct_weights.json"

COMMON_PRECINCT_WORDS = ("PRECINCT", "PCT", "WARD", "DISTRICT", "TOWNSHIP", "BOX", "VOTING", "LOCATION")


def relative_or_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def normalize_token(value: object) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"[^A-Z0-9 ._-]+", " ", text)
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_alias(value: object) -> str:
    text = normalize_token(value)
    for word in COMMON_PRECINCT_WORDS:
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text)
    text = text.replace("-", " ").replace(".", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "", normalize_token(value))


def source_code_aliases(value: object) -> set[str]:
    """Derive county-local code aliases from SBE2006 names like CAPE FEAR 3 -> CF03."""
    text = normalize_alias(value)
    parts = [part for part in text.split(" ") if part]
    if len(parts) < 2:
        return set()

    words: list[str] = []
    numbers: list[tuple[int, str]] = []
    for part in parts:
        number_match = re.fullmatch(r"0*(\d+)([A-Z]?)", part)
        alpha_number_match = re.fullmatch(r"([A-Z]+)0*(\d+)([A-Z]?)", part)
        if number_match:
            numbers.append((int(number_match.group(1)), number_match.group(2)))
        elif alpha_number_match:
            words.append(alpha_number_match.group(1))
            numbers.append((int(alpha_number_match.group(2)), alpha_number_match.group(3)))
        elif re.fullmatch(r"[A-Z]+", part):
            words.append(part)

    initials = "".join(word[0] for word in words if word)
    if not initials or not numbers:
        return set()

    aliases: set[str] = set()
    for number, suffix in numbers:
        aliases.add(f"{initials}{number}{suffix}")
        aliases.add(f"{initials}{number:02d}{suffix}")
    return aliases


def split_precinct_key(value: object) -> tuple[str, str]:
    text = normalize_token(value)
    if " - " not in text:
        return "", text
    county, precinct = text.split(" - ", 1)
    return normalize_token(county), normalize_token(precinct)


def aliases_for(county: str, precinct: str) -> set[str]:
    aliases: set[str] = set()
    full = f"{county} - {precinct}" if county and precinct else precinct
    for raw in (full, precinct):
        token = normalize_token(raw)
        alias = normalize_alias(raw)
        packed = compact(raw)
        if token:
            aliases.add(token)
        if alias:
            aliases.add(alias)
        if packed:
            aliases.add(packed)
    for alias in source_code_aliases(precinct):
        aliases.add(alias)
        aliases.add(compact(alias))
    county_token = normalize_token(county)
    for alias in legacy_abbreviation_aliases_for_name(county_token, precinct):
        aliases.add(alias)
        aliases.add(f"{county_token} - {alias}")
        aliases.add(compact(alias))
    return {alias for alias in aliases if alias}


def build_bridge(summary_path: Path) -> dict[str, object]:
    by_county: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    modern_precincts: set[str] = set()
    sbe_precincts: set[str] = set()
    rows_used = 0

    with summary_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            modern_county, modern_code = split_precinct_key(row.get("modern_precinct"))
            sbe_county, sbe_precinct = split_precinct_key(row.get("sbe2006_precinct"))
            county = modern_county or sbe_county
            if not county or not modern_code or not sbe_precinct:
                continue
            if sbe_county and sbe_county != county:
                continue

            rows_used += 1
            modern_precincts.add(f"{county} - {modern_code}")
            sbe_precincts.add(f"{county} - {sbe_precinct}")
            for alias in aliases_for(county, sbe_precinct):
                by_county[county][alias].add(modern_code)

    counties = {
        county: {
            alias: sorted(codes)
            for alias, codes in sorted(alias_map.items())
            if codes
        }
        for county, alias_map in sorted(by_county.items())
        if alias_map
    }
    return {
        "version": 1,
        "generated_from": [str(summary_path.relative_to(ROOT)).replace("\\", "/")],
        "description": "County-scoped aliases from SBE 2006 precinct labels to current OneMap precinct IDs.",
        "rows": rows_used,
        "sbe2006_precincts": len(sbe_precincts),
        "onemap_precincts": len(modern_precincts),
        "counties": counties,
    }


def load_vap_by_block(vap_path: Path) -> dict[str, float]:
    vap_by_block: dict[str, float] = {}
    with vap_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            geoid = str(row.get("block_geoid20") or row.get("GEOID20") or "").strip().zfill(15)
            if not geoid:
                continue
            try:
                vap = float(row.get("vap_count") or row.get("vap20") or 0)
            except (TypeError, ValueError):
                vap = 0.0
            vap_by_block[geoid] = vap if vap > 0 else 0.0
    return vap_by_block


def load_block_precinct_map(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            geoid = str(row.get("block_geoid20") or row.get("GEOID20") or "").strip().zfill(15)
            precinct = normalize_token(row.get("precinct_id") or row.get("onemap_precinct_id") or row.get("sbe_precinct_id") or "")
            if geoid and precinct:
                out[geoid] = precinct
    return out


def build_weighted_bridge(sbe_block_map: Path, onemap_block_map: Path, vap_path: Path) -> dict[str, object]:
    sbe_by_block = load_block_precinct_map(sbe_block_map)
    onemap_by_block = load_block_precinct_map(onemap_block_map)
    vap_by_block = load_vap_by_block(vap_path)

    pair_vap: dict[tuple[str, str], float] = defaultdict(float)
    pair_blocks: dict[tuple[str, str], int] = defaultdict(int)
    joined_blocks = 0

    for block_geoid, sbe_key in sbe_by_block.items():
        onemap_key = onemap_by_block.get(block_geoid)
        if not onemap_key:
            continue
        sbe_county, _ = split_precinct_key(sbe_key)
        onemap_county, _ = split_precinct_key(onemap_key)
        if not sbe_county or not onemap_county or sbe_county != onemap_county:
            continue
        joined_blocks += 1
        key = (sbe_key, onemap_key)
        pair_vap[key] += vap_by_block.get(block_geoid, 0.0)
        pair_blocks[key] += 1

    source_vap: dict[str, float] = defaultdict(float)
    source_blocks: dict[str, int] = defaultdict(int)
    for (sbe_key, _), vap in pair_vap.items():
        source_vap[sbe_key] += vap
        source_blocks[sbe_key] += pair_blocks[(sbe_key, _)]

    by_county: dict[str, dict[str, list[dict[str, float | str]]]] = defaultdict(lambda: defaultdict(list))
    source_keys: set[str] = set()
    target_keys: set[str] = set()
    zero_vap_sources: set[str] = set()

    grouped_by_source: dict[str, list[tuple[str, float, int]]] = defaultdict(list)
    for (sbe_key, onemap_key), vap in pair_vap.items():
        grouped_by_source[sbe_key].append((onemap_key, vap, pair_blocks[(sbe_key, onemap_key)]))

    for sbe_key, targets in grouped_by_source.items():
        sbe_county, sbe_precinct = split_precinct_key(sbe_key)
        if not sbe_county or not sbe_precinct:
            continue
        vap_total = source_vap.get(sbe_key, 0.0)
        block_total = source_blocks.get(sbe_key, 0)
        use_block_fallback = vap_total <= 0
        if use_block_fallback:
            zero_vap_sources.add(sbe_key)
        denom = float(block_total if use_block_fallback else vap_total)
        if denom <= 0:
            continue

        weighted_targets: list[dict[str, float | str]] = []
        for onemap_key, vap, blocks in targets:
            onemap_county, onemap_code = split_precinct_key(onemap_key)
            if onemap_county != sbe_county or not onemap_code:
                continue
            numer = float(blocks if use_block_fallback else vap)
            if numer <= 0:
                continue
            weight = numer / denom
            weighted_targets.append({
                "code": onemap_code,
                "weight": round(weight, 10),
            })
            target_keys.add(f"{sbe_county} - {onemap_code}")

        if not weighted_targets:
            continue
        total_weight = sum(float(item["weight"]) for item in weighted_targets)
        if total_weight > 0 and abs(total_weight - 1.0) > 1e-9:
            # Preserve each source precinct total after decimal trimming.
            last = weighted_targets[-1]
            last["weight"] = round(float(last["weight"]) + (1.0 - total_weight), 10)
        weighted_targets.sort(key=lambda item: (-float(item["weight"]), str(item["code"])))

        source_keys.add(sbe_key)
        for alias in aliases_for(sbe_county, sbe_precinct):
            by_county[sbe_county][alias] = weighted_targets

    counties = {
        county: {
            alias: entries
            for alias, entries in sorted(alias_map.items())
            if entries
        }
        for county, alias_map in sorted(by_county.items())
        if alias_map
    }
    return {
        "version": 1,
        "generated_from": [
            relative_or_path(sbe_block_map),
            relative_or_path(onemap_block_map),
            relative_or_path(vap_path),
        ]
        + ([relative_or_path(DEFAULT_LEGACY_ABBREVIATION_ALIASES)] if DEFAULT_LEGACY_ABBREVIATION_ALIASES.exists() else []),
        "description": "VAP-weighted county-scoped aliases from SBE 2006 precinct labels to current OneMap precinct IDs. Sources with zero joined VAP use block-count weights.",
        "joined_blocks": joined_blocks,
        "sbe2006_precincts": len(source_keys),
        "onemap_precincts": len(target_keys),
        "zero_vap_fallback_precincts": len(zero_vap_sources),
        "counties": counties,
    }


def build_bridge_from_weights(weights_payload: dict[str, object]) -> dict[str, object]:
    counties_in = weights_payload.get("counties", {})
    counties: dict[str, dict[str, list[str]]] = {}
    alias_rows = 0
    target_keys: set[str] = set()

    if isinstance(counties_in, dict):
        for county, alias_map in sorted(counties_in.items()):
            if not isinstance(alias_map, dict):
                continue
            out_aliases: dict[str, list[str]] = {}
            for alias, entries in sorted(alias_map.items()):
                if not isinstance(entries, list):
                    continue
                codes = sorted({str(item.get("code", "")).strip() for item in entries if isinstance(item, dict) and item.get("code")})
                if not codes:
                    continue
                out_aliases[str(alias)] = codes
                alias_rows += 1
                target_keys.update(f"{county} - {code}" for code in codes)
            if out_aliases:
                counties[str(county)] = out_aliases

    return {
        "version": 1,
        "generated_from": weights_payload.get("generated_from", []),
        "description": "County-scoped aliases from SBE 2006 precinct labels to current OneMap precinct IDs, derived from the weighted block bridge.",
        "rows": alias_rows,
        "sbe2006_precincts": weights_payload.get("sbe2006_precincts", 0),
        "onemap_precincts": len(target_keys),
        "counties": counties,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary-csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sbe-block-map", type=Path, default=DEFAULT_SBE_BLOCK_MAP)
    parser.add_argument("--onemap-block-map", type=Path, default=DEFAULT_ONEMAP_BLOCK_MAP)
    parser.add_argument("--vap-csv", type=Path, default=DEFAULT_VAP_CSV)
    parser.add_argument("--out-weights-json", type=Path, default=DEFAULT_WEIGHTS_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    weights_payload = build_weighted_bridge(args.sbe_block_map, args.onemap_block_map, args.vap_csv)
    payload = build_bridge_from_weights(weights_payload)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    args.out_weights_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_weights_json.write_text(json.dumps(weights_payload, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    print(
        f"Wrote {args.out_json} "
        f"({payload['rows']:,} rows, {payload['sbe2006_precincts']:,} SBE precincts, "
        f"{payload['onemap_precincts']:,} OneMap precincts)"
    )
    print(
        f"Wrote {args.out_weights_json} "
        f"({weights_payload['joined_blocks']:,} blocks, {weights_payload['sbe2006_precincts']:,} SBE precincts, "
        f"{weights_payload['onemap_precincts']:,} OneMap precincts, "
        f"{weights_payload['zero_vap_fallback_precincts']:,} block-fallback precincts)"
    )


if __name__ == "__main__":
    main()
