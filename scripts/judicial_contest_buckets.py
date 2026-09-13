"""Contest-specific candidate buckets for unusual judicial election formats."""

from __future__ import annotations

import re


def _norm(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


# The 2014 Martin/Seat 10 vacancy was a 19-candidate plurality election.  Party
# endorsements are useful context, but combining every endorsed candidate into
# DEM/REP changes the actual Tyson-versus-Arrowood result.  Preserve the two
# leading candidates as the comparison pair and put the other 17 in OTHER.
_SEAT_10_2014 = {
    "JOHN S ARROWOOD": "dem_votes",
    "JOHN M TYSON": "rep_votes",
}


def judicial_contest_candidate_bucket(
    *, year: int | None, office: object, candidate: object
) -> str | None:
    """Return a contest-specific vote bucket, or ``None`` for normal handling."""
    if int(year or 0) != 2014:
        return None
    office_key = _norm(office)
    if "COURT OF APPEALS" not in office_key or "MARTIN" not in office_key:
        return None
    return _SEAT_10_2014.get(_norm(candidate), "other_votes")
