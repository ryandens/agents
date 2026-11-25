"""Reddit metrics derived from existing Safari visits; no collection or migration."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from psycopg import sql
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from browser_history import SiteVisit

# Match the authority, never a Reddit URL embedded in a query or a lookalike host.
REDDIT_URL = r"(?i)^https?://(?:[a-z0-9-]+\.)*reddit\.com(?::[0-9]+)?(?:[/?#]|$)"
NO_SUBREDDIT = "__none__"


class RedditDay(BaseModel):
    day: date
    has_history: bool = False
    visits: int = 0
    raw_visits: int = 0
    unique_posts: int = 0


class SubredditCount(BaseModel):
    subreddit: str | None
    visits: int
    raw_visits: int


class RedditReport(BaseModel):
    days: list[RedditDay]
    subreddits: list[SubredditCount]


class RedditVisit(SiteVisit):
    subreddit: str | None


class RedditVisits(BaseModel):
    visits: list[RedditVisit]
    total: int
    limit: int
    offset: int


# Keep filtering, attribution and canonical page identities identical for all views.
# Queries use bound values, including the optional subreddit filter.
_BASE = r"""
    WITH history AS (
        SELECT visited_at, url, title, url_digest,
               (visited_at AT TIME ZONE %(tz)s)::date AS day
        FROM browser_visits
        WHERE visited_at >= %(after)s AND visited_at < %(before)s
    ), paths AS (
        SELECT *, regexp_replace(regexp_replace(url, '[?#].*$', ''),
                                 '^https?://[^/]+', '', 'i') AS path
        FROM history WHERE url ~ %(pattern)s
    ), reddit AS (
        SELECT *,
               lower(substring(path FROM '(?i)^/r/([a-z0-9_]+)(?:/|$)')) AS subreddit,
               lower(substring(path FROM '(?i)^/(?:r/[a-z0-9_]+/)?comments/([a-z0-9]+)(?:/|$)')) AS post_id
        FROM paths
    ), scoped AS (
        SELECT * FROM reddit
        WHERE (%(subreddit)s::text IS NULL
               OR subreddit = %(subreddit)s
               OR (%(subreddit)s = '__none__' AND subreddit IS NULL))
    )
"""
_SEQUENCE = r"""
    , sequenced AS (
        SELECT *, lag(visited_at) OVER (
            PARTITION BY day, subreddit,
                CASE WHEN post_id IS NOT NULL THEN 'post:' || post_id
                     ELSE 'page:' || coalesce(nullif(lower(rtrim(path, '/')), ''), '/') END
            ORDER BY visited_at, url_digest
        ) AS previous_visit
        FROM scoped
    ), counted AS (
        SELECT *, (previous_visit IS NULL
                   OR visited_at - previous_visit > interval '120 seconds') AS is_visit
        FROM sequenced
    )
"""


def _params(start: date, end: date, tz: str, subreddit: str | None) -> dict:
    zone = ZoneInfo(tz)
    return {
        "after": datetime.combine(start, time(), zone),
        "before": datetime.combine(end + timedelta(days=1), time(), zone),
        "tz": tz,
        "pattern": REDDIT_URL,
        "subreddit": subreddit.lower() if subreddit else None,
    }


def reddit_report(
    pool: ConnectionPool, start: date, end: date, tz: str, subreddit: str | None
) -> RedditReport:
    params = _params(start, end, tz, subreddit)
    with pool.connection() as conn:
        daily = conn.execute(
            sql.SQL("").join(
                [
                    sql.SQL(_BASE),
                    sql.SQL(_SEQUENCE),
                    sql.SQL("""
            , totals AS (
                SELECT day, count(*) AS raw_visits,
                       count(*) FILTER (WHERE is_visit) AS visits,
                       count(DISTINCT post_id) AS unique_posts
                FROM counted GROUP BY day
            )
            SELECT history.day, true AS has_history,
                   coalesce(totals.visits, 0) AS visits,
                   coalesce(totals.raw_visits, 0) AS raw_visits,
                   coalesce(totals.unique_posts, 0) AS unique_posts
            FROM (SELECT DISTINCT day FROM history) history
            LEFT JOIN totals USING (day) ORDER BY history.day
            """),
                ]
            ),
            params,
        ).fetchall()
        # Keep all communities available while drilling into a single one.
        communities = conn.execute(
            sql.SQL("").join(
                [
                    sql.SQL(_BASE),
                    sql.SQL(_SEQUENCE),
                    sql.SQL("""
            SELECT subreddit, count(*) FILTER (WHERE is_visit) AS visits,
                   count(*) AS raw_visits
            FROM counted GROUP BY subreddit
            ORDER BY visits DESC, subreddit NULLS LAST
            """),
                ]
            ),
            {**params, "subreddit": None},
        ).fetchall()
    by_day = {row["day"]: RedditDay.model_validate(row) for row in daily}
    return RedditReport(
        days=[
            by_day.get(day, RedditDay(day=day))
            for day in (
                start + timedelta(days=i) for i in range((end - start).days + 1)
            )
        ],
        subreddits=[SubredditCount.model_validate(row) for row in communities],
    )


def reddit_visits(
    pool: ConnectionPool,
    start: date,
    end: date,
    tz: str,
    subreddit: str | None,
    day: date | None,
    limit: int,
    offset: int,
) -> RedditVisits:
    params = {**_params(start, end, tz, subreddit), "day": day}
    where = sql.SQL(" WHERE (%(day)s::date IS NULL OR day = %(day)s::date)")
    with pool.connection() as conn:
        total = conn.execute(
            sql.SQL("").join(
                [sql.SQL(_BASE), sql.SQL("SELECT count(*) AS total FROM scoped"), where]
            ),
            params,
        ).fetchone()["total"]
        rows = conn.execute(
            sql.SQL("").join(
                [
                    sql.SQL(_BASE),
                    sql.SQL(
                        "SELECT visited_at AS timestamp, url, title, subreddit FROM scoped"
                    ),
                    where,
                    sql.SQL(
                        " ORDER BY visited_at DESC, url_digest DESC LIMIT %(limit)s OFFSET %(offset)s"
                    ),
                ]
            ),
            {**params, "limit": limit, "offset": offset},
        ).fetchall()
    return RedditVisits(
        visits=[RedditVisit.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
