from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import main
from browser_history import SiteVisit
from reddit import NO_SUBREDDIT

DAY = date(2026, 7, 26)


def record(store, url, seconds=0, day=DAY):
    store.record_visits(
        [
            SiteVisit(
                timestamp=datetime.combine(day, datetime.min.time(), UTC)
                + timedelta(seconds=seconds),
                url=url,
                title="Example post",
            )
        ]
    )


@pytest.mark.parametrize(
    "host",
    [
        "reddit.com",
        "www.reddit.com",
        "old.reddit.com",
        "new.reddit.com",
        "m.reddit.com",
        "np.reddit.com",
        "WWW.Reddit.COM",
    ],
)
def test_reddit_authorities_and_subreddit_case(history_store, host):
    record(history_store, f"https://{host}/r/Python/comments/abc123/title/?sort=new")
    report = history_store.reddit_report(DAY, DAY, "UTC")
    assert (
        report.days[0].visits
        == report.days[0].raw_visits
        == report.days[0].unique_posts
        == 1
    )
    assert report.subreddits[0].subreddit == "python"


@pytest.mark.parametrize(
    "url",
    [
        "https://reddit.com.evil.example/r/python",
        "https://notreddit.com/r/python",
        "https://example.com/?url=https://reddit.com/r/python",
        "https://reddit.com@evil.example/r/python",
        "https://reddit.com:bad/r/python",
        "https://redd.it/abc123",
    ],
)
def test_lookalikes_and_embedded_links_do_not_count(history_store, url):
    record(history_store, url)
    report = history_store.reddit_report(DAY, DAY, "UTC")
    assert report.days[0].has_history
    assert report.days[0].visits == report.days[0].raw_visits == 0
    assert report.subreddits == []


def test_page_opens_collapse_redirects_queries_and_comment_paths(history_store):
    for seconds, url in [
        (0, "https://www.reddit.com/r/python/comments/abc123/title"),
        (60, "https://old.reddit.com/r/Python/comments/abc123/title/?sort=new"),
        (180, "https://reddit.com/r/python/comments/abc123/title/comment456/#context"),
        (301, "https://reddit.com/r/python/comments/abc123/other-title"),
        (302, "https://reddit.com/r/python/comments/def456/other-post"),
    ]:
        record(history_store, url, seconds)
    row = history_store.reddit_report(DAY, DAY, "UTC").days[0]
    assert (row.visits, row.raw_visits, row.unique_posts) == (3, 5, 2)
    scoped = history_store.reddit_report(DAY, DAY, "UTC", "PYTHON")
    assert scoped.days[0] == row
    assert scoped.subreddits[0].visits == row.visits


def test_missing_days_and_non_reddit_history_remain_distinct(history_store):
    record(history_store, "https://example.com", day=DAY)
    rows = history_store.reddit_report(DAY, DAY + timedelta(days=1), "UTC").days
    assert rows[0].has_history and rows[0].visits == 0
    assert not rows[1].has_history and rows[1].visits == 0


def test_local_midnight_and_dst_determine_buckets(history_store):
    day = date(2026, 3, 8)
    record(history_store, "https://reddit.com/r/python", 7 * 3600 + 30 * 60, day)
    record(history_store, "https://reddit.com/r/python", 10 * 3600 + 30 * 60, day)
    report = history_store.reddit_report(
        day - timedelta(days=1), day, "America/Los_Angeles"
    )
    assert [(r.raw_visits, r.visits) for r in report.days] == [(1, 1), (1, 1)]


def test_unattributed_pages_are_browsable_and_filters_preserve_all_communities(
    history_store,
):
    for i, path in enumerate(
        [
            "",
            "/?feed=home",
            "/search?q=python",
            "/user/example",
            "/comments/abc123/title",
            "/r/python+news",
            "/r/Python",
            "/r/news/",
        ]
    ):
        record(history_store, "https://reddit.com" + path, i * 10)
    report = history_store.reddit_report(DAY, DAY, "UTC", NO_SUBREDDIT)
    assert report.days[0].raw_visits == 6
    assert {r.subreddit for r in report.subreddits} == {None, "python", "news"}
    listing = history_store.reddit_visits(DAY, DAY, "UTC", NO_SUBREDDIT)
    assert listing.total == 6 and all(r.subreddit is None for r in listing.visits)
    assert history_store.reddit_report(DAY, DAY, "UTC", "missing").days[0].visits == 0


def test_raw_records_paginate_with_equal_timestamps_and_keep_original_urls(
    history_store,
):
    for path in ["/r/python/?sort=new", "/r/python/?sort=top", "/r/news"]:
        record(history_store, "https://old.reddit.com" + path, 3600)
    first = history_store.reddit_visits(DAY, DAY, "UTC", "python", limit=1)
    second = history_store.reddit_visits(DAY, DAY, "UTC", "python", limit=1, offset=1)
    assert first.total == second.total == 2
    assert first.visits[0].url != second.visits[0].url
    assert first.visits[0].title == "Example post"
    assert history_store.reddit_visits(DAY, DAY, "UTC", "python", offset=2).visits == []


@pytest.fixture
def client(history_store):
    main.app.dependency_overrides[main.authenticated] = lambda: {"sub": "test-user"}
    main.app.dependency_overrides[main.visit_store] = lambda: history_store
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def test_api_window_filters_and_raw_day(client, history_store):
    today = datetime.now(UTC).date()
    record(
        history_store, "https://reddit.com/r/python/comments/abc123/title", 3600, today
    )
    record(history_store, "https://reddit.com/r/news/", 3600, today - timedelta(days=1))
    response = client.get(
        "/api/reddit/daily", params={"days": 7, "tz": "UTC", "subreddit": "PYTHON"}
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert len(report["days"]) == 7
    assert report["days"][-1]["day"] == str(today)
    assert report["days"][-1]["visits"] == 1
    assert report["days"][-2]["has_history"] and report["days"][-2]["raw_visits"] == 0
    response = client.get(
        "/api/reddit/visits",
        params={"days": 7, "day": str(today), "subreddit": "python", "limit": 1},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["visits"][0]["subreddit"] == "python"


@pytest.mark.parametrize(
    "path,params,status",
    [
        ("daily", {"days": 0}, 422),
        ("daily", {"days": 366}, 422),
        ("daily", {"tz": "Not/AZone"}, 400),
        ("visits", {"tz": "../UTC"}, 400),
        ("daily", {"subreddit": "python' OR 1=1"}, 422),
        ("visits", {"limit": 201}, 422),
        ("visits", {"offset": -1}, 422),
        ("visits", {"day": "2000-01-01"}, 400),
    ],
)
def test_api_rejects_invalid_queries(client, path, params, status):
    assert client.get(f"/api/reddit/{path}", params=params).status_code == status


def test_both_endpoints_require_authentication():
    with TestClient(main.app) as client:
        assert client.get("/api/reddit/daily").status_code == 401
        assert client.get("/api/reddit/visits").status_code == 401
