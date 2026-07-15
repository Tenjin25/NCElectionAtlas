"""Load audited legacy precinct abbreviation aliases."""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAPPING_CSV = ROOT / "data" / "mappings" / "legacy_precinct_abbreviation_to_sbe2006.csv"


def normalize_name(value: object) -> str:
    text = str(value or "").strip().upper()
    text = text.replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9#]+", " ", text)
    text = re.sub(r"\bMTN\b", "MOUNTAIN", text)
    text = re.sub(r"\bMT\b", "MOUNT", text)
    text = text.replace("#", " ")
    return re.sub(r"\s+", " ", text).strip()


def name_keys(value: object) -> set[str]:
    text = normalize_name(value)
    if not text:
        return set()
    keys = {text, re.sub(r"[^A-Z0-9]+", "", text)}
    if text == "FLINT GROVES":
        keys.add("FLINT GROVE")
        keys.add("FLINTGROVE")
    return {key for key in keys if key}


def aliases_for_code(county: str, code: object) -> set[str]:
    county = str(county or "").strip().upper()
    raw_aliases = {
        part.strip().upper()
        for part in str(code or "").replace(",", ";").split(";")
        if part.strip()
    }
    aliases = set(raw_aliases)
    if county == "GASTON":
        for alias in list(raw_aliases):
            match = re.fullmatch(r"0*(\d{1,3})", alias)
            if not match:
                continue
            number = int(match.group(1))
            aliases.add(str(number))
            aliases.add(f"{number:02d}")
            aliases.add(f"{number}-1")
            aliases.add(f"{number:02d}-1")
    return {alias for alias in aliases if alias}


@lru_cache(maxsize=4)
def load_aliases_by_county_name(mapping_csv: str | Path = DEFAULT_MAPPING_CSV) -> dict[tuple[str, str], set[str]]:
    path = Path(mapping_csv)
    if not path.exists():
        return {}

    out: dict[tuple[str, str], set[str]] = {}
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            confidence = str(row.get("confidence") or "").strip().lower()
            if confidence not in {"high", "verified"}:
                continue
            county = str(row.get("county") or "").strip().upper()
            if not county:
                continue
            aliases = aliases_for_code(county, row.get("alias_values") or row.get("precinct_abbrv"))
            source_precinct = row.get("source_precinct")
            if source_precinct:
                aliases.update(name_keys(source_precinct))
            if not aliases:
                continue
            for field in ("sbe2006_precinct", "source_precinct", "sbe2006_key"):
                value = row.get(field)
                if not value:
                    continue
                if field == "sbe2006_key" and " - " in value:
                    value = value.split(" - ", 1)[1]
                for key in name_keys(value):
                    out.setdefault((county, key), set()).update(aliases)
    return out


def legacy_abbreviation_aliases_for_name(county: object, name: object, mapping_csv: str | Path = DEFAULT_MAPPING_CSV) -> set[str]:
    county_key = str(county or "").strip().upper()
    aliases_by_name = load_aliases_by_county_name(mapping_csv)
    out: set[str] = set()
    for key in name_keys(name):
        out.update(aliases_by_name.get((county_key, key), set()))
    return out
