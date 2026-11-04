"""Convert an NCSBE precinct-results TSV to OpenElections-style CSV.

Output columns:
    county,precinct,office,district,party,candidate,votes

The converter preserves every contest and vote row, including zero-vote rows and
non-geographic absentee/early/provisional buckets. Downstream atlas builders are
responsible for selecting contests and allocating non-geographic votes.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


OUTPUT_COLUMNS = [
    "county",
    "precinct",
    "office",
    "district",
    "party",
    "candidate",
    "votes",
]


def extract_district(office: object) -> str:
    """Return the district token from district-based NCSBE contest labels."""
    label = str(office or "").strip().upper()
    match = re.search(r"\bDISTRICT\s+([0-9]+[A-Z]?)\b", label)
    return match.group(1) if match else ""


def convert_to_openelections(
    input_file: Path,
    output_file: Path,
    offices: list[str] | None = None,
) -> pd.DataFrame:
    """Convert one tab-separated NCSBE precinct export."""
    print(f"Processing {input_file}...")
    source = pd.read_csv(input_file, sep="\t", dtype=str, keep_default_na=False)

    required = {
        "County",
        "Precinct",
        "Contest Name",
        "Choice Party",
        "Choice",
        "Total Votes",
    }
    missing = sorted(required - set(source.columns))
    if missing:
        raise ValueError(f"Missing required NCSBE columns: {', '.join(missing)}")

    if offices:
        wanted = {office.strip().upper() for office in offices if office.strip()}
        source = source[source["Contest Name"].str.strip().str.upper().isin(wanted)].copy()
        missing_offices = sorted(wanted - set(source["Contest Name"].str.strip().str.upper()))
        if missing_offices:
            raise ValueError(f"Requested offices not found: {', '.join(missing_offices)}")

    votes = pd.to_numeric(source["Total Votes"], errors="raise").astype("int64")
    if (votes < 0).any():
        raise ValueError("Total Votes contains a negative value")

    result = pd.DataFrame(
        {
            "county": source["County"].str.strip(),
            "precinct": source["Precinct"].str.strip(),
            "office": source["Contest Name"].str.strip(),
            "district": source["Contest Name"].map(extract_district),
            "party": source["Choice Party"].str.strip(),
            "candidate": source["Choice"].str.strip(),
            "votes": votes,
        },
        columns=OUTPUT_COLUMNS,
    )
    result = result.sort_values(
        ["county", "precinct", "office", "party", "candidate"],
        kind="stable",
    ).reset_index(drop=True)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_file, index=False, lineterminator="\n")

    print(f"Saved {len(result):,} rows to {output_file}")
    print(f"  Counties: {result['county'].nunique():,}")
    precinct_pairs = result[["county", "precinct"]].drop_duplicates().shape[0]
    print(f"  County-precinct pairs: {precinct_pairs:,}")
    print(f"  Offices: {result['office'].nunique():,}")
    print(f"  Ballot selections: {int(result['votes'].sum()):,}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="NCSBE tab-separated results file")
    parser.add_argument("output", type=Path, help="OpenElections-style CSV to write")
    parser.add_argument(
        "--office",
        action="append",
        default=[],
        help="Exact contest name to include; repeat for multiple contests (default: all)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    convert_to_openelections(args.input, args.output, offices=args.office)


if __name__ == "__main__":
    main()
