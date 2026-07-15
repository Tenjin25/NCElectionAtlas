"""
Build 2024 district contest slices with true DEM/REP/OTHER allocation.

Pipeline:
1) Start from precinct-sort style rows (county, precinct, office, party, candidate, votes).
2) Reallocate non-geographic precinct rows (ABSENTEE/ONE-STOP/EARLY/etc.) to geographic
   precincts by candidate-performance shares within county.
3) Aggregate to precinct-level DEM/REP/OTHER.
4) VAP-shatter precinct totals to block-level, then aggregate to district scopes.
5) Emit data/district_contests/{scope}_{contest_type}_{year}.json + manifest.json.
"""
from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal
from pathlib import Path

import pandas as pd
import geopandas as gpd

from legacy_precinct_aliases import legacy_abbreviation_aliases_for_name
from shatter_precinct_votes_vap import aggregate_to_districts, load_crosswalk, load_vap, shatter_votes


# year_max (inclusive) -> preferred block→precinct match maps (first existing path wins).
# District aggregation matches OE keys + shatters through this map (vintage → blocks → district).
# OneMap 2025 is only the default for recent years; do not use it for pre-2022 matching.
VINTAGE_MATCH_CROSSWALKS: list[tuple[int, tuple[Path, ...]]] = [
    (
        2008,
        (
            Path("data/crosswalks/block20_to_sbe_2006_via_block00_nhgis_filled.csv"),
            Path("data/crosswalks/block20_to_sbe_2006_via_block10.csv"),
            Path("data/crosswalks/block20_to_sbe_2006_via_block00_nhgis.csv"),
            Path("data/crosswalks/block20_to_sbe_2006.csv"),
            Path("data/crosswalks/block20_to_vtd00.csv"),
        ),
    ),
    (
        2010,
        (
            Path("data/crosswalks/block20_to_sbe_2012_via_block10.csv"),
            Path("data/crosswalks/block20_to_sbe_2012.csv"),
            Path("data/crosswalks/block20_to_sbe_2006_via_block00_nhgis_filled.csv"),
        ),
    ),
    (
        2012,
        (
            Path("data/crosswalks/block20_to_sbe_2012_via_block10.csv"),
            Path("data/crosswalks/block20_to_sbe_2012.csv"),
        ),
    ),
    (
        2014,
        (
            Path("data/crosswalks/block20_to_sbe_2014_via_block10.csv"),
            Path("data/crosswalks/block20_to_sbe_2014.csv"),
            Path("data/crosswalks/block20_to_sbe_2013.csv"),
            Path("data/crosswalks/block20_to_sbe_2012_via_block10.csv"),
        ),
    ),
    (
        2016,
        (
            Path("data/crosswalks/block20_to_sbe_2016_via_block10.csv"),
            Path("data/crosswalks/block20_to_sbe_2015_via_block10.csv"),
            Path("data/crosswalks/block20_to_sbe_2015.csv"),
            Path("data/crosswalks/block20_to_sbe_2014_via_block10.csv"),
            Path("data/crosswalks/block20_to_sbe_2014.csv"),
        ),
    ),
    (
        2018,
        (
            Path("data/crosswalks/block20_to_sbe_2017_via_block10.csv"),
            Path("data/crosswalks/block20_to_sbe_2017.csv"),
            Path("data/crosswalks/block20_to_sbe_2016_via_block10.csv"),
            Path("data/crosswalks/block20_to_sbe_2015_via_block10.csv"),
            Path("data/crosswalks/block20_to_sbe_2015.csv"),
        ),
    ),
    (
        2021,
        (Path("data/crosswalks/block20_to_sbe_2020.csv"),),
    ),
    (
        2023,
        (
            Path("data/crosswalks/block20_to_sbe_2022.csv"),
            Path("data/crosswalks/block20_to_sbe_2020.csv"),
        ),
    ),
    (
        2025,
        (
            Path("data/crosswalks/block20_to_sbe_2024.csv"),
            Path("data/crosswalks/block20_to_onemap_2025_12.csv"),
        ),
    ),
    (
        9999,
        (Path("data/crosswalks/block20_to_onemap_2025_12.csv"),),
    ),
]


def resolve_vintage_match_crosswalk(year: int, fallback: Path | None = None) -> Path:
    """Pick the election-proximal block→precinct CSV for matching + VAP shatter."""
    y = int(year)
    for year_max, candidates in VINTAGE_MATCH_CROSSWALKS:
        if y <= int(year_max):
            for path in candidates:
                if Path(path).exists():
                    return Path(path)
            break
    if fallback is not None and Path(fallback).exists():
        return Path(fallback)
    raise FileNotFoundError(
        f"No vintage match crosswalk found for year={y}. "
        f"Checked ladder through year_max tiers and fallback={fallback!s}."
    )


NON_GEO_FLAGS = [
    "ABSENTEE",
    "ABSEN",
    "ABS",
    "ONE STOP",
    "ONE-STOP",
    "EARLY",
    "EV ",
    "EV-",
    "EV_",
    "PROVISIONAL",
    "PROVI",
    "PROV",
    "CURBSIDE",
    "MAIL",
    "TRANSFER",
]

KNOWN_OFFICE_KEYS = {
    "US PRESIDENT": "president",
    "PRESIDENT": "president",
    "PRESIDENT-VICE PRESIDENT": "president",
    "PRESIDENT AND VICE PRESIDENT": "president",
    "PRESIDENT-VICE-PRESIDENT": "president",
    "US SENATE": "us_senate",
    "UNITED STATES SENATE": "us_senate",
    "NC GOVERNOR": "governor",
    "GOVERNOR": "governor",
    "NC LIEUTENANT GOVERNOR": "lieutenant_governor",
    "LIEUTENANT GOVERNOR": "lieutenant_governor",
    "NC ATTORNEY GENERAL": "attorney_general",
    "ATTORNEY GENERAL": "attorney_general",
    "NC AUDITOR": "auditor",
    "AUDITOR": "auditor",
    "NC COMMISSIONER OF AGRICULTURE": "agriculture_commissioner",
    "COMMISSIONER OF AGRICULTURE": "agriculture_commissioner",
    "NC COMMISSIONER OF LABOR": "labor_commissioner",
    "COMMISSIONER OF LABOR": "labor_commissioner",
    "NC COMMISSIONER OF INSURANCE": "insurance_commissioner",
    "COMMISSIONER OF INSURANCE": "insurance_commissioner",
    "NC SECRETARY OF STATE": "secretary_of_state",
    "SECRETARY OF STATE": "secretary_of_state",
    "NC TREASURER": "treasurer",
    "TREASURER": "treasurer",
    "NC SUPERINTENDENT OF PUBLIC INSTRUCTION": "superintendent",
    "SUPERINTENDENT OF PUBLIC INSTRUCTION": "superintendent",
    "SUPER. OF PUBLIC INSTRUCTION": "superintendent",
    "NC COURT OF APPEALS JUDGE SEAT 12": "nc_court_of_appeals_judge_seat_12",
    "NC COURT OF APPEALS JUDGE SEAT 14": "nc_court_of_appeals_judge_seat_14",
    "NC COURT OF APPEALS JUDGE SEAT 15": "nc_court_of_appeals_judge_seat_15",
    "NC SUPREME COURT ASSOCIATE JUSTICE SEAT 06": "nc_supreme_court_associate_justice_seat_06",
}

PRESIDENT_OFFICE_KEY = "president"


# County-specific precinct aliases to improve key matching for older years where
# precinct naming varies between results exports and the precinct crosswalk.
#
# Keys and values refer to the precinct token portion of `precinct_id`
# (the part after "COUNTY - "). Values must match the canonical precinct token
# used by `data/crosswalks/block20_to_precinct.csv`.
PRECINCT_ALIASES: dict[str, dict[str, str]] = {
    "ROBESON": {
        "ALFORDSVILLE": "01",
        "ALF": "01",
        "BACK SWAMP": "02",
        "BACK": "02",
        "BRITTS": "03",
        "BURNT SWAMP": "04",
        "GADDYS": "07",
        "GADDY": "07",
        "LUMBERTON 1": "14",
        "LUM 1": "14",
        "LUMBERTON 8": "21",
        "LUM 8": "21",
        "MAXTON": "22",
        "MAX": "22",
        "ORRUM": "24",
        "ORR": "24",
        "PEMBROKE 1": "26",
        "PEM 1": "26",
        "RENNERT": "31",
        "RENS": "31",
        "SADDLETREE": "32",
        "SADD": "32",
        "ST PAULS": "34",
        "ST P": "34",
    },
    "WAKE": {
        # Common suffix variants where the canonical key is the base code.
        "20-10A": "20-10",
        "20-10B": "20-10",
    },
    "CABARRUS": {
        "HAR": "12-09",
        "HARRISBURG": "12-09",
    },
    # OE numeric codes → 2025Voting_Precincts *A keys.
    "GASTON": {
        **{f"{i:02d}": f"{i}A" for i in range(1, 41)},
        **{str(i): f"{i}A" for i in range(1, 41)},
    },
}


def _norm(text: str) -> str:
    return str(text).strip().upper()

def _norm_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", _norm(text))

