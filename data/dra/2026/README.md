# 2026 DRA block election files

These CSVs are formatted for Dave's Redistricting with one row for every North Carolina 2020 Census block:

```text
GEOID20,Tot,D,R
```

- `GEOID20` is the 15-digit 2020 Census block identifier.
- `Tot` is the total vote, including minor-party and unaffiliated candidates.
- `D` and `R` are Democratic and Republican votes.
- Other votes are therefore `Tot - D - R`.

The files cover U.S. Senate, U.S. House, NC State House, NC State Senate, NC Supreme Court Seat 1, and NC Court of Appeals Seats 1–3. Each file contains all 236,638 North Carolina blocks.

The source is the NCSBE November 13, 2026, 7:05:40 p.m. ET county-canvass precinct export. The State Board certified the election results on November 24, except NC House District 62 and District Attorney District 21, which were still under recount. The export is very close to the [certified results by contest](https://s3.amazonaws.com/dl.ncsbe.gov/State_Board_Meeting_Docs/2026-11-24/Canvass/State_Composite_Abstract_Report-Contest-redacted_NCH62_DA21_w.pdf), but it is not an exact copy of those totals: in the U.S. Senate race, Cooper has 9 fewer votes, Whatley 3 more, Bray 1 fewer, and Dublin 3 fewer. Each candidate in the Supreme Court and three Court of Appeals races also differs by no more than 9 votes. The State House block file may require one final refresh after the House District 62 recount.

These are final-canvass-era election results allocated to blocks, not certified block-level vote counts. Non-geographic ballots are allocated to geographic precincts using the repository's established candidate-share method. Precinct votes are then allocated to blocks by 2020 voting-age population. Integer largest-remainder rounding preserves the exact statewide Democratic, Republican, other, and total vote counts **of the checked-in export**.

Rebuild the files from the checked-in OpenElections CSV:

```powershell
python scripts/build_2026_dra_block_csvs.py
```

`manifest.json` records the source, allocation method, file list, block counts, office counts, and exact statewide controls.
