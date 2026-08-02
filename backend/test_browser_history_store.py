"""Store-level tests for the things the API tests cannot reach.

test_browser_history_api.py already covers deduplication and reading back through HTTP.
What is left here is the SQL the API layer hides: the digest column that makes a long
URL storable, and the chunking that keeps a large batch under Postgres's parameter
ceiling. Both are decisions in browser_history_store.py that a passing API test would
not notice going wrong.
"""

from datetime import UTC, datetime, timedelta

from browser_history import MAX_URL_LENGTH, SiteVisit
from browser_history_store import _CHUNK_SIZE, BrowserHistoryStore

START = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


_PREFIX = "https://example.com/?q="


def visit(offset: int, url: str = "https://example.com/", title: str = "") -> SiteVisit:
    return SiteVisit(timestamp=START + timedelta(seconds=offset), url=url, title=title)


def padded_url(length: int, suffix: str = "") -> str:
    """A URL of exactly `length` characters, ending in `suffix`."""
    filler = "a" * (length - len(_PREFIX) - len(suffix))
    return f"{_PREFIX}{filler}{suffix}"


def test_a_url_too_long_to_index_is_still_stored(
    history_store: BrowserHistoryStore,
) -> None:
    """The reason url_digest exists.

    A btree entry cannot exceed roughly a third of an 8kB page, so keying on the URL
    itself would make this INSERT fail outright — not deduplicate badly, fail.
    """
    url = padded_url(MAX_URL_LENGTH)
    assert len(url) == MAX_URL_LENGTH

    assert history_store.record_visits([visit(0, url=url)]) == 1
    assert history_store.list_visits()[0].url == url


def test_two_long_urls_alike_until_the_end_are_different_visits(
    history_store: BrowserHistoryStore,
) -> None:
    """A digest of the whole URL, not a truncation of it."""
    first = padded_url(MAX_URL_LENGTH, suffix="1")
    second = padded_url(MAX_URL_LENGTH, suffix="2")
    assert first[:-1] == second[:-1]

    assert history_store.record_visits([visit(0, url=first)]) == 1
    assert history_store.record_visits([visit(0, url=second)]) == 1
    assert history_store.count() == 2


def test_a_batch_larger_than_one_chunk_is_counted_correctly(
    history_store: BrowserHistoryStore,
) -> None:
    """Spans the _CHUNK_SIZE boundary, where an off-by-one would lose a row."""
    batch = [visit(second) for second in range(_CHUNK_SIZE + 5)]
    assert history_store.record_visits(batch) == _CHUNK_SIZE + 5
    assert history_store.count() == _CHUNK_SIZE + 5


def test_re_sending_a_multi_chunk_batch_stores_nothing(
    history_store: BrowserHistoryStore,
) -> None:
    batch = [visit(second) for second in range(_CHUNK_SIZE + 5)]
    history_store.record_visits(batch)
    assert history_store.record_visits(batch) == 0
    assert history_store.count() == _CHUNK_SIZE + 5


def test_a_mixed_batch_counts_only_the_new_visits(
    history_store: BrowserHistoryStore,
) -> None:
    """The count the endpoint reports back, with old and new interleaved.

    Straightforward to get wrong: the count comes from walking one result set per row
    of input, and a loop that mis-tracks which set it is on would still return a
    plausible-looking number.
    """
    history_store.record_visits([visit(0), visit(2), visit(4)])
    mixed = [visit(0), visit(1), visit(2), visit(3), visit(4), visit(5)]
    assert history_store.record_visits(mixed) == 3
    assert history_store.count() == 6


def test_an_empty_batch_is_a_no_op(history_store: BrowserHistoryStore) -> None:
    assert history_store.record_visits([]) == 0
    assert history_store.count() == 0


def test_a_late_arriving_title_does_not_overwrite_the_stored_one(
    history_store: BrowserHistoryStore,
) -> None:
    """DO NOTHING, not DO UPDATE.

    Documenting the trade-off rather than endorsing it: the first title Safari had for a
    visit is the one that is kept. Upserting the title instead would mean a re-export of
    an old day could rewrite rows, which is a bigger promise than this endpoint makes.
    """
    history_store.record_visits([visit(0, title="Loading…")])
    history_store.record_visits([visit(0, title="Example Domain")])
    assert history_store.list_visits()[0].title == "Loading…"