def _compact_token(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", _norm(text))

def precinct_bucket_from_code(precinct_code: str) -> str:
    """
    Derive a 'bucket' key used only for allocating *unmatched* precinct totals.

    The previous approach bucketed by the first token before '-' (e.g. '01-07A' -> '01'),
    which is too coarse in counties like WAKE/MECK where many distinct precinct codes share
    the same leading group. That smears unmatched votes across too many districts.

    Strategy:
      - If the code looks like A-B or A-B<letter>, bucket by A-B (strip suffix letter).
      - Otherwise fall back to legacy behavior: first token before '-'.
    """
    p = _norm(precinct_code)
    if not p:
        return ""
    m = re.fullmatch(r"0*([0-9]{1,3})-0*([0-9]{1,3})(?:[A-Z])?", p)
    if m:
        a = int(m.group(1))
        b = int(m.group(2))
        aa = str(a).zfill(2) if a < 100 else str(a)
        bb = str(b).zfill(2) if b < 100 else str(b)
        return f"{aa}-{bb}"
    return p.split("-")[0].strip()


def load_sbe_precinct_code_map(shp_path: Path) -> dict[tuple[str, str], str]:
    """
    Load NCSBE precinct shapefile attributes and return:
      (COUNTY_NAM, ENR_DESC) -> PREC_ID

    This is used as a high-confidence alias source for older years where the
    precinct exports use ENR_DESC-like labels.
    """
    if not shp_path.exists():
        return {}
    g0 = gpd.read_file(shp_path)
    cols = {c.lower(): c for c in list(g0.columns)}

    # Support multiple vintage schemas, including Precincts2006Gen
    # (County, Precinct, SEIMS_Code).
    prec_col = (
        cols.get("prec_id")
        or cols.get("seims_code")
        or cols.get("precinct_i")
        or cols.get("precid")
        or cols.get("precinctid")
        or cols.get("precinct_id")
    )
    desc_cols = []
    for name in ("enr_desc", "seims_desc", "precinct", "enrdesc", "name", "prec_name"):
        col = cols.get(name)
        if col and col not in desc_cols:
            desc_cols.append(col)
    county_col = cols.get("county_nam") or cols.get("county_name") or cols.get("countynam") or cols.get("county")

    if not prec_col or not desc_cols or not county_col:
        return {}

    g = g0[[prec_col, county_col, *desc_cols]].copy()
    g = g.rename(columns={prec_col: "PREC_ID", county_col: "COUNTY_NAM"})
    g["PREC_ID"] = g["PREC_ID"].astype(str).map(_norm)
    g["COUNTY_NAM"] = g["COUNTY_NAM"].astype(str).map(_norm)
    for col in desc_cols:
        g[col] = g[col].astype(str).map(_norm_spaces)
    g = g[(g["PREC_ID"] != "") & (g["COUNTY_NAM"] != "")].copy()

    out: dict[tuple[str, str], str] = {}
    for _, r in g.iterrows():
        for col in desc_cols:
            desc = str(r[col]).strip()
            if not desc:
                continue
            key = (r["COUNTY_NAM"], desc)
            out[key] = r["PREC_ID"]
            # Common variants: underscores vs spaces.
            out[(r["COUNTY_NAM"], _norm_spaces(desc.replace("_", " ")))] = r["PREC_ID"]
            out[(r["COUNTY_NAM"], _norm_spaces(desc.replace(" ", "_")))] = r["PREC_ID"]
            # Many description values include a code prefix like "CC01_CROSS CREEK #01".
            # Add a variant that drops the leading "<CODE>_" so exports that only
            # include the human-readable label can still resolve.
            if "_" in desc:
                right = _norm_spaces(str(desc).split("_", 1)[1])
                if right:
                    out[(r["COUNTY_NAM"], right)] = r["PREC_ID"]
    return out


def clean_precinct_name(precinct: str, county: str) -> str:
    """
    Normalize a precinct token to better match our canonical crosswalk keyspace.

    Conservative by design: if we cannot confidently normalize, return the
    original (uppercased/trimmed) string.
    """
    county_u = _norm(county)
    p = _norm(precinct)

    # 0) If we have an official SBE ENR_DESC->PREC_ID map loaded for this year,
    # use it first (most reliable).
    sbe_map = getattr(clean_precinct_name, "_sbe_map", None)
    if isinstance(sbe_map, dict):
        hit = sbe_map.get((county_u, _norm_spaces(p)))
        if hit:
            return _norm(hit)

    # 1) Hard-coded aliases (county-specific).
    ali = PRECINCT_ALIASES.get(county_u)
    if ali:
        hit = ali.get(p)
        if hit:
            return _norm(hit)

    # 2) Strip boilerplate words sometimes included in exports.
    p = p.replace("PRECINCT", " ").replace("VTD", " ").strip()
    # Some exports use "PCT <num>" for coded precincts (notably Mecklenburg in 2008).
    # Convert those to the canonical numeric code where possible.
    m = re.fullmatch(r"PCT\s*0*([0-9]{1,3})(\.[0-9]+)?", p)
    if m:
        num = int(m.group(1))
        suffix = m.group(2) or ""
        if county_u == "MECKLENBURG":
            base = str(num).zfill(3) if num < 100 else str(num)
            return f"{base}{suffix}"
        return f"{num}{suffix}"

    # 2b) Many historical exports use "CODE_NAME" patterns where the crosswalk
    # canonical key is just the code (e.g., "01_PATTERSON" -> "01").
    if "_" in p:
        left = p.split("_", 1)[0].strip()
        if left:
            p = left

    # 3) Standard NC code patterns like "01-14", "01-14A", "4-11", "03-00".
    m = re.search(r"\b(\d{1,3})-(\d{1,3})[A-Z]?\b", p)
    if m:
        a = m.group(1)
        b = m.group(2)
        # Many counties use 2-digit code groups in the crosswalk (e.g., 01-14),
        # but exports may include leading zeros (e.g., 020-10A).
        if a.isdigit():
            ai = int(a)
            a = str(ai).zfill(2) if ai < 100 else str(ai)
        if b.isdigit():
            bi = int(b)
            b = str(bi).zfill(2) if bi < 100 else str(bi)
        return f"{a}-{b}"

    # 4) Pure numeric code (Robeson uses 2-digit codes).
    if p.isdigit():
        if county_u == "ROBESON":
            return str(int(p)).zfill(2)
        return str(int(p))

    # 5) If the first token contains digits, it's probably a code like "06N" or "03C".
    tok = p.split()[0].strip() if p else ""
    if tok and any(ch.isdigit() for ch in tok) and re.fullmatch(r"[0-9A-Z-]+", tok):
        return tok

    return p


def normalize_presidential_candidate_name(name: str) -> str:
    """
    Strip running mate / ticket formatting from presidential candidate strings.
    Examples:
      "DONALD J. TRUMP / J.D. VANCE" -> "DONALD J. TRUMP"
      "A. Gore-J. Lieberman" -> "A. Gore"
    """
    raw = str(name or "").strip()
    if not raw:
        return ""

    for sep in [" / ", "/", " & ", "&", " + ", "+", " - ", " – ", " — "]:
        if sep in raw:
            left = raw.split(sep, 1)[0].strip()
            return left if left else raw

    # Hyphen tickets in older datasets, but try not to mangle compound surnames.
    if "-" in raw:
        left, right = raw.split("-", 1)
        left = left.strip()
        right = right.strip()
        if left and right and (("." in right) or (" " in right) or (right.isupper() and len(right) <= 20)):
            return left

    return raw


def canonicalize_candidate_label(name: str) -> str:
    """
    Normalize known punctuation variants for candidate display labels.
    """
    raw = str(name or "").strip()
    if not raw:
        return ""
    t = re.sub(r"\s+", " ", raw).strip().upper().replace(".", "")
    if t in {"PHIL BERGER JR", "PHIL BERGER, JR"}:
        return "Phil Berger, Jr."
    return raw


def infer_office_key(office: str) -> str | None:
    o_full = str(office).strip().upper()
    o_full = re.sub(r"\s+", " ", o_full)

    # Strip common parenthetical metadata like "(VOTE FOR 1)" but keep named-seat labels.
    o = re.sub(r"\s+\((?:VOTE FOR|VOTE|NONPARTISAN|PARTISAN|UNEXPIRED).*?\)$", "", o_full)

    direct = KNOWN_OFFICE_KEYS.get(o)
    if direct:
        return direct

    def _slug(s: str) -> str:
        s = str(s).strip().upper()
        s = re.sub(r"[^A-Z0-9]+", "_", s)
        s = s.strip("_")
        return s.lower()

    m = re.match(r"^NC COURT OF APPEALS JUDGE SEAT\s*0*([0-9]+)$", o)
    if m:
        return f"nc_court_of_appeals_judge_seat_{int(m.group(1)):02d}"

    m = re.match(r"^NC SUPREME COURT ASSOCIATE JUSTICE SEAT\s*0*([0-9]+)$", o)
    if m:
        return f"nc_supreme_court_associate_justice_seat_{int(m.group(1)):02d}"

    m = re.match(r"^NC SUPREME COURT CHIEF JUSTICE SEAT\s*0*([0-9]+)$", o)
    if m:
        return f"nc_supreme_court_chief_justice_seat_{int(m.group(1)):02d}"

    if o == "NC SUPREME COURT CHIEF JUSTICE":
        return "nc_supreme_court_chief_justice"

    # Legacy presidential label.
    if "PRESIDENT" in o_full and "VICE PRESIDENT" in o_full and "REPRESENTATIVES" not in o_full:
        return "president"

    # Older NCSBE labels often used named seats, e.g.:
    #   "SUPREME COURT ASSOCIATE JUSTICE (EDMUNDS SEAT)"
    #   "COURT OF APPEALS JUDGE (TYSON SEAT)"
    m = re.match(r"^SUPREME COURT ASSOCIATE JUSTICE\s*\((.+?)\s+SEAT\)$", o_full)
    if m:
        return f"nc_supreme_court_associate_justice_{_slug(m.group(1))}_seat"

    m = re.match(r"^SUPREME COURT CHIEF JUSTICE\s*\((.+?)\s+SEAT\)$", o_full)
    if m:
        return f"nc_supreme_court_chief_justice_{_slug(m.group(1))}_seat"

    m = re.match(r"^COURT OF APPEALS JUDGE\s*\((.+?)\s+SEAT\)$", o_full)
    if m:
        return f"nc_court_of_appeals_judge_{_slug(m.group(1))}_seat"

    # Alternate legacy formats using a dash instead of parentheses.
    m = re.match(r"^SUPREME COURT ASSOCIATE JUSTICE\s*-\s*(.+?)\s+SEAT$", o_full)
    if m:
        return f"nc_supreme_court_associate_justice_{_slug(m.group(1))}_seat"

    m = re.match(r"^SUPREME COURT CHIEF JUSTICE\s*-\s*(.+?)\s+SEAT$", o_full)
    if m:
        return f"nc_supreme_court_chief_justice_{_slug(m.group(1))}_seat"

    m = re.match(r"^COURT OF APPEALS JUDGE\s*-\s*(.+?)\s+SEAT$", o_full)
    if m:
        return f"nc_court_of_appeals_judge_{_slug(m.group(1))}_seat"

    # 2010/2012 "NC … - Name Seat" labels (OE) and 2014 parentheses forms.
    #   "NC COURT OF APPEALS JUDGE - Bryant Seat"
    #   "NC SUPREME COURT ASSOCIATE JUSTICE - Newby Seat"
    #   "NC COURT OF APPEALS JUDGE (DAVIS)"
    #   "NC SUPREME COURT ASSOCIATE JUSTICE (HUDSON)"
    #   "NC SUPREME COURT CHIEF JUSTICE (PARKER)"
    #   "NC SUPREME COURT ASSOCIATE JUSTICE" (2016 Edmunds seat – seat omitted in OE)
    m = re.match(r"^NC COURT OF APPEALS JUDGE\s*-\s*(.+?)\s+SEAT$", o_full)
    if m:
        return f"nc_court_of_appeals_judge_{_slug(m.group(1))}_seat"

    m = re.match(r"^NC SUPREME COURT ASSOCIATE JUSTICE\s*-\s*(.+?)\s+SEAT$", o_full)
    if m:
        return f"nc_supreme_court_associate_justice_{_slug(m.group(1))}_seat"

    m = re.match(r"^NC SUPREME COURT CHIEF JUSTICE\s*-\s*(.+?)\s+SEAT$", o_full)
    if m:
        return f"nc_supreme_court_chief_justice_{_slug(m.group(1))}_seat"

    m = re.match(r"^NC COURT OF APPEALS JUDGE\s*\((.+?)\)$", o_full)
    if m:
        return f"nc_court_of_appeals_judge_{_slug(m.group(1))}_seat"

    m = re.match(r"^NC SUPREME COURT ASSOCIATE JUSTICE\s*\((.+?)\)$", o_full)
    if m:
        return f"nc_supreme_court_associate_justice_{_slug(m.group(1))}_seat"

    m = re.match(r"^NC SUPREME COURT CHIEF JUSTICE\s*\((.+?)\)$", o_full)
    if m:
        return f"nc_supreme_court_chief_justice_{_slug(m.group(1))}_seat"

    if o_full == "NC SUPREME COURT ASSOCIATE JUSTICE":
        # 2016 OE dropped the seat name; historically the Edmunds associate seat.
        return "nc_supreme_court_associate_justice_edmunds_seat"

    # Skip multi-candidate IRV vacancy contests (no clean two-party map).
    if "IRV" in o_full:
        return None

    return None


def is_non_geographic_precinct(name: str, county: str | None = None) -> bool:
    t = str(name).strip().upper()
    c = _norm(county or "")
    # Some real precinct names/codes contain "PROV*" but are geographic
    # (e.g., CASWELL/WAKE "PROVI", JOHNSTON "PROVIDENCE").
    if t == "PROVIDENCE":
        return False
    if c in {"CASWELL", "WAKE"} and t == "PROVI":
        return False
    # NC precinct-sort exports often abbreviate one-stop/early vote as "OS <SITE>"
    # (e.g., "OS MAXTON"). Treat these as non-geographic buckets.
    if t == "OS" or t.startswith("OS ") or t.startswith("OS-") or t.startswith("OS_"):
        return True
    # Some counties (notably WAKE in OpenElections precinct exports) use compact one-stop
    # codes like "OSNB 81-91" (no space after "OS"). Treat any OS-prefixed bucket as non-geo.
    if re.match(r"^OS[A-Z0-9]+", t):
        return True
    # Some files use suffix forms like "NASHVILLE OS" / "BOE OS".
    if re.search(r"(^|[^A-Z0-9])OS([^A-Z0-9]|$)", t):
        return True
    # Some counties use a compact "ONESTOP" label.
    if t == "ONESTOP" or t.startswith("ONESTOP "):
        return True
    # Bare "EV" appears in some county exports (e.g. Henderson) as an early-vote bucket.
    if t == "EV" or re.match(r"^EV[A-Z0-9]+$", t):
        return True
    # Buncombe 2020 OE uses 4-letter early-vote *site* codes (AVML, WGSC, …) alongside
    # geographic decimal precincts (01.1). Those sites must allocate, not choropleth.
    if c == "BUNCOMBE" and re.fullmatch(r"[A-Z]{4}", t):
        return True
    # Wake compact transfer buckets: "TRANS 1-40" (TRANSFER abbreviated).
    if t.startswith("TRANS ") or t.startswith("TRANS_") or re.match(r"^TRANS\d", t):
        return True
    # Recurring county BOE / DSS / co-op one-stop site labels (not polygon keys).
    if t in {
        "BOE OFFICE",
        "MURFREE CNTR",
        "DET OF SOCIAL SERVICES",
        "PINES CHAP FELLSHIP HALL",
        "CO OP",
        "BROWDER",
        "BLAD COUNTY GYM",
        "BAY TREE FIRE DEPT",
        "BOOK T. WASHINGTON",
        "SPAULDING MONROE",
        "TAR HEEL MUNI BLD",
        "EAST ARCADIA",
    }:
        return True
    # Hamlet / Ellerbe appear as Richmond early-vote sites in 2020 OE (polygons use 01–16).
    if c == "RICHMOND" and t in {"HAMLET", "ELLERBE"}:
        return True
    return any(flag in t for flag in NON_GEO_FLAGS)


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


def load_district_map(path: Path, block_col: str, district_col: str) -> pd.DataFrame:
    d = pd.read_csv(path, dtype=str)
    d.columns = [str(c).strip() for c in d.columns]
    block_candidates = [block_col, "block_geoid20", "GEOID", "GEOID20", "Block"]
    district_candidates = [district_col, "district", "District", "CDFP", "DISTRICT"]
    actual_block_col = next((c for c in block_candidates if c in d.columns), None)
    actual_district_col = next((c for c in district_candidates if c in d.columns), None)
    if actual_block_col is None or actual_district_col is None:
        raise ValueError(
            f"{path} missing district map columns. "
            f"Need one of {block_candidates} and one of {district_candidates}; "
            f"found {list(d.columns)}"
        )
    out = d[[actual_block_col, actual_district_col]].copy()
    out.columns = ["block_geoid20", "district"]
    out["block_geoid20"] = out["block_geoid20"].astype(str).str.strip().str.zfill(15)
    out["district"] = out["district"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    m = out["district"].str.match(r"^\d+$", na=False)
    out.loc[m, "district"] = out.loc[m, "district"].str.lstrip("0")
    out.loc[out["district"] == "", "district"] = "0"
    return out.dropna().drop_duplicates(subset=["block_geoid20"], keep="first")

def _signed_margin_pct(dem_votes: int, rep_votes: int, total_votes: int) -> float:
    t = float(total_votes or 0)
    if t <= 0:
        return 0.0
    return ((float(rep_votes) - float(dem_votes)) / t) * 100.0


def _winner_label(dem_votes: int, rep_votes: int) -> str:
    if rep_votes > dem_votes:
        return "REP"
    if dem_votes > rep_votes:
        return "DEM"
    return "TIE"


def round_precinct_party_votes_preserve_county_totals(precinct_party: pd.DataFrame) -> pd.DataFrame:
    """Round precinct vote floats while keeping each county/party total rounded exactly."""
    if precinct_party is None or precinct_party.empty:
        return precinct_party

    out = precinct_party.copy()
    out["precinct_id"] = out["precinct_id"].astype(str).str.strip().str.upper()
    out["_county"] = out["precinct_id"].str.split(" - ").str[0].str.strip().str.upper()
    vote_cols = [c for c in ["dem_votes", "rep_votes", "other_votes"] if c in out.columns]
    for col in vote_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
        rounded = pd.Series(0, index=out.index, dtype="int64")
        for _, idx in out.groupby("_county").groups.items():
            vals = out.loc[idx, col].astype(float)
            floors = vals.map(lambda v: int(v // 1))
            target = int(round(float(vals.sum())))
            remainder = target - int(floors.sum())
            adjusted = floors.copy()
            if remainder > 0:
                order = (vals - floors).sort_values(ascending=False).index[:remainder]
                adjusted.loc[order] = adjusted.loc[order] + 1
            elif remainder < 0:
                order = (vals - floors).sort_values(ascending=True).index[: abs(remainder)]
                adjusted.loc[order] = adjusted.loc[order] - 1
            rounded.loc[idx] = adjusted.astype("int64")
        out[col] = rounded
    return out.drop(columns=["_county"])


def build_precinct_contest_payload(
    *,
    year: int,
    contest_type: str,
    office_label: str,
    nongeo_allocation_mode: str,
    precinct_party: pd.DataFrame,
    dem_candidate: str,
    rep_candidate: str,
    display_precinct_overrides: dict[str, str] | None = None,
) -> dict:
    """
    Build a data/contests/<contest_type>_<year>.json payload.

    Rows are precinct-level and keyed by "county" (matching index.html conventions),
    where county is a "COUNTY - PRECINCT" precinct_id string.
    """
    rows: list[dict] = []
    dem_total = 0
    rep_total = 0
    other_total = 0
    if precinct_party is None or precinct_party.empty:
        return {"rows": []}
    precinct_party = apply_display_precinct_overrides(precinct_party, display_precinct_overrides)
    precinct_party = round_precinct_party_votes_preserve_county_totals(precinct_party)

    for _, r in precinct_party.iterrows():
        precinct_id = str(r.get("precinct_id", "")).strip().upper()
        if not precinct_id:
            continue
        dem = int(round(float(r.get("dem_votes", 0) or 0)))
        rep = int(round(float(r.get("rep_votes", 0) or 0)))
        oth = int(round(float(r.get("other_votes", 0) or 0)))
        total = dem + rep + oth
        if total <= 0:
            continue
        m_pct = _signed_margin_pct(dem, rep, total)
        winner = _winner_label(dem, rep)
        rows.append(
            {
                "year": int(year),
                "county": precinct_id,
                "dem_votes": dem,
                "rep_votes": rep,
                "other_votes": oth,
                "total_votes": total,
                "dem_candidate": dem_candidate or "",
                "rep_candidate": rep_candidate or "",
                "margin": int(rep - dem),
                "margin_pct": float(round(m_pct, 4)),
                "winner": winner,
                "color": calculate_competitiveness(m_pct),
            }
        )
        dem_total += dem
        rep_total += rep
        other_total += oth

    rows.sort(key=lambda x: str(x.get("county", "")))
    total_votes = int(dem_total + rep_total + other_total)
    major_party_contested = bool(dem_total > 0 and rep_total > 0)
    return {
        "year": int(year),
        "contest_type": str(contest_type),
        "meta": {
            "source": "batch_shatter_vap_party_split",
            "office": office_label,
            "nongeo_allocation_mode": nongeo_allocation_mode,
            "dem_total": int(dem_total),
            "rep_total": int(rep_total),
            "other_total": int(other_total),
            "total_votes": total_votes,
            "major_party_contested": major_party_contested,
        },
        "rows": rows,
    }


def build_contests_manifest_entry(*, year: int, contest_type: str, file_name: str, payload: dict) -> dict:
    rows = payload.get("rows") or []
    meta = payload.get("meta") or {}
    dem_total = int(meta.get("dem_total", 0) or 0)
    rep_total = int(meta.get("rep_total", 0) or 0)
    total_votes = int(meta.get("total_votes", 0) or 0)
    if total_votes <= 0 and rows:
        dem_total = int(sum(int(r.get("dem_votes", 0) or 0) for r in rows))
        rep_total = int(sum(int(r.get("rep_votes", 0) or 0) for r in rows))
        total_votes = int(sum(int(r.get("total_votes", 0) or 0) for r in rows))
    major_party_contested = bool(dem_total > 0 and rep_total > 0)
    return {
        "year": int(year),
        "contest_type": str(contest_type),
        "file": str(file_name),
        "rows": int(len(rows)),
        "dem_total": dem_total,
        "rep_total": rep_total,
        "total_votes": total_votes,
        "major_party_contested": major_party_contested,
    }


def update_contests_manifest(manifest_path: Path, entries: list[dict]) -> None:
    if not entries:
        return
    base = {"files": []}
    if manifest_path.exists():
        try:
            base = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            base = {"files": []}
    files = list((base.get("files") or []))

    idx: dict[tuple[str, int], dict] = {}
    for e in files:
        try:
            idx[(str(e.get("contest_type")), int(e.get("year")))] = e
        except Exception:
            continue
    for e in entries:
        idx[(str(e.get("contest_type")), int(e.get("year")))] = e

    merged = list(idx.values())
    merged.sort(key=lambda x: (int(x.get("year", 0)), str(x.get("contest_type", ""))))
    manifest_path.write_text(json.dumps({"files": merged}, indent=2), encoding="utf-8")


def build_county_shares(
    crosswalk_df: pd.DataFrame,
    vap_df: pd.DataFrame,
    district_map: pd.DataFrame,
) -> pd.DataFrame:
    cw = crosswalk_df.copy()
    cw["county"] = cw["precinct_id"].astype(str).str.split(" - ").str[0].str.strip().str.upper()
    v = vap_df.copy()
    v["vap_count"] = pd.to_numeric(v["vap_count"], errors="coerce").fillna(0.0)
    m = (
        cw[["block_geoid20", "county"]]
        .merge(v[["block_geoid20", "vap_count"]], on="block_geoid20", how="left")
        .merge(district_map[["block_geoid20", "district"]], on="block_geoid20", how="inner")
    )
    m["vap_count"] = m["vap_count"].fillna(0.0)
    g = m.groupby(["county", "district"], as_index=False)["vap_count"].sum()
    den = g.groupby("county", as_index=False)["vap_count"].sum().rename(columns={"vap_count": "county_vap"})
    g = g.merge(den, on="county", how="left")
    g["share"] = g["vap_count"] / g["county_vap"]
    return g[["county", "district", "share"]]


def build_precinct_bucket_shares(
    crosswalk_df: pd.DataFrame,
    vap_df: pd.DataFrame,
    district_map: pd.DataFrame,
) -> pd.DataFrame:
    cw = crosswalk_df.copy()
    cw["county"] = cw["precinct_id"].astype(str).str.split(" - ").str[0].str.strip().str.upper()
    p = cw["precinct_id"].astype(str).str.split(" - ").str[1].fillna("").str.strip().str.upper()
    cw["bucket"] = p.map(precinct_bucket_from_code)
    cw = cw[cw["bucket"] != ""].copy()

    v = vap_df.copy()
    v["vap_count"] = pd.to_numeric(v["vap_count"], errors="coerce").fillna(0.0)
    m = (
        cw[["block_geoid20", "county", "bucket"]]
        .merge(v[["block_geoid20", "vap_count"]], on="block_geoid20", how="left")
        .merge(district_map[["block_geoid20", "district"]], on="block_geoid20", how="inner")
    )
    m["vap_count"] = m["vap_count"].fillna(0.0)
    g = m.groupby(["county", "bucket", "district"], as_index=False)["vap_count"].sum()
    den = g.groupby(["county", "bucket"], as_index=False)["vap_count"].sum().rename(columns={"vap_count": "bucket_vap"})
    g = g.merge(den, on=["county", "bucket"], how="left")
    g["share"] = g["vap_count"] / g["bucket_vap"]
    return g[["county", "bucket", "district", "share"]]


def load_allocation_weights(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_precinct_overrides(path: Path, year: int) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return {}
    if df.empty:
        return {}
    req = {"raw_precinct_key", "canonical_precinct_key"}
    if not req.issubset(set(df.columns)):
        return {}
    if "year" in df.columns:
        y = str(int(year))
        df = df[(df["year"].astype(str).str.strip() == "") | (df["year"].astype(str).str.strip() == y)].copy()
    df["raw_precinct_key"] = df["raw_precinct_key"].astype(str).str.strip().str.upper()
    df["canonical_precinct_key"] = df["canonical_precinct_key"].astype(str).str.strip().str.upper()
    df = df[(df["raw_precinct_key"] != "") & (df["canonical_precinct_key"] != "")]
    return dict(zip(df["raw_precinct_key"], df["canonical_precinct_key"]))


def build_auto_precinct_overrides(precinct_ids: pd.Series, matched_precincts: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    vals = {
        str(v).strip().upper()
        for v in pd.Series(precinct_ids).dropna().tolist()
        if str(v).strip() and str(v).strip().upper() not in {"NAN", "NONE"}
    }

    county_tokens: dict[str, set[str]] = {}
    county_compact_tokens: dict[str, dict[str, set[str]]] = {}
    for raw_key in matched_precincts:
        key = str(raw_key).strip().upper()
        if key in {"", "NAN", "NONE"}:
            continue
        if " - " not in key:
            continue
        county, tok = key.split(" - ", 1)
        county = _norm(county)
        tok = _norm(tok)
        if not county or not tok:
            continue
        county_tokens.setdefault(county, set()).add(tok)

    for county, toks in county_tokens.items():
        c_map: dict[str, set[str]] = {}
        for tok in toks:
            comp = _compact_token(tok)
            if not comp:
                continue
            c_map.setdefault(comp, set()).add(tok)
        county_compact_tokens[county] = c_map

    def _resolve_unique_token(county: str, candidates: list[str] | set[str]) -> str | None:
        toks = sorted({str(t).strip().upper() for t in candidates if str(t).strip()})
        if len(toks) != 1:
            return None
        cand = f"{county} - {toks[0]}"
        return cand if cand in matched_precincts else None

    for raw in sorted(vals, key=str):
        if not raw or raw in matched_precincts or " - " not in raw:
            continue
        county, p = raw.split(" - ", 1)
        county = _norm(county)
        p = _norm(p)

        # Use SBE ENR_DESC->PREC_ID if available (strongest signal).
        sbe_map = getattr(build_auto_precinct_overrides, "_sbe_map", None)
        if isinstance(sbe_map, dict):
            hit = sbe_map.get((county, _norm_spaces(p)))
            if hit:
                cand = f"{county} - {_norm(hit)}"
                if cand in matched_precincts:
                    out[raw] = cand
                    continue

        # County-specific aliases (named precincts -> coded keys).
        ali = PRECINCT_ALIASES.get(county)
        if ali:
            hit = ali.get(p)
            if hit:
                cand = f"{county} - {_norm(hit)}"
                if cand in matched_precincts:
                    out[raw] = cand
                    continue

        # Generic cleanup: extract standard codes from messy labels.
        cleaned = clean_precinct_name(p, county)
        if cleaned and cleaned != p:
            cand = f"{county} - {cleaned}"
            if cand in matched_precincts:
                out[raw] = cand
                continue

        # Example: WAKE - 01-07A -> WAKE - 01-07 if canonical exists.
        if p.endswith("A"):
            cand = f"{county} - {p[:-1]}"
            if cand in matched_precincts:
                out[raw] = cand
                continue

        # Example: GASTON - 29-1 -> GASTON - 29A; GASTON - 04-1 -> GASTON - 4A.
        m = re.match(r"^0*([0-9]+)(?:-1)?$", p)
        if m:
            cand = f"{county} - {int(m.group(1))}A"
            if cand in matched_precincts:
                out[raw] = cand
                continue

        # Example: ROCKINGHAM - WS -> ROCKINGHAM - WS-1.
        if re.fullmatch(r"[A-Z0-9]+", p):
            cand = f"{county} - {p}-1"
            if cand in matched_precincts:
                out[raw] = cand
                continue

        # Zero-padded numeric variants (e.g., UNION 019 -> 0019, 020A -> 0020A).
        m = re.fullmatch(r"0*([0-9]{1,4})([A-Z]?)", p)
        if m:
            n = int(m.group(1))
            suffix = m.group(2) or ""
            numeric_candidates = []
            for width in [1, 2, 3, 4]:
                base = str(n) if width == 1 else str(n).zfill(width)
                numeric_candidates.append(f"{base}{suffix}")
            cand = _resolve_unique_token(county, numeric_candidates)
            if cand:
                out[raw] = cand
                continue

        # Compact-token fallback for punctuated variants (e.g., DV1-A -> DV1A1A, CC3 -> CC3-1).
        p_comp = _compact_token(p)
        if p_comp:
            comp_map = county_compact_tokens.get(county, {})
            cand = _resolve_unique_token(county, comp_map.get(p_comp, set()))
            if cand:
                out[raw] = cand
                continue

            # Conservative prefix fallback: only when exactly one canonical token matches.
            if len(p_comp) >= 3:
                pref_hits: set[str] = set()
                for tok_comp, tok_set in comp_map.items():
                    if tok_comp.startswith(p_comp):
                        pref_hits.update(tok_set)
                cand = _resolve_unique_token(county, pref_hits)
                if cand:
                    out[raw] = cand
                    continue

    return out


def apply_precinct_overrides(df: pd.DataFrame, overrides: dict[str, str] | None) -> pd.DataFrame:
    if not overrides:
        return df
    out = df.copy()
    out["precinct_id"] = out["precinct_id"].astype(str).str.strip().str.upper()
    out["precinct_id"] = out["precinct_id"].map(lambda k: overrides.get(k, k))
    return out


def build_contest_display_overrides(
    precinct_ids: pd.Series,
    display_crosswalk_csv: Path | None,
) -> dict[str, str]:
    """
    Build conservative precinct display remaps from source/SBE keys to OneMap keys.

    District aggregation still uses the election-vintage match map. This helper is
    only for precinct-level contest JSON, where row keys must join to the current
    OneMap display layer.
    """
    if display_crosswalk_csv is None or not Path(display_crosswalk_csv).exists():
        return {}

    bridge = pd.read_csv(display_crosswalk_csv, dtype=str).fillna("")
    required = {"sbe_precinct_id", "onemap_precinct_id", "share"}
    if not required.issubset(set(bridge.columns)):
        return {}

    bridge = bridge[["sbe_precinct_id", "onemap_precinct_id", "share"]].copy()
    bridge["sbe_precinct_id"] = bridge["sbe_precinct_id"].astype(str).str.strip().str.upper()
    bridge["onemap_precinct_id"] = bridge["onemap_precinct_id"].astype(str).str.strip().str.upper()
    bridge["share"] = pd.to_numeric(bridge["share"], errors="coerce").fillna(0.0)
    bridge = bridge[(bridge["sbe_precinct_id"] != "") & (bridge["onemap_precinct_id"] != "")].copy()
    if bridge.empty:
        return {}

    unique_bridge: dict[str, str] = {}
    for sbe_id, group in bridge.groupby("sbe_precinct_id"):
        targets = sorted(set(group["onemap_precinct_id"].astype(str)))
        if len(targets) != 1:
            continue
        share = float(group["share"].sum())
        if abs(share - 1.0) > 0.000001:
            continue
        unique_bridge[str(sbe_id)] = targets[0]

    if not unique_bridge:
        return {}

    raw_ids = pd.Series(precinct_ids, dtype="string").astype(str).str.strip().str.upper()
    onemap_ids = set(bridge["onemap_precinct_id"])

    out: dict[str, str] = {}
    for raw in sorted(set(raw_ids)):
        if not raw or raw in onemap_ids:
            continue
        if " - " not in raw:
            continue
        county, precinct = raw.split(" - ", 1)
        county = _norm(county)
        precinct = _norm(precinct)

        candidates: list[str] = []
        if raw in unique_bridge:
            candidates.append(raw)

        sbe_map = getattr(build_auto_precinct_overrides, "_sbe_map", None)
        if isinstance(sbe_map, dict):
            hit = sbe_map.get((county, _norm_spaces(precinct)))
            if hit:
                candidates.append(f"{county} - {_norm(hit)}")

        alias_hit = PRECINCT_ALIASES.get(county, {}).get(precinct)
        if alias_hit:
            candidates.append(f"{county} - {_norm(alias_hit)}")

        if precinct.endswith("A"):
            candidates.append(f"{county} - {precinct[:-1]}")

        targets = {unique_bridge[cand] for cand in candidates if cand in unique_bridge}
        if len(targets) == 1:
            target = next(iter(targets))
            if target != raw:
                out[raw] = target
    return out


def apply_display_precinct_overrides(
    precinct_party: pd.DataFrame,
    overrides: dict[str, str] | None,
) -> pd.DataFrame:
    if not overrides or precinct_party is None or precinct_party.empty:
        return precinct_party

    out = precinct_party.copy()
    out["precinct_id"] = out["precinct_id"].astype(str).str.strip().str.upper().map(lambda k: overrides.get(k, k))
    vote_cols = [c for c in ["dem_votes", "rep_votes", "other_votes"] if c in out.columns]
    for col in vote_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    return out.groupby("precinct_id", as_index=False)[vote_cols].sum()


def apply_county_share_overrides(
    county_shares: pd.DataFrame,
    *,
    year: int,
    scope: str,
    allocation_weights: dict,
    min_county_share: float = 0.0,
) -> pd.DataFrame:
    out = county_shares.copy()
    inserts = []
    scope_weights = (allocation_weights.get(str(int(year)), {}) or {}).get(str(scope), {}) or {}
    for county, weights in scope_weights.items():
        county_u = str(county).strip().upper()
        out = out[out["county"].astype(str).str.upper() != county_u].copy()
        raw = {str(k).strip(): float(v) for k, v in weights.items()}
        if min_county_share > 0:
            raw = {k: v for k, v in raw.items() if v >= float(min_county_share)}
        if not raw:
            continue
        total = sum(raw.values())
        if total <= 0:
            continue
        for district, share in raw.items():
            inserts.append(
                {
                    "county": county_u,
                    "district": str(district).strip(),
                    "share": float(share) / total,
                }
            )
    if inserts:
        out = pd.concat([out, pd.DataFrame(inserts)], ignore_index=True)
    return out


def apply_unmatched_county_fallback(
    district_df: pd.DataFrame,
    results_df: pd.DataFrame,
    matched_precincts: set[str],
    county_shares: pd.DataFrame,
    precinct_bucket_shares: pd.DataFrame | None = None,
) -> dict[str, int]:
    d = district_df.copy()
    d["district"] = d["district"].astype(str).str.strip()
    d["votes_rounded"] = pd.to_numeric(d["votes_rounded"], errors="coerce").fillna(0.0)
    base = d.set_index("district")["votes_rounded"].to_dict()

    r = results_df.copy()
    r["precinct_id"] = r["precinct_id"].astype(str).str.strip().str.upper()
    r["votes"] = pd.to_numeric(r["votes"], errors="coerce").fillna(0.0)
    r["county"] = r["precinct_id"].str.split(" - ").str[0].str.strip().str.upper()
    r["precinct"] = r["precinct_id"].str.split(" - ").str[1].fillna("").str.strip().str.upper()
    r["bucket"] = r["precinct"].map(precinct_bucket_from_code)
    unmatched = r[~r["precinct_id"].isin(matched_precincts)].copy()
    if unmatched.empty:
        return {str(k): int(round(v)) for k, v in base.items()}

    add_frames = []
    assigned = pd.DataFrame(columns=["county", "bucket"])
    if precinct_bucket_shares is not None and not precinct_bucket_shares.empty:
        u_bucket = unmatched.groupby(["county", "bucket"], as_index=False)["votes"].sum().rename(
            columns={"votes": "unmatched_votes"}
        )
        b_alloc = u_bucket.merge(precinct_bucket_shares, on=["county", "bucket"], how="inner")
        if not b_alloc.empty:
            b_alloc["alloc_votes"] = b_alloc["unmatched_votes"] * b_alloc["share"]
            add_frames.append(b_alloc[["district", "alloc_votes"]])
            assigned = b_alloc[["county", "bucket"]].drop_duplicates()

    rem = unmatched
    if not assigned.empty:
        rem = unmatched.merge(assigned, on=["county", "bucket"], how="left", indicator=True)
        rem = rem[rem["_merge"] == "left_only"].drop(columns=["_merge"])

    if not rem.empty:
        u = rem.groupby("county", as_index=False)["votes"].sum().rename(columns={"votes": "unmatched_votes"})
        alloc = u.merge(county_shares, on="county", how="left").dropna(subset=["district", "share"]).copy()
        alloc["alloc_votes"] = alloc["unmatched_votes"] * alloc["share"]
        add_frames.append(alloc[["district", "alloc_votes"]])

    if not add_frames:
        return {str(k): int(round(v)) for k, v in base.items()}

    add = pd.concat(add_frames, ignore_index=True).groupby("district", as_index=False)["alloc_votes"].sum()
    for _, row in add.iterrows():
        dist = str(row["district"]).strip()
        base[dist] = float(base.get(dist, 0.0)) + float(row["alloc_votes"])
    return {str(k): int(round(v)) for k, v in base.items()}


def party_group(party: str) -> str:
    p = str(party).strip().upper().replace("\x00", "")
    if p == "DEM":
        return "dem_votes"
    if p == "REP":
        return "rep_votes"
    return "other_votes"


_JUDICIAL_PARTY_OVERRIDE_CACHE: dict[int, dict[str, str]] | None = None


def _norm_candidate_key(name: str) -> str:
    s = str(name or "").strip().upper().replace("\x00", "")
    s = re.sub(r"[.,]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_judicial_candidate_party_overrides(
    path: Path | None = None,
) -> dict[int, dict[str, str]]:
    """year -> {normalized candidate name -> dem_votes|rep_votes|other_votes}."""
    global _JUDICIAL_PARTY_OVERRIDE_CACHE
    if _JUDICIAL_PARTY_OVERRIDE_CACHE is not None:
        return _JUDICIAL_PARTY_OVERRIDE_CACHE

    csv_path = path or Path("data/mappings/judicial_candidate_party_overrides.csv")
    out: dict[int, dict[str, str]] = {}
    if not csv_path.exists():
        _JUDICIAL_PARTY_OVERRIDE_CACHE = out
        return out

    raw = pd.read_csv(csv_path, dtype=str).fillna("")
    for _, row in raw.iterrows():
        try:
            year = int(str(row.get("year") or "").strip())
        except Exception:
            continue
        cand = _norm_candidate_key(row.get("candidate") or "")
        party = str(row.get("party") or "").strip().upper()
        if not cand or party not in {"DEM", "REP", "OTHER"}:
            continue
        bucket = {"DEM": "dem_votes", "REP": "rep_votes", "OTHER": "other_votes"}[party]
        out.setdefault(year, {})[cand] = bucket

    _JUDICIAL_PARTY_OVERRIDE_CACHE = out
    return out


def apply_candidate_party_overrides(df: pd.DataFrame, election_year: int | None = None) -> pd.DataFrame:
    """
    Targeted overrides where ballot-party labels are missing/wrong for DEM/REP margins.

    - 2018: Anglin (Supreme Court) -> other
    - Pre-2018 (and 2016 SC): judicial candidate lean map from
      data/mappings/judicial_candidate_party_overrides.csv
    """
    out = df.copy()
    if out.empty:
        return out

    y = None
    try:
        if election_year is not None:
            y = int(election_year)
    except Exception:
        y = None

    if y == 2018:
        cand = out["candidate"].astype(str).str.upper()
        office = out["office"].astype(str).str.upper()
        # Chris/Christopher Anglin in NC Supreme Court race should roll into Other.
        mask = cand.str.contains(r"\bANGLIN\b", regex=True, na=False) & office.str.contains("SUPREME COURT", na=False)
        out.loc[mask, "party_group"] = "other_votes"

    if y is not None:
        lean_map = load_judicial_candidate_party_overrides().get(y) or {}
        if lean_map:
            office_u = out["office"].astype(str).str.upper()
            judicial = office_u.str.contains(r"SUPREME COURT|COURT OF APPEALS", regex=True, na=False)
            if judicial.any():
                keys = out.loc[judicial, "candidate"].map(_norm_candidate_key)
                mapped = keys.map(lean_map)
                hit = judicial & mapped.notna()
                out.loc[hit, "party_group"] = mapped.loc[hit].astype(str)

    return out


def allocate_non_geo_by_candidate(
    df_office: pd.DataFrame, precinct_overrides: dict[str, str] | None = None
) -> pd.DataFrame:
    """
    Returns rows at county+precinct+candidate with votes after non-geo allocation.
    """
    df = df_office.copy()
    df["votes"] = pd.to_numeric(df["votes"], errors="coerce").fillna(0.0)
    df["county"] = df["county"].astype(str).str.strip().str.upper()
    df["precinct"] = df["precinct"].astype(str).str.strip().str.upper()
    df["candidate"] = df["candidate"].astype(str).str.strip()
    df["precinct_id"] = df["county"] + " - " + df["precinct"]
    df = apply_precinct_overrides(df, precinct_overrides)
    df["non_geo"] = df.apply(
        lambda r: is_non_geographic_precinct(str(r.get("precinct", "")), str(r.get("county", ""))),
        axis=1,
    )

    geo = df[~df["non_geo"]].copy()
    non_geo = df[df["non_geo"]].copy()
    if non_geo.empty:
        return geo.groupby(["county", "precinct_id", "candidate"], as_index=False)["votes"].sum()

    geo_cand = geo.groupby(["county", "candidate", "precinct_id"], as_index=False)["votes"].sum()
    cand_den = geo_cand.groupby(["county", "candidate"], as_index=False)["votes"].sum().rename(
        columns={"votes": "cand_geo_total"}
    )
    non_geo_cand = non_geo.groupby(["county", "candidate"], as_index=False)["votes"].sum().rename(
        columns={"votes": "non_geo_votes"}
    )

    alloc = geo_cand.merge(cand_den, on=["county", "candidate"], how="left").merge(
        non_geo_cand, on=["county", "candidate"], how="left"
    )
    alloc["non_geo_votes"] = alloc["non_geo_votes"].fillna(0.0)
    alloc["alloc"] = 0.0
    ok = alloc["cand_geo_total"] > 0
    alloc.loc[ok, "alloc"] = alloc.loc[ok, "non_geo_votes"] * (
        alloc.loc[ok, "votes"] / alloc.loc[ok, "cand_geo_total"]
    )

    miss = non_geo_cand.merge(cand_den, on=["county", "candidate"], how="left")
    miss = miss[(miss["cand_geo_total"].isna()) & (miss["non_geo_votes"] > 0)].copy()
    if not miss.empty:
        county_geo = geo.groupby(["county", "precinct_id"], as_index=False)["votes"].sum()
        county_den = county_geo.groupby("county", as_index=False)["votes"].sum().rename(columns={"votes": "county_geo_total"})
        cshare = county_geo.merge(county_den, on="county", how="left")
        cshare["share"] = cshare["votes"] / cshare["county_geo_total"]
        miss_alloc = miss.merge(cshare[["county", "precinct_id", "share"]], on="county", how="left")
        miss_alloc["alloc"] = miss_alloc["non_geo_votes"] * miss_alloc["share"].fillna(0.0)
        alloc_extra = miss_alloc.groupby(["county", "precinct_id"], as_index=False)["alloc"].sum()
    else:
        alloc_extra = pd.DataFrame(columns=["county", "precinct_id", "alloc"])

    alloc_main = alloc.groupby(["county", "precinct_id"], as_index=False)["alloc"].sum()
    alloc_all = pd.concat([alloc_main, alloc_extra], ignore_index=True).groupby(
        ["county", "precinct_id"], as_index=False
    )["alloc"].sum()

    geo_tot = geo.groupby(["county", "precinct_id", "candidate"], as_index=False)["votes"].sum()
    # Add candidate-specific allocation where available.
    merged = geo_tot.merge(alloc[["county", "precinct_id", "candidate", "alloc"]], on=["county", "precinct_id", "candidate"], how="left")
    merged["alloc"] = merged["alloc"].fillna(0.0)
    merged["votes"] = merged["votes"] + merged["alloc"]

    # County-level fallback allocations were candidate-agnostic; distribute proportionally
    # across candidates in each precinct by existing geo candidate shares.
    if not alloc_extra.empty:
        p_cand = merged.groupby(["county", "precinct_id", "candidate"], as_index=False)["votes"].sum()
        p_tot = p_cand.groupby(["county", "precinct_id"], as_index=False)["votes"].sum().rename(columns={"votes": "p_total"})
        p_share = p_cand.merge(p_tot, on=["county", "precinct_id"], how="left")
        p_share["share"] = p_share["votes"] / p_share["p_total"]
        add = alloc_extra.merge(p_share[["county", "precinct_id", "candidate", "share"]], on=["county", "precinct_id"], how="left")
        add["votes_add"] = add["alloc"] * add["share"].fillna(0.0)
        add = add.groupby(["county", "precinct_id", "candidate"], as_index=False)["votes_add"].sum()
        merged = merged.merge(add, on=["county", "precinct_id", "candidate"], how="left")
        merged["votes_add"] = merged["votes_add"].fillna(0.0)
        merged["votes"] = merged["votes"] + merged["votes_add"]

    return merged[["county", "precinct_id", "candidate", "votes"]]


def build_precinct_party_votes(
    src: pd.DataFrame, office: str, precinct_overrides: dict[str, str] | None = None, election_year: int | None = None
) -> tuple[pd.DataFrame, str, str]:
    df = src[src["office"] == office].copy()
    if df.empty:
        return pd.DataFrame(columns=["precinct_id", "dem_votes", "rep_votes", "other_votes"]), "", ""
    df["votes_num"] = pd.to_numeric(df["votes"], errors="coerce").fillna(0.0)
    df["party_group"] = df["party"].map(party_group)
    df = apply_candidate_party_overrides(df, election_year=election_year)
    df["candidate"] = df["candidate"].map(canonicalize_candidate_label)

    # Candidate labels (statewide top by party).
    dem_c = (
        df[df["party_group"] == "dem_votes"]
        .groupby("candidate", as_index=False)["votes_num"]
        .sum()
        .sort_values("votes_num", ascending=False)
    )
    rep_c = (
        df[df["party_group"] == "rep_votes"]
        .groupby("candidate", as_index=False)["votes_num"]
        .sum()
        .sort_values("votes_num", ascending=False)
    )
    dem_candidate = str(dem_c["candidate"].iloc[0]) if not dem_c.empty else ""
    rep_candidate = str(rep_c["candidate"].iloc[0]) if not rep_c.empty else ""
    if infer_office_key(office) == PRESIDENT_OFFICE_KEY:
        dem_candidate = normalize_presidential_candidate_name(dem_candidate)
        rep_candidate = normalize_presidential_candidate_name(rep_candidate)
    dem_candidate = canonicalize_candidate_label(dem_candidate)
    rep_candidate = canonicalize_candidate_label(rep_candidate)

    # Normalize precinct IDs before allocation/matching.
    df["county"] = df["county"].astype(str).str.strip().str.upper()
    df["precinct"] = df["precinct"].astype(str).str.strip().str.upper()
    df["precinct_id"] = df["county"] + " - " + df["precinct"]
    df = apply_precinct_overrides(df, precinct_overrides)
    allocated = allocate_non_geo_by_candidate(df, precinct_overrides=precinct_overrides)
    # Attach party via candidate+office+county lookup (candidate names are unique enough per office).
    party_lookup = (
        df[["candidate", "party_group"]]
        .drop_duplicates(subset=["candidate"], keep="first")
        .set_index("candidate")["party_group"]
        .to_dict()
    )
    allocated["party_group"] = allocated["candidate"].map(lambda c: party_lookup.get(c, "other_votes"))
    p = allocated.groupby(["precinct_id", "party_group"], as_index=False)["votes"].sum()
    wide = p.pivot(index="precinct_id", columns="party_group", values="votes").fillna(0.0).reset_index()
    for col in ["dem_votes", "rep_votes", "other_votes"]:
        if col not in wide.columns:
            wide[col] = 0.0
    return wide[["precinct_id", "dem_votes", "rep_votes", "other_votes"]], dem_candidate, rep_candidate


def build_precinct_party_votes_county_weight_mode(
    src: pd.DataFrame, office: str, precinct_overrides: dict[str, str] | None = None, election_year: int | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, str, str]:
    df = src[src["office"] == office].copy()
    if df.empty:
        empty_p = pd.DataFrame(columns=["precinct_id", "dem_votes", "rep_votes", "other_votes"])
        empty_c = pd.DataFrame(columns=["county", "party_group", "votes"])
        return empty_p, empty_c, "", ""

    df["votes_num"] = pd.to_numeric(df["votes"], errors="coerce").fillna(0.0)
    df["party_group"] = df["party"].map(party_group)
    df = apply_candidate_party_overrides(df, election_year=election_year)
    df["candidate"] = df["candidate"].map(canonicalize_candidate_label)
    df["county"] = df["county"].astype(str).str.strip().str.upper()
    df["precinct"] = df["precinct"].astype(str).str.strip().str.upper()
    df["precinct_id"] = df["county"] + " - " + df["precinct"]
    df = apply_precinct_overrides(df, precinct_overrides)
    df["non_geo"] = df.apply(
        lambda r: is_non_geographic_precinct(str(r.get("precinct", "")), str(r.get("county", ""))),
        axis=1,
    )

    dem_c = (
        df[df["party_group"] == "dem_votes"]
        .groupby("candidate", as_index=False)["votes_num"]
        .sum()
        .sort_values("votes_num", ascending=False)
    )
    rep_c = (
        df[df["party_group"] == "rep_votes"]
        .groupby("candidate", as_index=False)["votes_num"]
        .sum()
        .sort_values("votes_num", ascending=False)
    )
    dem_candidate = str(dem_c["candidate"].iloc[0]) if not dem_c.empty else ""
    rep_candidate = str(rep_c["candidate"].iloc[0]) if not rep_c.empty else ""
    if infer_office_key(office) == PRESIDENT_OFFICE_KEY:
        dem_candidate = normalize_presidential_candidate_name(dem_candidate)
        rep_candidate = normalize_presidential_candidate_name(rep_candidate)
    dem_candidate = canonicalize_candidate_label(dem_candidate)
    rep_candidate = canonicalize_candidate_label(rep_candidate)

    geo = df[~df["non_geo"]].copy()
    non_geo = df[df["non_geo"]].copy()

    p = geo.groupby(["precinct_id", "party_group"], as_index=False)["votes_num"].sum()
    wide = p.pivot(index="precinct_id", columns="party_group", values="votes_num").fillna(0.0).reset_index()
    for col in ["dem_votes", "rep_votes", "other_votes"]:
        if col not in wide.columns:
            wide[col] = 0.0

    county_non_geo = non_geo.groupby(["county", "party_group"], as_index=False)["votes_num"].sum()
    county_non_geo.columns = ["county", "party_group", "votes"]
    return wide[["precinct_id", "dem_votes", "rep_votes", "other_votes"]], county_non_geo, dem_candidate, rep_candidate


def to_results_df(p: pd.DataFrame, col: str) -> pd.DataFrame:
    out = p[["precinct_id", col]].copy()
    out.columns = ["precinct_id", "votes"]
    out["votes"] = out["votes"].map(lambda v: Decimal(str(v)))
    return out


def agg_party_to_scope(
    precinct_party: pd.DataFrame,
    crosswalk_df: pd.DataFrame,
    vap_df: pd.DataFrame,
    map_path: Path,
    block_col: str,
    district_col: str,
    county_shares: pd.DataFrame,
    precinct_bucket_shares: pd.DataFrame,
    matched_precincts: set[str],
    county_non_geo_party: pd.DataFrame | None = None,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], int, int]:
    def _alloc_all_votes_by_bucket_then_county(res_df: pd.DataFrame) -> dict[str, int]:
        """
        Fallback when zero precinct keys match the block->precinct crosswalk.

        Allocates votes to districts using:
        1) county+bucket -> district shares (bucket derived from precinct code like '01-07A' => '01-07')
        2) remaining county totals -> district shares (county-wide VAP shares)

        This preserves within-county variation at the "precinct bucket" level without requiring
        any matched precinct IDs.
        """
        r = res_df.copy()
        r["precinct_id"] = r["precinct_id"].astype(str).str.strip().str.upper()
        r["votes"] = pd.to_numeric(r["votes"], errors="coerce").fillna(0.0)
        r["county"] = r["precinct_id"].str.split(" - ").str[0].str.strip().str.upper()
        r["precinct"] = r["precinct_id"].str.split(" - ").str[1].fillna("").str.strip().str.upper()
        r["bucket"] = r["precinct"].map(precinct_bucket_from_code)
        r = r[(r["county"] != "") & (r["votes"] != 0)].copy()
        if r.empty:
            return {}

        add_frames = []
        assigned = pd.DataFrame(columns=["county", "bucket"])

        # Bucket allocation where we have shares.
        u_bucket = r.groupby(["county", "bucket"], as_index=False)["votes"].sum().rename(columns={"votes": "unmatched_votes"})
        b_alloc = u_bucket.merge(precinct_bucket_shares, on=["county", "bucket"], how="inner")
        if not b_alloc.empty:
            b_alloc["alloc_votes"] = b_alloc["unmatched_votes"] * b_alloc["share"]
            add_frames.append(b_alloc[["district", "alloc_votes"]])
            assigned = b_alloc[["county", "bucket"]].drop_duplicates()

        # Remaining county totals (buckets with no shares) fall back to county-wide shares.
        rem = u_bucket
        if not assigned.empty:
            rem = u_bucket.merge(assigned, on=["county", "bucket"], how="left", indicator=True)
            rem = rem[rem["_merge"] == "left_only"].drop(columns=["_merge"])
        if not rem.empty:
            u = rem.groupby("county", as_index=False)["unmatched_votes"].sum().rename(columns={"unmatched_votes": "votes"})
            alloc = u.merge(county_shares, on="county", how="left").dropna(subset=["district", "share"]).copy()
            alloc["alloc_votes"] = alloc["votes"] * alloc["share"]
            add_frames.append(alloc[["district", "alloc_votes"]])

        if not add_frames:
            return {}

        add = pd.concat(add_frames, ignore_index=True).groupby("district", as_index=False)["alloc_votes"].sum()
        return {str(row["district"]).strip(): int(round(float(row["alloc_votes"]))) for _, row in add.iterrows()}

    party_district = {}
    matched = 0
    total = int(len(precinct_party))

    # If nothing matches the precinct crosswalk, skip VAP-shatter and do a pure share-based allocation.
    precinct_ids = precinct_party["precinct_id"].astype(str).str.strip().str.upper()
    if int(precinct_ids.isin(matched_precincts).sum()) == 0:
        for col in ["dem_votes", "rep_votes", "other_votes"]:
            res_df = to_results_df(precinct_party, col)
            party_district[col] = _alloc_all_votes_by_bucket_then_county(res_df)
        return (
            party_district.get("dem_votes", {}),
            party_district.get("rep_votes", {}),
            party_district.get("other_votes", {}),
            0,
            total,
        )

    for col in ["dem_votes", "rep_votes", "other_votes"]:
        res_df = to_results_df(precinct_party, col)
        shattered, audit = shatter_votes(
            results_df=res_df,
            crosswalk_df=crosswalk_df,
            vap_df=vap_df,
            precision=28,
        )
        matched = max(matched, int(len(audit)))
        agg = aggregate_to_districts(shattered, map_path, block_col, district_col)
        party_district[col] = apply_unmatched_county_fallback(
            district_df=agg,
            results_df=res_df,
            matched_precincts=matched_precincts,
            county_shares=county_shares,
            precinct_bucket_shares=precinct_bucket_shares,
        )

        if county_non_geo_party is not None and not county_non_geo_party.empty:
            add_src = county_non_geo_party[county_non_geo_party["party_group"] == col][["county", "votes"]].copy()
            if not add_src.empty:
                add = add_src.merge(county_shares, on="county", how="left").dropna(subset=["district", "share"]).copy()
                add["alloc_votes"] = pd.to_numeric(add["votes"], errors="coerce").fillna(0.0) * pd.to_numeric(
                    add["share"], errors="coerce"
                ).fillna(0.0)
                add = add.groupby("district", as_index=False)["alloc_votes"].sum()
                base = {k: float(v) for k, v in party_district[col].items()}
                for _, row in add.iterrows():
                    d = str(row["district"]).strip()
                    base[d] = float(base.get(d, 0.0)) + float(row["alloc_votes"])
                party_district[col] = {str(k): int(round(v)) for k, v in base.items()}
    return (
        party_district["dem_votes"],
        party_district["rep_votes"],
        party_district["other_votes"],
        matched,
        total,
    )


def load_sbe2006_district_weights(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def select_sbe2006_district_weight_scopes(
    payload: dict,
    *,
    weight_set: str,
    allocation_year: int,
    cd_file: Path,
) -> dict[str, dict]:
    if not payload:
        return {}
    if weight_set == "none":
        return {}
    selected = weight_set
    if selected == "auto":
        cd_text = str(cd_file).lower()
        if allocation_year >= 2026 or "2026" in cd_text or "sl2025" in cd_text:
            selected = "2026"
        elif allocation_year >= 2024:
            selected = "2024"
        else:
            selected = "2022"

    scope_sets = payload.get("scope_sets") or {}
    scope_names = scope_sets.get(str(selected)) or {}
    scopes = payload.get("scopes") or {}
    out: dict[str, dict] = {}
    for district_type in ("state_house", "state_senate", "congressional"):
        scope_name = scope_names.get(district_type)
        scope = scopes.get(scope_name) if scope_name else None
        if isinstance(scope, dict) and scope.get("precincts"):
            out[district_type] = scope
    return out


def build_sbe2006_weight_alias_lookup(precinct_ids: set[str]) -> dict[str, str]:
    """Resolve OE/SBE2006 spelling variants to unique district-weight precinct keys."""
    candidates: dict[str, set[str]] = {}

    def add(alias: str, canonical: str) -> None:
        alias = _norm_spaces(alias)
        canonical = _norm_spaces(canonical)
        if alias and canonical:
            candidates.setdefault(alias, set()).add(canonical)

    for canonical in precinct_ids:
        canonical = _norm_spaces(canonical)
        for alias in sbe2006_precinct_key_aliases(canonical):
            add(alias, canonical)
            add(_compact_token(alias), canonical)

    # Keep only unambiguous aliases. Exact canonical keys are always safe.
    lookup: dict[str, str] = {}
    for alias, matches in candidates.items():
        if alias in precinct_ids:
            lookup[alias] = alias
        elif len(matches) == 1:
            lookup[alias] = next(iter(matches))
    return lookup


def sbe2006_precinct_key_aliases(precinct_id: str) -> set[str]:
    """Generate conservative one-to-one candidate aliases for a SBE2006 precinct key."""
    key = _norm_spaces(precinct_id)
    out = {key} if key else set()
    if " - " not in key:
        return out

    county, precinct = key.split(" - ", 1)
    variants = {precinct}
    no_hash = _norm_spaces(precinct.replace("#", " "))
    variants.add(no_hash)
    variants.update(legacy_abbreviation_aliases_for_name(county, precinct))

    # Polling-place suffixes: "01.1 - SITE" / "001 - SITE" -> "01.1" / "001".
    if " - " in precinct:
        variants.add(_norm_spaces(precinct.split(" - ", 1)[0]))
    m = re.match(r"^([A-Z]*0*\d+[A-Z]?(?:\.\d+)?)(?:\s+-\s+|\s+)", precinct)
    if m:
        variants.add(_norm_spaces(m.group(1)))

    # Cumberland-style group suffixes and Davidson-style numeric suffixes.
    variants.add(_norm_spaces(re.sub(r"\s*-\s*G\d+[A-Z]?$", "", precinct)))
    variants.add(_norm_spaces(re.sub(r"\s+#\s*\d+[A-Z]?$", "", precinct)))

    # Leading-zero variants: "BURLINGTON 04" <-> "BURLINGTON 4"; "001" -> "1".
    variants.add(
        _norm_spaces(
            re.sub(
                r"\b0+(\d+)([A-Z]?)\b",
                lambda m: f"{int(m.group(1))}{m.group(2)}",
                precinct,
            )
        )
    )
    variants.add(
        _norm_spaces(
            re.sub(
                r"\b(\d{1})([A-Z]?)\b",
                lambda m: f"0{m.group(1)}{m.group(2)}",
                precinct,
            )
        )
    )
    variants.add(
        _norm_spaces(
            re.sub(
                r"\b0*(\d{1,2})([A-Z]?)\b",
                lambda m: f"{int(m.group(1)):02d}{m.group(2)}",
                precinct,
            )
        )
    )

    # Directional aliases: "BANNER NORTH" <-> "NORTH BANNER".
    directions = {"NORTH", "SOUTH", "EAST", "WEST", "NORTHEAST", "NORTHWEST", "SOUTHEAST", "SOUTHWEST"}
    parts = precinct.split()
    if len(parts) >= 2 and parts[0] in directions:
        variants.add(_norm_spaces(" ".join([*parts[1:], parts[0]])))
    if len(parts) >= 2 and parts[-1] in directions:
        variants.add(_norm_spaces(" ".join([parts[-1], *parts[:-1]])))

    for variant in list(variants):
        if not variant:
            continue
        out.add(f"{county} - {variant}")
        cleaned = clean_precinct_name(variant, county)
        if cleaned:
            out.add(f"{county} - {cleaned}")
    return {x for x in out if x}


def aggregate_precinct_party_with_district_weights(
    precinct_party: pd.DataFrame,
    scope_weights: dict,
    *,
    county_shares: pd.DataFrame | None = None,
    county_non_geo_party: pd.DataFrame | None = None,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], int, int]:
    """Aggregate precinct party totals directly through SBE2006->district weights."""
    precincts = {
        str(k).strip().upper(): v
        for k, v in (scope_weights.get("precincts") or {}).items()
        if isinstance(v, list)
    }
    total = int(len(precinct_party))
    matched_ids = set(precincts)
    alias_lookup = build_sbe2006_weight_alias_lookup(matched_ids)

    def resolve_precinct_id(precinct_id: str) -> str | None:
        key = _norm_spaces(precinct_id)
        for alias in sbe2006_precinct_key_aliases(key):
            if alias in precincts:
                return alias
            hit = alias_lookup.get(alias) or alias_lookup.get(_compact_token(alias))
            if hit:
                return hit
        return None

    resolved_keys = precinct_party["precinct_id"].astype(str).map(resolve_precinct_id)
    matched = int(resolved_keys.notna().sum())

    def _round_map(raw: dict[str, float]) -> dict[str, int]:
        return {str(k): int(round(float(v))) for k, v in raw.items() if abs(float(v)) > 0}

    def _aggregate_col(col: str) -> dict[str, int]:
        base: dict[str, float] = {}
        rows = precinct_party[["precinct_id", col]].copy()
        rows["precinct_id"] = rows["precinct_id"].astype(str).map(_norm_spaces)
        rows["resolved_precinct_id"] = rows["precinct_id"].map(resolve_precinct_id)
        rows["votes"] = pd.to_numeric(rows[col], errors="coerce").fillna(0.0)
        rows = rows[rows["votes"] != 0].copy()

        for r in rows.itertuples(index=False):
            precinct_id = str(r.resolved_precinct_id or "")
            votes = float(r.votes)
            entries = precincts.get(precinct_id)
            if entries:
                for entry in entries:
                    district = str((entry or {}).get("district", "")).strip().lstrip("0") or "0"
                    share = float((entry or {}).get("share") or 0.0)
                    if district and share > 0:
                        base[district] = base.get(district, 0.0) + votes * share
                continue

        if county_shares is not None and not county_shares.empty:
            unmatched = rows[rows["resolved_precinct_id"].isna()].copy()
            if not unmatched.empty:
                unmatched["county"] = unmatched["precinct_id"].str.split(" - ").str[0].str.strip().str.upper()
                u = unmatched.groupby("county", as_index=False)["votes"].sum()
                alloc = u.merge(county_shares, on="county", how="left").dropna(subset=["district", "share"]).copy()
                if not alloc.empty:
                    alloc["alloc_votes"] = pd.to_numeric(alloc["votes"], errors="coerce").fillna(0.0) * pd.to_numeric(
                        alloc["share"], errors="coerce"
                    ).fillna(0.0)
                    for ar in alloc.itertuples(index=False):
                        district = str(ar.district).strip().lstrip("0") or "0"
                        base[district] = base.get(district, 0.0) + float(ar.alloc_votes)

        return _round_map(base)

    party_district = {col: _aggregate_col(col) for col in ["dem_votes", "rep_votes", "other_votes"]}

    if county_non_geo_party is not None and not county_non_geo_party.empty and county_shares is not None:
        for col in ["dem_votes", "rep_votes", "other_votes"]:
            add_src = county_non_geo_party[county_non_geo_party["party_group"] == col][["county", "votes"]].copy()
            if add_src.empty:
                continue
            add = add_src.merge(county_shares, on="county", how="left").dropna(subset=["district", "share"]).copy()
            add["alloc_votes"] = pd.to_numeric(add["votes"], errors="coerce").fillna(0.0) * pd.to_numeric(
                add["share"], errors="coerce"
            ).fillna(0.0)
            base = {k: float(v) for k, v in party_district[col].items()}
            for ar in add.itertuples(index=False):
                district = str(ar.district).strip().lstrip("0") or "0"
                base[district] = base.get(district, 0.0) + float(ar.alloc_votes)
            party_district[col] = _round_map(base)

    return (
        party_district["dem_votes"],
        party_district["rep_votes"],
        party_district["other_votes"],
        matched,
        total,
    )


def build_payload(
    *,
    year: int,
    scope: str,
    contest_type: str,
    office_label: str,
    nongeo_allocation_mode: str,
    dem_map: dict[str, int],
    rep_map: dict[str, int],
    oth_map: dict[str, int],
    dem_candidate: str,
    rep_candidate: str,
    matched: int,
    total: int,
    match_crosswalk: str | None = None,
    target_crosswalk: str | None = None,
    district_weights_json: str | None = None,
    district_weight_plan: str | None = None,
    district_lines_year: int | None = None,
    district_lines_label: str | None = None,
) -> dict:
    keys = sorted(set(dem_map) | set(rep_map) | set(oth_map), key=lambda x: (int(x) if str(x).isdigit() else x))
    results = {}
    for k in keys:
        dem = int(dem_map.get(k, 0))
        rep = int(rep_map.get(k, 0))
        oth = int(oth_map.get(k, 0))
        total_votes = dem + rep + oth
        margin = rep - dem
        margin_pct = (margin / total_votes * 100.0) if total_votes else 0.0
        winner = "REP" if margin > 0 else "DEM" if margin < 0 else "TIE"
        results[str(k)] = {
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
    cov = (matched / total * 100.0) if total else 0.0
    meta = {
        "match_coverage_pct": round(cov, 2),
        "matched_precinct_keys": int(matched),
        "total_precinct_keys": int(total),
        "source": "batch_shatter_vap_party_split",
        "office": office_label,
        "nongeo_allocation_mode": nongeo_allocation_mode,
    }
    if match_crosswalk:
        meta["match_crosswalk"] = match_crosswalk
    if target_crosswalk:
        meta["target_crosswalk"] = target_crosswalk
    if district_weights_json:
        meta["district_weights_json"] = district_weights_json
    if district_weight_plan:
        meta["district_weight_plan"] = district_weight_plan
    if district_lines_year is not None:
        meta["district_lines_year"] = int(district_lines_year)
    if district_lines_label:
        meta["district_lines_label"] = district_lines_label
    return {
        "year": year,
        "scope": scope,
        "contest_type": contest_type,
        "meta": meta,
        "general": {"results": results},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build district contest slices with true party split.")
    parser.add_argument("--batch-dir", type=Path, default=Path("data/tmp/shatter/batch_2024_council_judicial_overlay_test"))
    parser.add_argument("--results-csv", type=Path, default=Path("data/2024/20241105__nc__general__precinct.csv"))
    parser.add_argument("--district-contests-dir", type=Path, default=Path("data/district_contests"))
    parser.add_argument(
        "--crosswalk-csv",
        type=Path,
        default=Path("data/crosswalks/block20_to_onemap_2025_12.csv"),
        help="Fallback / explicit block→precinct map. Ignored for matching when --auto-vintage-match is on.",
    )
    parser.add_argument(
        "--auto-vintage-match",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Select block→precinct match map by election year "
            "(VTD00 / SBE2012 / SBE2016 / SBE2020 / OneMap2025). Default: on."
        ),
    )
    parser.add_argument(
        "--match-crosswalk-csv",
        type=Path,
        default=None,
        help="Optional explicit match/shatter map (overrides --auto-vintage-match).",
    )
    parser.add_argument(
        "--contest-display-crosswalk-csv",
        type=Path,
        default=None,
        help=(
            "Optional SBE precinct -> modern OneMap precinct bridge used only for precinct contest display rows. "
            "Pass this explicitly for a chosen modern target basis."
        ),
    )
    parser.add_argument("--vap-csv", type=Path, default=Path("data/census/block_vap_2020_nc.csv"))
    parser.add_argument("--house-file", type=Path, default=Path("data/tmp/block_assign_extract/SL 2022-4.csv"))
    parser.add_argument("--senate-file", type=Path, default=Path("data/tmp/block_assign_extract/SL 2022-2.csv"))
    parser.add_argument("--cd-file", type=Path, default=Path("data/census/block files/NC_CD118.txt"))
    parser.add_argument("--allocation-weights-json", type=Path, default=Path("data/mappings/allocation_weights.json"))
    parser.add_argument(
        "--sbe2006-district-weights-json",
        type=Path,
        default=Path("data/mappings/sbe2006_to_modern_district_weights.json"),
        help="Optional SBE2006 precinct -> modern district weights for early-era district overlays.",
    )
    parser.add_argument(
        "--sbe2006-district-weight-set",
        choices=["auto", "none", "2022", "2024", "2026"],
        default="auto",
        help="District weight scope set for SBE2006-era overlays. Auto follows allocation year / CD file.",
    )
    parser.add_argument(
        "--district-lines-year",
        type=int,
        choices=[2022, 2024, 2026],
        default=None,
        help="District line set recorded in output provenance metadata.",
    )
    parser.add_argument(
        "--district-lines-label",
        type=str,
        default="",
        help="Optional human-readable district line-set label for output provenance metadata.",
    )
    parser.add_argument(
        "--emit-scopes",
        type=str,
        default="state_house,state_senate,congressional",
        help="Comma-separated district scopes to write (default: all scopes).",
    )
    parser.add_argument("--precinct-overrides-csv", type=Path, default=Path("data/mappings/precinct_key_overrides.csv"))
    parser.add_argument(
        "--allocation-year",
        type=int,
        default=2022,
        help="Use this year key in allocation_weights.json (defaults to 2022 for SL 2022 district overlays).",
    )
    parser.add_argument(
        "--min-county-share",
        type=float,
        default=0.01,
        help="Drop override shares below this threshold and renormalize (e.g., 0.01 => 1%% sliver fallback).",
    )
    parser.add_argument(
        "--nongeo-allocation-mode",
        choices=["precinct_candidate", "county_weights"],
        default="precinct_candidate",
        help="Allocate non-geographic votes by precinct candidate shares (default) or county->district weights.",
    )
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument(
        "--sbe-precincts-2006-shp",
        type=Path,
        default=Path("data/Precincts2006Gen/Precincts2006Gen.shp"),
        help="Optional NCSBE precinct shapefile path (2006-era) for Precinct/SEIMS_Code aliases.",
    )
    parser.add_argument(
        "--sbe-precincts-2012-shp",
        type=Path,
        default=Path("data/census/SBE_PRECINCTS_20120901/SBE_PRECINCTS_09012012.shp"),
        help="Optional NCSBE precinct shapefile path (2012-era) for ENR_DESC->PREC_ID aliases.",
    )
    parser.add_argument(
        "--sbe-precincts-2014-shp",
        type=Path,
        default=Path("data/census/SBE_PRECINCTS_20141016/PRECINCTS.shp"),
        help="Optional NCSBE precinct shapefile path (2014-era) for ENR_DESC->PREC_ID aliases.",
    )
    parser.add_argument(
        "--sbe-precincts-2020-shp",
        type=Path,
        default=Path("data/census/SBE_PRECINCTS_20201018/SBE_PRECINCTS_20201018.shp"),
        help="Optional NCSBE precinct shapefile path (2020-era) for ENR_DESC->PREC_ID aliases.",
    )
    parser.add_argument(
        "--sbe-precincts-2022-shp",
        type=Path,
        default=Path("data/census/SBE_PRECINCTS_20220118/SBE_PRECINCTS_20220118.shp"),
        help="Optional NCSBE precinct shapefile path (2022-era) for ENR_DESC->PREC_ID aliases.",
    )
    parser.add_argument(
        "--sbe-precincts-2024-shp",
        type=Path,
        default=Path("data/census/SBE_PRECINCTS_20240723/SBE_PRECINCTS_20240723.shp"),
        help="Optional NCSBE precinct shapefile path (2024-era) for ENR_DESC->PREC_ID aliases.",
    )
    parser.add_argument(
        "--office-source",
        choices=["summary", "auto"],
        default="summary",
        help="Use batch summary office->key mapping, or infer from results CSV using KNOWN_OFFICE_KEYS.",
    )
    parser.add_argument(
        "--contest-type-regex",
        type=str,
        default="",
        help="Optional regex to filter derived contest_type keys (e.g. '^president$' or '^nc_').",
    )
    parser.add_argument(
        "--contests-only",
        action="store_true",
        help="Only write precinct-level contest slices (skip VAP shatter + district aggregation).",
    )
    parser.add_argument(
        "--write-contests",
        action="store_true",
        help="Also write precinct-level contest slices to data/contests (enables county view for judicial, etc).",
    )
    parser.add_argument("--contests-dir", type=Path, default=Path("data/contests"))
    parser.add_argument("--contests-manifest", type=Path, default=Path("data/contests/manifest.json"))
    parser.add_argument(
        "--contests-only-missing",
        action="store_true",
        help="When writing contests, only create files that do not already exist.",
    )
    args = parser.parse_args()
    if args.district_lines_year is not None:
        district_lines_year = int(args.district_lines_year)
    elif int(args.allocation_year) in {2022, 2024, 2026}:
        district_lines_year = int(args.allocation_year)
    else:
        district_lines_year = 2022
    district_lines_label = str(args.district_lines_label or f"{district_lines_year} lines").strip()
    emit_scopes = {
        token.strip()
        for token in str(args.emit_scopes or "").split(",")
        if token.strip()
    }
    valid_emit_scopes = {"state_house", "state_senate", "congressional"}
    invalid_emit_scopes = sorted(emit_scopes - valid_emit_scopes)
    if invalid_emit_scopes:
        raise ValueError(f"Invalid --emit-scopes values: {', '.join(invalid_emit_scopes)}")
    if not emit_scopes:
        emit_scopes = set(valid_emit_scopes)

    # Load the closest-available SBE precinct name->code alias map and attach it
    # to the cleaning/override helpers.
    sbe_map: dict[tuple[str, str], str] = {}
    y = int(args.year)
    # Choose the most appropriate SBE precinct file for a given election year.
    # Using a far-off vintage can produce bad "matches" in urban counties where
    # precinct naming/codes shift over time.
    if y <= 2010:
        shp = Path(args.sbe_precincts_2006_shp)
    elif y <= 2012:
        shp = Path(args.sbe_precincts_2012_shp)
    elif y <= 2017:
        shp = Path(args.sbe_precincts_2014_shp)
    elif y <= 2021:
        shp = Path(args.sbe_precincts_2020_shp)
    elif y <= 2023:
        shp = Path(args.sbe_precincts_2022_shp)
    else:
        shp = Path(args.sbe_precincts_2024_shp)
    sbe_map = load_sbe_precinct_code_map(shp)
    clean_precinct_name._sbe_map = sbe_map  # type: ignore[attr-defined]
    build_auto_precinct_overrides._sbe_map = sbe_map  # type: ignore[attr-defined]

    src = pd.read_csv(args.results_csv, dtype=str, low_memory=False)

    if args.match_crosswalk_csv is not None:
        match_crosswalk_path = Path(args.match_crosswalk_csv)
    elif args.auto_vintage_match:
        match_crosswalk_path = resolve_vintage_match_crosswalk(
            int(args.year), fallback=Path(args.crosswalk_csv)
        )
    else:
        match_crosswalk_path = Path(args.crosswalk_csv)
    if not match_crosswalk_path.exists():
        raise FileNotFoundError(f"Match crosswalk not found: {match_crosswalk_path}")
    print(
        f"Match/shatter crosswalk for {int(args.year)}: {match_crosswalk_path.as_posix()} "
        f"(auto_vintage_match={bool(args.auto_vintage_match)})"
    )

    crosswalk_df = load_crosswalk(match_crosswalk_path, "precinct_id", "block_geoid20")
    matched_precincts = set(crosswalk_df["precinct_id"].astype(str).str.strip().str.upper().unique())
    src_precinct_ids = (
        src["county"].astype(str).str.strip().str.upper()
        + " - "
        + src["precinct"].astype(str).str.strip().str.upper()
    )
    auto_overrides = build_auto_precinct_overrides(src_precinct_ids, matched_precincts)
    manual_overrides = load_precinct_overrides(args.precinct_overrides_csv, args.year)
    precinct_overrides = {**auto_overrides, **manual_overrides}
    # Do not remount OE keys that already exist on the vintage match/shatter map.
    # OneMap/choropleth remaps (e.g. WAKE 10-04→04-10, 12-05→12-08) move vote mass
    # across districts for every contest when applied here.
    before_n = len(precinct_overrides)
    precinct_overrides = {
        raw: can
        for raw, can in precinct_overrides.items()
        if _norm(str(raw)) not in matched_precincts
        and _norm(str(can)) in matched_precincts
        and _norm(str(raw)) != _norm(str(can))
    }
    skipped = before_n - len(precinct_overrides)
    if skipped:
        print(
            f"Skipped {skipped:,} precinct overrides that remapped keys already "
            f"present on the match map ({match_crosswalk_path.name})"
        )

    contest_display_crosswalk = (
        Path(args.contest_display_crosswalk_csv)
        if int(args.year) >= 2024 and args.contest_display_crosswalk_csv is not None
        else None
    )

    offices_to_run: list[tuple[str, str]] = []
    if args.office_source == "summary":
        batch_summary = pd.read_csv(args.batch_dir / "summary.csv", dtype=str).fillna("")
        for _, row in batch_summary.iterrows():
            office = str(row["office"]).strip()
            contest_type = str(row["office_key"]).strip()
            if office and contest_type:
                offices_to_run.append((office, contest_type))
    else:
        seen = set()
        for office in sorted(src["office"].dropna().astype(str).unique()):
            key = infer_office_key(office)
            if key and key not in seen:
                offices_to_run.append((office.strip(), key))
                seen.add(key)

    if args.contests_only:
        contests_written = 0
        for office, contest_type in offices_to_run:
            if not office or not contest_type:
                continue
            if args.contest_type_regex:
                try:
                    if not re.search(str(args.contest_type_regex), str(contest_type)):
                        continue
                except re.error:
                    pass
            if not args.write_contests:
                continue

            print(f"Processing (contests-only) {office} -> {contest_type}")
            if args.nongeo_allocation_mode == "county_weights":
                precinct_party, _, dem_candidate, rep_candidate = build_precinct_party_votes_county_weight_mode(
                    src, office, precinct_overrides=precinct_overrides, election_year=args.year
                )
            else:
                precinct_party, dem_candidate, rep_candidate = build_precinct_party_votes(
                    src, office, precinct_overrides=precinct_overrides, election_year=args.year
                )
            if precinct_party.empty:
                continue
            dem_tot = float(precinct_party["dem_votes"].sum()) if "dem_votes" in precinct_party else 0.0
            rep_tot = float(precinct_party["rep_votes"].sum()) if "rep_votes" in precinct_party else 0.0
            if dem_tot <= 0 or rep_tot <= 0:
                print(
                    f"  skip {contest_type}: not two-party contested "
                    f"(dem={dem_tot:.0f} rep={rep_tot:.0f})"
                )
                continue

            args.contests_dir.mkdir(parents=True, exist_ok=True)
            contest_file = args.contests_dir / f"{contest_type}_{int(args.year)}.json"
            payload = None
            if contest_file.exists() and args.contests_only_missing:
                try:
                    payload = json.loads(contest_file.read_text(encoding="utf-8"))
                except Exception:
                    payload = None
            else:
                display_precinct_overrides = build_contest_display_overrides(
                    precinct_party["precinct_id"],
                    contest_display_crosswalk,
                )
                if display_precinct_overrides:
                    print(
                        f"  contest display remaps for {contest_type}: "
                        f"{len(display_precinct_overrides):,} source keys -> OneMap keys"
                    )
                payload = build_precinct_contest_payload(
                    year=int(args.year),
                    contest_type=str(contest_type),
                    office_label=office,
                    nongeo_allocation_mode=str(args.nongeo_allocation_mode),
                    precinct_party=precinct_party,
                    dem_candidate=dem_candidate,
                    rep_candidate=rep_candidate,
                    display_precinct_overrides=display_precinct_overrides,
                )
                # Keep JSON pretty-printed for consistency with committed slice files and easier audit diffs.
                contest_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                contests_written += 1

            if payload is None:
                continue
            update_contests_manifest(
                args.contests_manifest,
                [
                    build_contests_manifest_entry(
                        year=int(args.year),
                        contest_type=str(contest_type),
                        file_name=contest_file.name,
                        payload=payload,
                    )
                ],
            )

        print(f"Wrote {contests_written} contest slices.")
        return

    alloc_year = int(args.allocation_year) if args.allocation_year is not None else int(args.year)
    allocation_weights = load_allocation_weights(args.allocation_weights_json)
    vap_df = load_vap(args.vap_csv, "block_geoid20", "vap_count")

    house_map = load_district_map(args.house_file, "Block", "District")
    senate_map = load_district_map(args.senate_file, "Block", "District")
    cd_map = load_district_map(args.cd_file, "GEOID", "CDFP")
    house_shares = apply_county_share_overrides(
        build_county_shares(crosswalk_df, vap_df, house_map),
        year=alloc_year,
        scope="state_house",
        allocation_weights=allocation_weights,
        min_county_share=args.min_county_share,
    )
    house_bucket_shares = build_precinct_bucket_shares(crosswalk_df, vap_df, house_map)
    senate_shares = apply_county_share_overrides(
        build_county_shares(crosswalk_df, vap_df, senate_map),
        year=alloc_year,
        scope="state_senate",
        allocation_weights=allocation_weights,
        min_county_share=args.min_county_share,
    )
    senate_bucket_shares = build_precinct_bucket_shares(crosswalk_df, vap_df, senate_map)
    cd_shares = apply_county_share_overrides(
        build_county_shares(crosswalk_df, vap_df, cd_map),
        year=alloc_year,
        scope="congressional",
        allocation_weights=allocation_weights,
        min_county_share=args.min_county_share,
    )
    cd_bucket_shares = build_precinct_bucket_shares(crosswalk_df, vap_df, cd_map)
    sbe2006_weight_scopes = {}
    if int(args.year) <= 2008 and str(args.sbe2006_district_weight_set) != "none":
        sbe2006_weight_scopes = select_sbe2006_district_weight_scopes(
            load_sbe2006_district_weights(args.sbe2006_district_weights_json),
            weight_set=str(args.sbe2006_district_weight_set),
            allocation_year=alloc_year,
            cd_file=Path(args.cd_file),
        )
        if sbe2006_weight_scopes:
            print(
                "SBE2006 district chain scopes: "
                + ", ".join(f"{k}={v.get('plan_id', '')}" for k, v in sorted(sbe2006_weight_scopes.items()))
            )

    out_dir = args.district_contests_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0

    for office, contest_type in offices_to_run:
        if not office or not contest_type:
            continue
        if args.contest_type_regex:
            try:
                if not re.search(str(args.contest_type_regex), str(contest_type)):
                    continue
            except re.error:
                pass
        print(f"Processing {office} -> {contest_type}")
        if args.nongeo_allocation_mode == "county_weights":
            precinct_party, county_non_geo_party, dem_candidate, rep_candidate = build_precinct_party_votes_county_weight_mode(
                src, office, precinct_overrides=precinct_overrides, election_year=args.year
            )
        else:
            precinct_party, dem_candidate, rep_candidate = build_precinct_party_votes(
                src, office, precinct_overrides=precinct_overrides, election_year=args.year
            )
            county_non_geo_party = None
        if precinct_party.empty:
            continue

        # Skip unopposed / same-party "uncontested" races (incl. judicial seats marked excluded
        # in judicial_candidate_party_overrides notes once leaned — only one D/R bucket has votes).
        dem_tot = float(precinct_party["dem_votes"].sum()) if "dem_votes" in precinct_party else 0.0
        rep_tot = float(precinct_party["rep_votes"].sum()) if "rep_votes" in precinct_party else 0.0
        if dem_tot <= 0 or rep_tot <= 0:
            print(
                f"  skip {contest_type}: not two-party contested "
                f"(dem={dem_tot:.0f} rep={rep_tot:.0f})"
            )
            continue

        if "state_house" in sbe2006_weight_scopes:
            dem_h, rep_h, oth_h, matched, total = aggregate_precinct_party_with_district_weights(
                precinct_party,
                sbe2006_weight_scopes["state_house"],
                county_shares=house_shares,
                county_non_geo_party=county_non_geo_party,
            )
        else:
            dem_h, rep_h, oth_h, matched, total = agg_party_to_scope(
                precinct_party,
                crosswalk_df,
                vap_df,
                args.house_file,
                "Block",
                "District",
                house_shares,
                house_bucket_shares,
                matched_precincts,
                county_non_geo_party=county_non_geo_party,
            )
        if "state_senate" in sbe2006_weight_scopes:
            dem_s, rep_s, oth_s, _, _ = aggregate_precinct_party_with_district_weights(
                precinct_party,
                sbe2006_weight_scopes["state_senate"],
                county_shares=senate_shares,
                county_non_geo_party=county_non_geo_party,
            )
        else:
            dem_s, rep_s, oth_s, _, _ = agg_party_to_scope(
                precinct_party,
                crosswalk_df,
                vap_df,
                args.senate_file,
                "Block",
                "District",
                senate_shares,
                senate_bucket_shares,
                matched_precincts,
                county_non_geo_party=county_non_geo_party,
            )
        if "congressional" in sbe2006_weight_scopes:
            dem_c, rep_c, oth_c, _, _ = aggregate_precinct_party_with_district_weights(
                precinct_party,
                sbe2006_weight_scopes["congressional"],
                county_shares=cd_shares,
                county_non_geo_party=county_non_geo_party,
            )
        else:
            dem_c, rep_c, oth_c, _, _ = agg_party_to_scope(
                precinct_party,
                crosswalk_df,
                vap_df,
                args.cd_file,
                "GEOID",
                "CDFP",
                cd_shares,
                cd_bucket_shares,
                matched_precincts,
                county_non_geo_party=county_non_geo_party,
            )

        def _district_weight_plan(scope_name: str) -> str | None:
            scope_payload = sbe2006_weight_scopes.get(scope_name)
            if not scope_payload:
                return None
            return str(scope_payload.get("plan_id") or scope_payload.get("scope") or "").strip() or None

        def _district_weights_json(scope_name: str) -> str | None:
            return args.sbe2006_district_weights_json.as_posix() if scope_name in sbe2006_weight_scopes else None

        payloads = {
            f"state_house_{contest_type}_{args.year}.json": build_payload(
                year=args.year,
                scope="state_house",
                contest_type=contest_type,
                office_label=office,
                nongeo_allocation_mode=args.nongeo_allocation_mode,
                dem_map=dem_h,
                rep_map=rep_h,
                oth_map=oth_h,
                dem_candidate=dem_candidate,
                rep_candidate=rep_candidate,
                matched=matched,
                total=total,
                match_crosswalk=match_crosswalk_path.as_posix(),
                target_crosswalk=args.crosswalk_csv.as_posix(),
                district_weights_json=_district_weights_json("state_house"),
                district_weight_plan=_district_weight_plan("state_house"),
                district_lines_year=district_lines_year,
                district_lines_label=district_lines_label,
            ),
            f"state_senate_{contest_type}_{args.year}.json": build_payload(
                year=args.year,
                scope="state_senate",
                contest_type=contest_type,
                office_label=office,
                nongeo_allocation_mode=args.nongeo_allocation_mode,
                dem_map=dem_s,
                rep_map=rep_s,
                oth_map=oth_s,
                dem_candidate=dem_candidate,
                rep_candidate=rep_candidate,
                matched=matched,
                total=total,
                match_crosswalk=match_crosswalk_path.as_posix(),
                target_crosswalk=args.crosswalk_csv.as_posix(),
                district_weights_json=_district_weights_json("state_senate"),
                district_weight_plan=_district_weight_plan("state_senate"),
                district_lines_year=district_lines_year,
                district_lines_label=district_lines_label,
            ),
            f"congressional_{contest_type}_{args.year}.json": build_payload(
                year=args.year,
                scope="congressional",
                contest_type=contest_type,
                office_label=office,
                nongeo_allocation_mode=args.nongeo_allocation_mode,
                dem_map=dem_c,
                rep_map=rep_c,
                oth_map=oth_c,
                dem_candidate=dem_candidate,
                rep_candidate=rep_candidate,
                matched=matched,
                total=total,
                match_crosswalk=match_crosswalk_path.as_posix(),
                target_crosswalk=args.crosswalk_csv.as_posix(),
                district_weights_json=_district_weights_json("congressional"),
                district_weight_plan=_district_weight_plan("congressional"),
                district_lines_year=district_lines_year,
                district_lines_label=district_lines_label,
            ),
        }
        for name, payload in payloads.items():
            if str(payload.get("scope") or "") not in emit_scopes:
                continue
            # Keep JSON pretty-printed for consistency with committed slice files and easier audit diffs.
            (out_dir / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            written += 1

        if args.write_contests:
            args.contests_dir.mkdir(parents=True, exist_ok=True)
            contest_file = args.contests_dir / f"{contest_type}_{int(args.year)}.json"
            if (not args.contests_only_missing) or (not contest_file.exists()):
                display_precinct_overrides = build_contest_display_overrides(
                    precinct_party["precinct_id"],
                    contest_display_crosswalk,
                )
                if display_precinct_overrides:
                    print(
                        f"  contest display remaps for {contest_type}: "
                        f"{len(display_precinct_overrides):,} source keys -> OneMap keys"
                    )
                contest_payload = build_precinct_contest_payload(
                    year=int(args.year),
                    contest_type=str(contest_type),
                    office_label=office,
                    nongeo_allocation_mode=str(args.nongeo_allocation_mode),
                    precinct_party=precinct_party,
                    dem_candidate=dem_candidate,
                    rep_candidate=rep_candidate,
                    display_precinct_overrides=display_precinct_overrides,
                )
                # Keep JSON pretty-printed for consistency with committed slice files and easier audit diffs.
                contest_file.write_text(json.dumps(contest_payload, indent=2) + "\n", encoding="utf-8")
                update_contests_manifest(
                    args.contests_manifest,
                    [
                        build_contests_manifest_entry(
                            year=int(args.year),
                            contest_type=str(contest_type),
                            file_name=contest_file.name,
                            payload=contest_payload,
                        )
                    ],
                )

    # Rebuild manifest
    manifest = []
    for p in sorted(out_dir.glob("*.json")):
        if p.name == "manifest.json":
            continue
        parts = p.stem.split("_")
        if len(parts) < 3:
            continue
        if parts[0] == "state" and len(parts) >= 4:
            scope = "_".join(parts[0:2])
            contest_type = "_".join(parts[2:-1])
        else:
            scope = parts[0]
            contest_type = "_".join(parts[1:-1])
        try:
            year = int(parts[-1])
        except ValueError:
            continue
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
            districts = len(((payload.get("general") or {}).get("results")) or {})
            meta = payload.get("meta") or {}
        except Exception:
            districts = 0
            meta = {}
        manifest.append(
            {
                "year": year,
                "scope": scope,
                "contest_type": contest_type,
                "file": p.name,
                "districts": districts,
                "district_lines_year": meta.get("district_lines_year"),
                "district_lines_label": meta.get("district_lines_label"),
            }
        )
    manifest.sort(key=lambda x: (x["year"], x["scope"], x["contest_type"]))
    (out_dir / "manifest.json").write_text(json.dumps({"files": manifest}, indent=2), encoding="utf-8")
    print(f"Wrote {written} slices; manifest updated at {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
