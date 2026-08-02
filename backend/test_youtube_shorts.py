"""The parts of the Shorts graph that are arithmetic rather than SQL.

The pattern itself is tested in test_youtube_shorts_store.py, against the Postgres
regex engine that actually runs it — asserting here that Python's `re` agrees with it
would be testing a second implementation nothing uses.
"""

from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, reset_tzpath

import pytest

from youtube_shorts import ShortsDay, fill_gaps, window


def day(iso: str, visits: int = 1, unique_shorts: int = 1) -> ShortsDay:
    return ShortsDay(
        day=date.fromisoformat(iso), visits=visits, unique_shorts=unique_shorts
    )


# --- window ---


def test_a_one_day_window_is_today_alone() -> None:
    """Off by one here would put a "today" graph on yesterday."""
    assert window(1, date(2026, 8, 1)) == (date(2026, 8, 1), date(2026, 8, 1))


def test_a_weeks_window_is_seven_days_including_today() -> None:
    assert window(7, date(2026, 8, 1)) == (date(2026, 7, 26), date(2026, 8, 1))


def test_a_window_spans_a_month_boundary() -> None:
    assert window(30, date(2026, 8, 1)) == (date(2026, 7, 3), date(2026, 8, 1))


# --- fill_gaps ---


def test_every_day_in_the_range_is_present() -> None:
    filled = fill_gaps([], date(2026, 7, 30), date(2026, 8, 2))
    assert [row.day.isoformat() for row in filled] == [
        "2026-07-30",
        "2026-07-31",
        "2026-08-01",
        "2026-08-02",
    ]


def test_a_day_with_nothing_is_zero_rather_than_absent() -> None:
    """The reason this function exists.

    Handing a chart only the days that had visits draws a week off as one wide step
    between the days either side of it, which reads as "about the same" rather than
    "none".
    """
    filled = fill_gaps(
        [day("2026-08-02", visits=9, unique_shorts=4)],
        date(2026, 7, 31),
        date(2026, 8, 2),
    )
    assert [(row.visits, row.unique_shorts) for row in filled] == [
        (0, 0),
        (0, 0),
        (9, 4),
    ]


def test_counted_days_keep_their_numbers_and_their_order() -> None:
    filled = fill_gaps(
        [day("2026-08-01", visits=3, unique_shorts=2), day("2026-07-30", visits=5)],
        date(2026, 7, 30),
        date(2026, 8, 1),
    )
    assert [(row.day.day, row.visits) for row in filled] == [(30, 5), (31, 0), (1, 3)]


def test_a_single_day_range_is_one_row() -> None:
    filled = fill_gaps([], date(2026, 8, 1), date(2026, 8, 1))
    assert len(filled) == 1


def test_an_inverted_range_is_empty_rather_than_an_error() -> None:
    """Not reachable through the endpoint, where window() builds the range.

    Asserted anyway because the alternative is a negative span silently becoming a
    very long loop if this ever grows a second caller.
    """
    assert fill_gaps([], date(2026, 8, 2), date(2026, 8, 1)) == []


# --- the time zone database ---


def test_a_zone_resolves_without_a_system_timezone_database() -> None:
    """Guards the one bug in this feature that no other test can see.

    zoneinfo reads /usr/share/zoneinfo and only falls back to the `tzdata` package when
    the host has none. Developer machines and the CI runner have one; the Chainguard
    image the app actually ships in has no zoneinfo directory at all. Every other test
    here would therefore pass with tzdata missing from the dependencies, while every
    request naming a real zone 500'd in production.

    Emptying TZPATH is what makes this test see what the image sees. no_cache() because
    the zone is almost certainly already cached from an earlier test, and a cache hit
    would never consult TZPATH at all.
    """
    reset_tzpath(to=[])
    try:
        assert ZoneInfo.no_cache("America/New_York") is not None
    except ZoneInfoNotFoundError:  # pragma: no cover - only without the dependency
        pytest.fail("tzdata is not installed; the deployed image has no other copy")
    finally:
        reset_tzpath()
