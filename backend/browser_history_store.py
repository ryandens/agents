"""Postgres-backed storage for browser visits.

The one idea here that the pantry store does not have is deduplication. The exporter
uploads a day at a time and retries days it is not sure landed, so the same visit
arrives more than once in normal operation — after a failed upload, after a re-export,
after a manual catch-up run. Making (timestamp, url) the identity of a visit turns
those retries into no-ops, which is what lets the client's retry policy stay simple:
it can always re-send a day without asking whether it already did.

That identity is the table's primary key, so the deduplication is the database's job
rather than a read-modify-write in Python. The difference matters under concurrency:
two exporters uploading the same day at once would each have read the same "existing"
set and each written its own copy of it.

Title is deliberately not part of the identity. Safari revises a visit's title after
the fact when a page's <title> loads late, so including it would make the corrected
re-export look like a second visit at the identical instant.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from psycopg_pool import ConnectionPool

from browser_history import SiteVisit
from youtube_shorts import SHORTS_URL_PATTERN, ShortsDay

# RETURNING reports only the rows that were actually inserted, so its length is the
# count of visits that were new — which is what the endpoint reports back to the
# exporter. ON CONFLICT DO NOTHING also collapses duplicates *within* one statement:
# Postgres checks a speculative insertion against rows inserted earlier in the same
# command, not just against rows that were already committed.
_INSERT = """
    INSERT INTO browser_visits (visited_at, url, title)
    VALUES (%s, %s, %s)
    ON CONFLICT (visited_at, url_digest) DO NOTHING
    RETURNING 1
"""

# Two predicates over the same window, doing different jobs.
#
# The (visited_at AT TIME ZONE …)::date BETWEEN … pair is the truth: it is what "which
# local day was this" means, and it is the same expression the GROUP BY buckets on, so
# a row can never be counted into a day the filter would have excluded.
#
# The visited_at >= / < pair is only an index prefilter. The primary key leads with
# visited_at, so it turns a scan of every visit ever recorded into a range scan of the
# window; without it the date expression alone is unindexable and the query gets slower
# with every day the exporter runs. It is deliberately a day wider on each side than
# the dates ask for, so no offset the zone can have at a boundary — DST, a historical
# offset change, a zone whose local midnight does not exist on some day — can make it
# narrower than the predicate it is accelerating. A prefilter that is too wide costs a
# few rows the date predicate then drops; one that is too narrow silently loses a day.
_DAILY_SHORTS = """
    SELECT (visited_at AT TIME ZONE %(tz)s)::date AS day,
           count(*) AS visits,
           count(DISTINCT substring(url from %(pattern)s)) AS unique_shorts
    FROM browser_visits
    WHERE visited_at >= %(after)s
      AND visited_at < %(before)s
      AND url ~ %(pattern)s
      AND (visited_at AT TIME ZONE %(tz)s)::date BETWEEN %(start)s AND %(end)s
    GROUP BY day
    ORDER BY day
"""

# Keeps one INSERT under Postgres's 65535-parameter ceiling with room to spare at three
# parameters per row, so a batch at MAX_VISITS_PER_REQUEST is a handful of statements in
# one transaction rather than a single statement that fails to plan.
_CHUNK_SIZE = 1000


def _values(visits: list[SiteVisit]) -> list[tuple]:
    return [(visit.timestamp, visit.url, visit.title) for visit in visits]


class BrowserHistoryStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def record_visits(self, visits: list[SiteVisit]) -> int:
        """Add visits that are not already stored. Returns how many were new."""
        if not visits:
            return 0

        rows = _values(visits)
        stored = 0
        # One connection, and therefore one transaction, for the whole batch: a day's
        # upload lands completely or not at all, so a client that retries after a
        # mid-batch failure is not reasoning about a partially stored day.
        with self._pool.connection() as conn, conn.cursor() as cursor:
            for start in range(0, len(rows), _CHUNK_SIZE):
                chunk = rows[start : start + _CHUNK_SIZE]
                cursor.executemany(_INSERT, chunk, returning=True)
                # executemany with returning=True leaves one result set per row of
                # input; nextset() walks them. A row that conflicted produced no
                # result, so counting the ones that did is the count of new visits.
                while True:
                    if cursor.rowcount > 0:
                        stored += 1
                    if not cursor.nextset():
                        break
        return stored

    def list_visits(self, limit: int | None = None) -> list[SiteVisit]:
        """The most recent visits, newest first."""
        query = """
            SELECT visited_at AS timestamp, url, title
            FROM browser_visits
            ORDER BY visited_at DESC, url
        """
        params: tuple = ()
        if limit is not None:
            query += " LIMIT %s"
            params = (limit,)

        with self._pool.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [SiteVisit.model_validate(row) for row in rows]

    def daily_shorts(self, start: date, end: date, tz: str) -> list[ShortsDay]:
        """How many Shorts were watched on each local day in [start, end].

        Only the days that had any — filling in the empty ones is youtube_shorts.
        fill_gaps, because a day with nothing in it is not a fact the database holds.

        The bucketing runs in Postgres rather than over rows fetched into Python. The
        window is bounded but the visits in it are not: a query that grouped in the
        app would carry every Shorts URL in the range across the wire to produce one
        integer per day.

        Raises ZoneInfoNotFoundError for a zone name Python does not know. Callers that
        take the name from a request should validate it themselves and answer 400 —
        this is a programming-error path, not a request-validation one.
        """
        zone = ZoneInfo(tz)
        with self._pool.connection() as conn:
            rows = conn.execute(
                _DAILY_SHORTS,
                {
                    "tz": tz,
                    "pattern": SHORTS_URL_PATTERN,
                    "start": start,
                    "end": end,
                    "after": datetime.combine(start - timedelta(days=1), time(), zone),
                    "before": datetime.combine(end + timedelta(days=2), time(), zone),
                },
            ).fetchall()
        return [ShortsDay.model_validate(row) for row in rows]

    def count(self) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT count(*) AS total FROM browser_visits"
            ).fetchone()
        return row["total"] if row else 0
