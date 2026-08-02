"""The /api/youtube-shorts/daily contract the graph is drawn from.

What the store tests cover — which URLs count, which day they land on — is not
repeated here. What is left is the shape of the answer: that it is always exactly the
window asked for, that the window ends today in the caller's zone, and that a zone or
a range the app cannot honour is refused rather than guessed at.

Visits are recorded at noon UTC on a given date rather than at an offset from "now",
so no test straddles midnight on a slow CI runner. Noon may be in the future when the
suite runs early in the UTC day, which is fine: the window is bounded by date, not by
the clock, and a visit later today still belongs to today.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import main
from browser_history import SiteVisit
from browser_history_store import BrowserHistoryStore
from main import authenticated
from youtube_shorts import MAX_DAYS

# UTC+14 and UTC-11. Between them they span 25 hours, so at any instant at least one is
# on a different calendar date from UTC — which is what lets the zone test always run
# rather than skipping for the twenty hours a day when a nearer zone agrees with UTC.
FAR_EAST = "Pacific/Kiritimati"
FAR_WEST = "Pacific/Midway"


@pytest.fixture
def client(history_store: BrowserHistoryStore) -> Iterator[TestClient]:
    main.app.dependency_overrides[authenticated] = lambda: {"sub": "test-user"}
    main.app.dependency_overrides[main.visit_store] = lambda: history_store
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def watched(store: BrowserHistoryStore, on: date, video_id: str, at: int = 12) -> None:
    store.record_visits(
        [
            SiteVisit(
                timestamp=datetime.combine(on, time(hour=at), UTC),
                url=f"https://www.youtube.com/shorts/{video_id}",
            )
        ]
    )


def get(client: TestClient, **params) -> list[dict]:
    response = client.get("/api/youtube-shorts/daily", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def today_in(zone: str) -> date:
    return datetime.now(ZoneInfo(zone)).date()


# --- The window ---


def test_the_default_window_is_thirty_days(client: TestClient) -> None:
    assert len(get(client)) == 30


def test_a_window_is_exactly_the_days_asked_for(client: TestClient) -> None:
    assert len(get(client, days=7)) == 7
    assert len(get(client, days=1)) == 1
    assert len(get(client, days=MAX_DAYS)) == MAX_DAYS


def test_days_are_oldest_first_and_contiguous(client: TestClient) -> None:
    """The chart plots these left to right without sorting them itself."""
    days = [date.fromisoformat(row["day"]) for row in get(client, days=5)]
    assert days == sorted(days)
    assert days[-1] - days[0] == timedelta(days=4)


def test_the_window_ends_today(client: TestClient) -> None:
    # Bracketed rather than compared to one reading of the clock, so a run that crosses
    # midnight between the two calls fails for a real reason or not at all.
    before = today_in("UTC")
    last = get(client, days=3)[-1]["day"]
    assert last in {before.isoformat(), today_in("UTC").isoformat()}


def test_the_window_ends_on_todays_date_in_the_callers_zone(
    client: TestClient,
) -> None:
    """The reason the endpoint takes a zone: "today" is the reader's, not the server's.

    Whichever of the two extreme zones is not on the UTC date right now proves it; one
    of them never is.
    """
    utc_today = today_in("UTC")
    zone = FAR_EAST if today_in(FAR_EAST) != utc_today else FAR_WEST
    local_today = today_in(zone)
    assert local_today != utc_today, "no zone disagreed with UTC — check the fixtures"

    last = get(client, days=1, tz=zone)[0]["day"]
    assert last in {local_today.isoformat(), today_in(zone).isoformat()}
    assert last != utc_today.isoformat()


def test_every_day_is_present_even_with_no_history(client: TestClient) -> None:
    days = get(client, days=4)
    assert [row["visits"] for row in days] == [0, 0, 0, 0]
    assert [row["unique_shorts"] for row in days] == [0, 0, 0, 0]


def test_a_day_with_shorts_reports_both_counts(
    client: TestClient, history_store: BrowserHistoryStore
) -> None:
    today = today_in("UTC")
    watched(history_store, today, "aaaaaaaaaaa", at=9)
    watched(history_store, today, "bbbbbbbbbbb", at=12)
    watched(history_store, today, "aaaaaaaaaaa", at=21)

    latest = get(client, days=1)[0]
    assert (latest["visits"], latest["unique_shorts"]) == (3, 2)


def test_a_quiet_day_between_busy_ones_is_a_zero(
    client: TestClient, history_store: BrowserHistoryStore
) -> None:
    """What the graph needs from the gap filling, end to end."""
    today = today_in("UTC")
    watched(history_store, today - timedelta(days=2), "aaaaaaaaaaa")
    watched(history_store, today, "bbbbbbbbbbb")

    assert [row["visits"] for row in get(client, days=3)] == [1, 0, 1]


def test_history_older_than_the_window_is_not_included(
    client: TestClient, history_store: BrowserHistoryStore
) -> None:
    watched(history_store, today_in("UTC") - timedelta(days=5), "aaaaaaaaaaa")

    assert sum(row["visits"] for row in get(client, days=2)) == 0
    assert sum(row["visits"] for row in get(client, days=10)) == 1


# --- Refusals ---


@pytest.mark.parametrize("days", [0, -1, MAX_DAYS + 1])
def test_a_window_outside_the_supported_range_is_refused(
    client: TestClient, days: int
) -> None:
    """Refused, not clamped.

    Clamping would answer a request for two years with one year of data and no sign it
    had done so, and the caller would label the axis with the range it asked for.
    """
    response = client.get("/api/youtube-shorts/daily", params={"days": days})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "tz", ["Mars/Olympus_Mons", "", "../../etc/passwd", "/etc/localtime"]
)
def test_an_unknown_zone_is_a_client_error(client: TestClient, tz: str) -> None:
    """A 400 naming the zone, rather than a 500 from somewhere deeper.

    The path-shaped ones are the reason ValueError is caught alongside
    ZoneInfoNotFoundError: zoneinfo rejects those before it ever looks a zone up.
    """
    response = client.get("/api/youtube-shorts/daily", params={"tz": tz})
    assert response.status_code == 400, response.text
    assert "time zone" in response.json()["detail"]


def test_the_endpoint_requires_authentication(
    history_store: BrowserHistoryStore,
) -> None:
    """Every other test here overrides the dependency, so nothing else would notice.

    The store is still injected, so a 401 here is authentication refusing the request
    rather than the app happening to have no database.
    """
    main.app.dependency_overrides[main.visit_store] = lambda: history_store
    try:
        response = TestClient(main.app).get("/api/youtube-shorts/daily")
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 401


@pytest.mark.parametrize(
    "params",
    [
        {"days": 0},
        {"days": MAX_DAYS + 1},
        {"tz": "Mars/Olympus_Mons"},
        {"tz": "../../etc/passwd"},
    ],
)
def test_a_bad_request_without_credentials_is_still_only_a_401(
    history_store: BrowserHistoryStore, params: dict
) -> None:
    """Authentication settles before anything looks at the query string.

    Every one of these is a request the endpoint would refuse on its merits — 422 for
    the ranges, 400 for the zones. An anonymous caller must not be able to tell which:
    answering "that zone does not exist" to someone who never authenticated turns the
    endpoint into a free validity oracle, and it would mean the handler body ran before
    the credential was checked.

    This is ordering, not a rule written anywhere in the handler, so it is exactly the
    kind of property that a refactor moving validation into a dependency would break
    silently.
    """
    main.app.dependency_overrides[main.visit_store] = lambda: history_store
    try:
        response = TestClient(main.app).get("/api/youtube-shorts/daily", params=params)
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 401, response.text
