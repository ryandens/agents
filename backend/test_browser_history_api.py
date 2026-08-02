from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import main
from browser_history_store import BrowserHistoryStore
from main import authenticated

VISIT = {
    "timestamp": "2026-07-29T08:14:22-04:00",
    "url": "https://example.com/page",
    "title": "Example Page",
}

OTHER_VISIT = {
    "timestamp": "2026-07-29T09:02:00-04:00",
    "url": "https://news.example.com/",
    "title": "News",
}


@pytest.fixture
def client(history_store: BrowserHistoryStore) -> Iterator[TestClient]:
    # Injected rather than left to the app's lifespan, which would open a second pool
    # against whatever DATABASE_URL happens to be set to. See test_pantry_api.py.
    main.app.dependency_overrides[authenticated] = lambda: {"sub": "test-user"}
    main.app.dependency_overrides[main.visit_store] = lambda: history_store
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


# --- Recording ---


def test_records_a_batch(client: TestClient) -> None:
    resp = client.post("/api/browser-history", json=[VISIT, OTHER_VISIT])
    assert resp.status_code == 201
    assert resp.json() == {"received": 2, "stored": 2}


def test_empty_batch_is_accepted(client: TestClient) -> None:
    """A day with no browsing is a successful export, not an error."""
    resp = client.post("/api/browser-history", json=[])
    assert resp.status_code == 201
    assert resp.json() == {"received": 0, "stored": 0}


def test_title_is_optional(client: TestClient) -> None:
    resp = client.post(
        "/api/browser-history",
        json=[{"timestamp": "2026-07-29T08:14:22-04:00", "url": "https://a.example/"}],
    )
    assert resp.status_code == 201
    assert client.get("/api/browser-history").json()[0]["title"] == ""


# --- Deduplication ---


def test_resending_the_same_batch_stores_nothing_new(client: TestClient) -> None:
    """The exporter retries whole days, so a repeat upload has to be a no-op."""
    client.post("/api/browser-history", json=[VISIT, OTHER_VISIT])
    resp = client.post("/api/browser-history", json=[VISIT, OTHER_VISIT])
    assert resp.json() == {"received": 2, "stored": 0}
    assert len(client.get("/api/browser-history").json()) == 2


def test_duplicates_within_one_batch_are_collapsed(client: TestClient) -> None:
    resp = client.post("/api/browser-history", json=[VISIT, VISIT])
    assert resp.json() == {"received": 2, "stored": 1}


def test_a_revised_title_does_not_create_a_second_visit(client: TestClient) -> None:
    """Safari backfills titles that loaded late; the re-export must not duplicate."""
    client.post("/api/browser-history", json=[{**VISIT, "title": ""}])
    resp = client.post("/api/browser-history", json=[VISIT])
    assert resp.json() == {"received": 1, "stored": 0}


def test_the_same_url_at_a_different_time_is_a_new_visit(client: TestClient) -> None:
    client.post("/api/browser-history", json=[VISIT])
    resp = client.post(
        "/api/browser-history",
        json=[{**VISIT, "timestamp": "2026-07-29T18:00:00-04:00"}],
    )
    assert resp.json() == {"received": 1, "stored": 1}


def test_the_same_instant_written_in_another_zone_is_one_visit(
    client: TestClient,
) -> None:
    """08:14:22-04:00 and 12:14:22+00:00 are the same moment."""
    client.post("/api/browser-history", json=[VISIT])
    resp = client.post(
        "/api/browser-history",
        json=[{**VISIT, "timestamp": "2026-07-29T12:14:22+00:00"}],
    )
    assert resp.json() == {"received": 1, "stored": 0}


# --- Validation ---


def test_naive_timestamps_are_rejected(client: TestClient) -> None:
    """Without an offset there is no telling which local day a late-night visit is on."""
    resp = client.post(
        "/api/browser-history",
        json=[{**VISIT, "timestamp": "2026-07-29T23:40:00"}],
    )
    assert resp.status_code == 422
    assert "offset" in resp.text


def test_empty_url_is_rejected(client: TestClient) -> None:
    resp = client.post("/api/browser-history", json=[{**VISIT, "url": ""}])
    assert resp.status_code == 422


def test_unknown_fields_are_rejected(client: TestClient) -> None:
    """Fields this API has not promised to keep must not silently disappear."""
    resp = client.post("/api/browser-history", json=[{**VISIT, "visit_count": 3}])
    assert resp.status_code == 422


def test_an_oversized_batch_is_refused(client: TestClient) -> None:
    batch = [
        {**VISIT, "timestamp": f"2026-07-29T08:14:{second:02d}-04:00"}
        for second in range(60)
    ]
    main_max = main.MAX_VISITS_PER_REQUEST
    main.MAX_VISITS_PER_REQUEST = 10
    try:
        resp = client.post("/api/browser-history", json=batch)
    finally:
        main.MAX_VISITS_PER_REQUEST = main_max
    assert resp.status_code == 413
    assert "smaller batches" in resp.text


def test_an_oversized_body_is_refused_before_it_is_read(client: TestClient) -> None:
    """The memory bound, which the visit-count cap is not.

    The count is checked in the handler, by which point FastAPI has already parsed the
    body and built every model in it. This is enforced on Content-Length, before any of
    that — so it has to reject a body whose declared size is over the limit even though
    the bytes actually sent are trivial.
    """
    resp = client.post(
        "/api/browser-history",
        content=b"[]",
        headers={"content-length": str(main.MAX_REQUEST_BYTES + 1)},
    )
    assert resp.status_code == 413
    assert "byte limit" in resp.text


def test_the_body_limit_runs_before_authentication(history_store) -> None:
    """Outermost middleware: an oversized request is turned away without a session."""
    main.app.dependency_overrides.clear()
    anonymous = TestClient(main.app)
    resp = anonymous.post(
        "/api/browser-history",
        content=b"[]",
        headers={"content-length": str(main.MAX_REQUEST_BYTES + 1)},
    )
    assert resp.status_code == 413


def test_a_normal_batch_is_not_affected_by_the_body_limit(client: TestClient) -> None:
    """Guards against a limit low enough to break ordinary use."""
    assert client.post("/api/browser-history", json=[VISIT]).status_code == 201


# --- Reading back ---


def test_list_is_newest_first(client: TestClient) -> None:
    client.post("/api/browser-history", json=[VISIT, OTHER_VISIT])
    urls = [visit["url"] for visit in client.get("/api/browser-history").json()]
    assert urls == [OTHER_VISIT["url"], VISIT["url"]]


def test_list_honours_limit(client: TestClient) -> None:
    client.post("/api/browser-history", json=[VISIT, OTHER_VISIT])
    resp = client.get("/api/browser-history", params={"limit": 1})
    assert len(resp.json()) == 1


def test_timestamps_come_back_in_utc(client: TestClient) -> None:
    client.post("/api/browser-history", json=[VISIT])
    stored = client.get("/api/browser-history").json()[0]
    assert stored["timestamp"].startswith("2026-07-29T12:14:22")


# --- Auth ---


def test_requires_authentication(history_store: BrowserHistoryStore) -> None:
    # The store is still provided, so a 401 here is auth refusing the request rather
    # than the store dependency happening to fail first with a 503.
    main.app.dependency_overrides = {main.visit_store: lambda: history_store}
    try:
        anonymous = TestClient(main.app)
        assert anonymous.post("/api/browser-history", json=[VISIT]).status_code == 401
        assert anonymous.get("/api/browser-history").status_code == 401
    finally:
        main.app.dependency_overrides.clear()
