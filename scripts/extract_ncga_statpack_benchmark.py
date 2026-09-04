#!/usr/bin/env python3
"""Extract every district election row from an official NCGA StatPack PDF."""

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


def extract(pdf_path: Path, *, scope: str, plan_id: str, source_url: str) -> dict[str, Any]:
    reader = PdfReader(pdf_path)
    contests: dict[tuple[int, str], dict[str, Any]] = {}

    for page_number, page in enumerate(reader.pages, start=1):
        lines = [line.strip() for line in (page.extract_text() or "").splitlines() if line.strip()]
        heading_index = next((i for i, line in enumerate(lines) if HEADING_RE.match(line)), None)
        if heading_index is None:
            continue
        heading = HEADING_RE.match(lines[heading_index])
        assert heading is not None
        year = int(heading.group(1))
        name = heading.group(2)
        parties = next(
            (parsed for line in lines[heading_index + 1 :] if (parsed := parse_party_order(line))),
            [],
        )
        if not parties:
            continue
        contest = contests.setdefault(
            (year, name),
            {
                "election_year": year,
                "contest": name,
                "party_order": parties,
                "source_pages": [],
                "districts": {},
            },
        )
        contest["source_pages"].append(page_number)
        for line in lines:
            parsed = parse_row(line, parties)
            if parsed is not None:
                district, values = parsed
                contest["districts"][district] = values

    ordered = sorted(contests.values(), key=lambda item: (item["election_year"], item["contest"]))
    district_counts = sorted({len(item["districts"]) for item in ordered})
    return {
        "schema": "ncga_statpack_benchmark.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "plan_id": plan_id,
        "source_pdf": pdf_path.name,
        "source_url": source_url,
        "pdf_pages": len(reader.pages),
        "election_contests": len(ordered),
        "district_row_counts": district_counts,
        "contests": ordered,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--scope", choices=("state_senate", "congressional"), required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.pdf.exists():
        parser.error(f"PDF not found: {args.pdf}")
    payload = extract(args.pdf, scope=args.scope, plan_id=args.plan_id, source_url=args.source_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in (
        "scope", "plan_id", "pdf_pages", "election_contests", "district_row_counts"
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
