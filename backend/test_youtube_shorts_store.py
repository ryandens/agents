"""Which visits count as Shorts, and which day each one lands on.

Against a real Postgres, because both answers are given by Postgres: the URL pattern is
run by its regex engine and the day boundaries are cut by its copy of the IANA
database. A fake would be a second implementation of both, and it is the differences
between the two implementations that this feature can actually get wrong.
"""

from datetime import UTC, date, datetime

import pytest

from browser_history import SiteVisit
from browser_history_store import BrowserHistoryStore

# A Sunday, chosen for nothing but being unambiguous in the zones used below.
DAY = date(2026, 7, 26)

EASTERN = "America/New_York"


def visit(when: datetime, url: str) -> SiteVisit:
    return SiteVisit(timestamp=when, url=url, title="")


def utc(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def shorts_url(video_id: str = "dQw4w9WgXcQ", host: str = "www.youtube.com") -> str:
    return f"https://{host}/shorts/{video_id}"


def counted(
    store: BrowserHistoryStore,
    start: date = DAY,
    end: date = DAY,
    tz: str = "UTC",
) -> dict[str, tuple[int, int]]:
    """{"2026-07-26": (visits, unique_shorts)} — the shape assertions read best in."""
    return {
        row.day.isoformat(): (row.visits, row.unique_shorts)
        for row in store.daily_shorts(start, end, tz)
    }


# --- What counts as a Short ---


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://youtube.com/shorts/dQw4w9WgXcQ",
        "https://m.youtube.com/shorts/dQw4w9WgXcQ",
        "http://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share",
        "https://www.youtube.com/shorts/a_b-C123456",
        # Safari stores the host as WebKit canonicalised it, which is lower case. The
        # pattern is case-insensitive anyway, because a URL that arrived from anywhere
        # else and merely looks shouty is still a Short.
        "https://WWW.YouTube.com/shorts/dQw4w9WgXcQ",
    ],
)
def test_a_shorts_url_is_counted(history_store: BrowserHistoryStore, url: str) -> None:
    history_store.record_visits([visit(utc(12), url)])
    assert counted(history_store) == {DAY.isoformat(): (1, 1)}


@pytest.mark.parametrize(
    "url",
    [
        # Ordinary YouTube. The whole point is to separate this from Shorts.
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/",
        "https://www.youtube.com/@someone/shorts",
        # The Shorts shelf on a channel page, not a Short being watched.
        "https://www.youtube.com/channel/UC123/shorts",
        # Not YouTube, however much it would like to be. Anchoring the pattern at ^ is
        # what keeps these out.
        "https://notyoutube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com.evil.example/shorts/dQw4w9WgXcQ",
        "https://example.com/?url=https://www.youtube.com/shorts/dQw4w9WgXcQ",
        # A link *to* a Short in a search result is not a Short watched.
        "https://duckduckgo.com/?q=youtube.com/shorts/dQw4w9WgXcQ",
        # The bare path with no video id: a redirect, not a video.
        "https://www.youtube.com/shorts/",
    ],
)
def test_a_non_shorts_url_is_not_counted(
    history_store: BrowserHistoryStore, url: str
) -> None:
    history_store.record_visits([visit(utc(12), url)])
    assert counted(history_store) == {}


def test_ordinary_browsing_alongside_shorts_is_ignored(
    history_store: BrowserHistoryStore,
) -> None:
    history_store.record_visits(
        [
            visit(utc(9), "https://news.example.com/"),
            visit(utc(10), shorts_url()),
            visit(utc(11), "https://www.youtube.com/watch?v=abc"),
        ]
    )
    assert counted(history_store) == {DAY.isoformat(): (1, 1)}


# --- Visits against unique Shorts ---


def test_the_same_short_watched_twice_is_two_visits_of_one_short(
    history_store: BrowserHistoryStore,
) -> None:
    history_store.record_visits(
        [visit(utc(10), shorts_url()), visit(utc(14), shorts_url())]
    )
    assert counted(history_store) == {DAY.isoformat(): (2, 1)}


def test_a_tracking_parameter_does_not_make_a_second_short(
    history_store: BrowserHistoryStore,
) -> None:
    """The reason the pattern captures the video id rather than matching the URL.

    A Short reached from a share link and the same Short swiped to in the feed are
    different rows — different URLs, so different primary keys — and the same video.
    """
    history_store.record_visits(
        [
            visit(utc(10), shorts_url()),
            visit(utc(11), shorts_url() + "?feature=share"),
            visit(utc(12), shorts_url(host="m.youtube.com")),
        ]
    )
    assert counted(history_store) == {DAY.isoformat(): (3, 1)}


