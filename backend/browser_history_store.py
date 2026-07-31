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

from psycopg_pool import ConnectionPool

from browser_history import SiteVisit

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

    def count(self) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT count(*) AS total FROM browser_visits"
            ).fetchone()
        return row["total"] if row else 0
