"""What counts as a YouTube Short, and how a day of watching them is reported.

The data is already there: cli/ uploads Safari's history and browser_visits keeps it.
This module is only the question asked of it — which of those visits were Shorts, and
how many happened on each calendar day.

"Calendar day" is the whole feature, so the time zone is not a detail to default away.
Visits are stored in UTC (browser_history.SiteVisit normalises them), and a UTC day
boundary falls at 8pm the previous evening on the US east coast — late-evening
scrolling, which is exactly when this happens, would land on the wrong day and the
graph would be quietly wrong rather than obviously broken. So the caller names the
zone and the database buckets in it.
"""

from datetime import date, timedelta

from pydantic import BaseModel

# One pattern, used twice: as the test for "was this visit a Short" and — through
# Postgres's substring(text from pattern), which returns the first capture group — as
# the extractor for *which* Short it was. Writing it once means the set of URLs counted
# and the set of URLs that can be told apart can never drift.
#
# The capture group is the video id, so the two URLs a share link and a swipe produce
# for one video (…/shorts/abc123 and …/shorts/abc123?feature=share) count as one Short
# watched twice rather than two Shorts watched once.
#
# (?i) rather than matching with ~* : the case-insensitivity has to be part of the
# pattern itself, because substring() has no case-insensitive operator form to pair
# with. Postgres accepts embedded options only at the very start of the expression.
#
# Anchored at ^ so a URL that merely *contains* a Shorts link — a search result page,
# a redirector carrying one in its query string — is not counted as watching one.
SHORTS_URL_PATTERN = r"(?i)^https?://(?:www\.|m\.)?youtube\.com/shorts/([A-Za-z0-9_-]+)"

# What the UI asks for when it has no opinion, and the ceiling on what it may ask for.
# A year of daily rows is ~15kB of JSON and 365 columns is already past what a bar
# chart can show honestly; the cap is there so a hand-written query string cannot ask
# the database to group over the entire table.
DEFAULT_DAYS = 30
MAX_DAYS = 365


class ShortsDay(BaseModel):
    """One local calendar day of Shorts watching."""

    model_config = {"extra": "forbid"}

    day: date
    # Page loads of a Shorts URL. Named for what it is rather than "views": a visit is
    # Safari having recorded a navigation, which is the closest thing the history
    # database has to "watched one" and is not the same claim.
    visits: int
    # Distinct video ids among those visits. The pair is the interesting part — 40
    # visits to 40 Shorts is a different evening from 40 visits to 3.
    unique_shorts: int


def window(days: int, today: date) -> tuple[date, date]:
    """The inclusive [start, end] date range covering the last `days` days.

    Inclusive of today, so `days=1` is today alone rather than today and yesterday.
    """
    return today - timedelta(days=days - 1), today


def fill_gaps(counted: list[ShortsDay], start: date, end: date) -> list[ShortsDay]:
    """Every day from start to end, with the days nothing happened reported as zero.

    A time axis has to be a calendar rather than a list of the days something happened.
    Handing the chart only the non-empty days would draw a week off as a single wide
    step between the days either side of it — which reads as "it stayed about the
    same", the opposite of what it means.

    Days the database returned are trusted as-is; this only adds what is missing.
    """
    by_day = {row.day: row for row in counted}
    span = max((end - start).days + 1, 0)
    every_day = (start + timedelta(days=offset) for offset in range(span))
    return [
        by_day.get(day, ShortsDay(day=day, visits=0, unique_shorts=0))
        for day in every_day
    ]