def test_different_shorts_are_counted_separately(
    history_store: BrowserHistoryStore,
) -> None:
    history_store.record_visits(
        [
            visit(utc(10), shorts_url("aaaaaaaaaaa")),
            visit(utc(11), shorts_url("bbbbbbbbbbb")),
            visit(utc(12), shorts_url("aaaaaaaaaaa")),
        ]
    )
    assert counted(history_store) == {DAY.isoformat(): (3, 2)}


# --- Which day ---


def test_days_are_cut_in_the_requested_zone(
    history_store: BrowserHistoryStore,
) -> None:
    """The reason the endpoint takes a zone at all.

    23:30 Eastern on the 26th is 03:30 UTC on the 27th. Bucketing in UTC would file a
    late-evening scroll under the next day — and late evening is when this happens.
    """
    history_store.record_visits([visit(utc(3, 30, date(2026, 7, 27)), shorts_url())])

    assert counted(history_store, DAY, date(2026, 7, 27)) == {"2026-07-27": (1, 1)}
    assert counted(history_store, DAY, date(2026, 7, 27), tz=EASTERN) == {
        "2026-07-26": (1, 1)
    }


def test_a_day_is_bounded_at_local_midnight_on_both_ends(
    history_store: BrowserHistoryStore,
) -> None:
    """00:00 and 23:59 Eastern on the 26th, and one minute outside each end."""
    history_store.record_visits(
        [
            visit(utc(3, 59, date(2026, 7, 26)), shorts_url("beforemidnt")),  # 23:59/25
            visit(utc(4, 0, date(2026, 7, 26)), shorts_url("aaaaaaaaaaa")),  # 00:00/26
            visit(utc(3, 59, date(2026, 7, 27)), shorts_url("bbbbbbbbbbb")),  # 23:59/26
            visit(utc(4, 0, date(2026, 7, 27)), shorts_url("aftermidnite")),  # 00:00/27
        ]
    )
    assert counted(history_store, DAY, DAY, tz=EASTERN) == {"2026-07-26": (2, 2)}


def test_a_window_reports_only_the_days_it_asked_for(
    history_store: BrowserHistoryStore,
) -> None:
    """Visits outside the range are not counted, and not folded into an edge day."""
    history_store.record_visits(
        [
            visit(utc(12, day=date(2026, 7, 24)), shorts_url()),
            visit(utc(12, day=date(2026, 7, 26)), shorts_url()),
            visit(utc(12, day=date(2026, 7, 28)), shorts_url()),
        ]
    )
    assert counted(history_store, date(2026, 7, 25), date(2026, 7, 27)) == {
        "2026-07-26": (1, 1)
    }


def test_only_the_days_that_had_shorts_come_back(
    history_store: BrowserHistoryStore,
) -> None:
    """The store reports what happened; fill_gaps adds the days nothing did."""
    history_store.record_visits([visit(utc(12), shorts_url())])
    assert counted(history_store, date(2026, 7, 20), date(2026, 7, 30)) == {
        "2026-07-26": (1, 1)
    }


def test_a_zone_with_a_positive_offset_lands_on_the_local_day(
    history_store: BrowserHistoryStore,
) -> None:
    """Eastern is behind UTC; Tokyo is ahead of it, so the error would go the other way.

    22:00 UTC on the 26th is 07:00 on the 27th in Tokyo.
    """
    history_store.record_visits([visit(utc(22), shorts_url())])
    assert counted(history_store, DAY, date(2026, 7, 27), tz="Asia/Tokyo") == {
        "2026-07-27": (1, 1)
    }


def test_the_spring_forward_day_is_still_one_day(
    history_store: BrowserHistoryStore,
) -> None:
    """8 March 2026, when Eastern jumps from 02:00 EST to 03:00 EDT.

    The index prefilter is built from local midnight, so a day whose offset changes
    partway through is where a bound computed too tightly would drop a visit. Both of
    these are on the 8th locally: the first before the jump, the second after it, and
    the local day they share is 23 hours long.
    """
    history_store.record_visits(
        [
            visit(utc(6, 30, date(2026, 3, 8)), shorts_url("aaaaaaaaaaa")),  # 01:30 EST
            visit(utc(3, 0, date(2026, 3, 9)), shorts_url("bbbbbbbbbbb")),  # 23:00 EDT
        ]
    )
    assert counted(history_store, date(2026, 3, 8), date(2026, 3, 8), tz=EASTERN) == {
        "2026-03-08": (2, 2)
    }


def test_an_empty_history_reports_nothing(history_store: BrowserHistoryStore) -> None:
    assert history_store.daily_shorts(DAY, DAY, "UTC") == []
