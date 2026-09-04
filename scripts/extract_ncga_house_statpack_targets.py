#!/usr/bin/env python3
"""Extract selected district rows from NCGA House StatPack election tables.

The NCGA House StatPacks begin with population reports and then contain a
series of three-page statewide election tables.  This utility reads those
tables directly from the PDF text layer and emits a compact, auditable JSON
benchmark for selected districts.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader


HEADING_RE = re.compile(r"^(20\d{2}) Election Contest Report - (.+)$")
ROW_RE = re.compile(r"^(\d{1,3})\s+(.+)$")


def parse_party_order(header: str) -> list[str]:
    """Return party labels from a header like 'District Rep % Rep Dem % Dem'."""
    tokens = header.split()
    if not tokens or tokens[0] != "District":
        return []
    parties: list[str] = []
    index = 1
    while index + 2 < len(tokens):
        party = tokens[index]
        if tokens[index + 1] == "%" and tokens[index + 2] == party:
            parties.append(party)
            index += 3
        else:
            index += 1
    return parties


def parse_row(text: str, parties: list[str]) -> tuple[str, dict[str, Any]] | None:
    match = ROW_RE.match(text.strip())
    if not match:
        return None
    district, remainder = match.groups()
    tokens = remainder.replace(",", "").split()
    if len(tokens) < len(parties) * 2:
        return None

    values: dict[str, Any] = {}
    for index, party in enumerate(parties):
        vote_token = tokens[index * 2]
        pct_token = tokens[index * 2 + 1]
        if not vote_token.isdigit() or not pct_token.endswith("%"):
            return None
        values[party] = {
            "votes": int(vote_token),
            "percent": float(pct_token[:-1]),
        }
    return district, values


def extract(
    pdf_path: Path,
    target_districts: set[str],
    *,
    plan_id: str,
    source_url: str,
) -> dict[str, Any]:
    reader = PdfReader(pdf_path)
    contests: dict[tuple[int, str], dict[str, Any]] = {}

    for page_number, page in enumerate(reader.pages, start=1):
        lines = [line.strip() for line in (page.extract_text() or "").splitlines() if line.strip()]
        heading_index = next(
            (index for index, line in enumerate(lines) if HEADING_RE.match(line)),
            None,
        )
        if heading_index is None:
            continue

        heading_match = HEADING_RE.match(lines[heading_index])
        assert heading_match is not None
        election_year = int(heading_match.group(1))
        contest_name = heading_match.group(2)
        party_order = next(
            (
                parsed
                for line in lines[heading_index + 1 :]
                if (parsed := parse_party_order(line))
            ),
            [],
        )
        if not party_order:
            continue

        key = (election_year, contest_name)
        contest = contests.setdefault(
            key,
            {
                "election_year": election_year,
                "contest": contest_name,
                "party_order": party_order,
                "source_pages": [],
                "districts": {},
            },
        )
        contest["source_pages"].append(page_number)

        for line in lines:
            parsed = parse_row(line, party_order)
            if parsed is None:
                continue
            district, values = parsed
            if district in target_districts:
                contest["districts"][district] = values

    ordered = sorted(contests.values(), key=lambda item: (item["election_year"], item["contest"]))
    missing_rows = [
        {
            "election_year": contest["election_year"],
            "contest": contest["contest"],
            "missing_districts": sorted(target_districts - set(contest["districts"])),
        }
        for contest in ordered
        if target_districts - set(contest["districts"])
    ]
    return {
        "schema": "ncga_house_statpack_targets.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_pdf": pdf_path.name,
        "source_url": source_url,
        "plan_id": plan_id,
        "target_districts": sorted(target_districts, key=int),
        "pdf_pages": len(reader.pages),
        "election_contests": len(ordered),
        "missing_rows": missing_rows,
        "contests": ordered,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--districts", default="108,109,110")
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    targets = {part.strip() for part in args.districts.split(",") if part.strip()}
    if not targets or any(not target.isdigit() for target in targets):
        parser.error("--districts must be a comma-separated list of district numbers")
    if not args.pdf.exists():
        parser.error(f"PDF not found: {args.pdf}")

    payload = extract(
        args.pdf,
        targets,
        plan_id=args.plan_id,
        source_url=args.source_url,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "source_pdf": str(args.pdf),
                "output": str(args.output),
                "pdf_pages": payload["pdf_pages"],
                "election_contests": payload["election_contests"],
                "missing_rows": len(payload["missing_rows"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
