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

The source is the NCSBE November 11, 2026, 4:00:44 p.m. ET precinct posting, when all 100 counties showed U.S. Senate provisional votes. These results remain unofficial until the statewide canvass. Non-geographic ballots are allocated to geographic precincts using the repository's established candidate-share method. Precinct votes are then allocated to blocks by 2020 voting-age population. Integer largest-remainder rounding preserves the exact statewide Democratic, Republican, other, and total vote counts.

Rebuild the files from the checked-in OpenElections CSV:

```powershell
python scripts/build_2026_dra_block_csvs.py
```

`manifest.json` records the source, allocation method, file list, block counts, office counts, and exact statewide controls.
