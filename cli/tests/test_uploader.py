"""Uploader tests. Nothing here touches the network or Google."""

from __future__ import annotations

import pytest

from safari_history.errors import ConfigurationError, UploadFailed
from safari_history.uploader import default_audience, upload_visits

API_URL = "https://agents.example.com/api/browser-history"


class FakeResponse:
    def __init__(
        self, status_code: int, payload: dict | None = None, text: str = ""
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Records requests and replays a scripted list of responses."""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.requests: list[dict] = []

    def post(self, url, json, headers, timeout):
        self.requests.append(
            {"url": url, "json": json, "headers": headers, "timeout": timeout}
        )
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    """Retries back off in real seconds; tests should not wait for them."""
    monkeypatch.setattr("safari_history.uploader.time.sleep", lambda _: None)


def visits(count: int) -> list[dict]:
    return [
        {
            "timestamp": f"2026-07-29T08:{index // 60:02d}:{index % 60:02d}-04:00",
            "url": f"https://example.com/{index}",
            "title": f"Page {index}",
        }
        for index in range(count)
    ]


# --- Audience ---


def test_the_audience_is_the_origin_of_the_api_url() -> None:
    """It has to equal the backend's APP_BASE_URL — host only, no path."""
    assert default_audience(API_URL) == "https://agents.example.com"


def test_a_url_without_a_scheme_is_rejected() -> None:
    with pytest.raises(ConfigurationError):
        default_audience("agents.example.com/api/browser-history")


# --- Posting ---


def test_visits_are_posted_with_the_bearer_token() -> None:
    session = FakeSession([FakeResponse(201, {"received": 1, "stored": 1})])
    upload_visits(visits(1), api_url=API_URL, token="tok", session=session)

    request = session.requests[0]
    assert request["url"] == API_URL
    assert request["headers"]["Authorization"] == "Bearer tok"
    assert request["json"][0]["url"] == "https://example.com/0"


def test_totals_are_summed_across_batches() -> None:
    session = FakeSession(
        [
            FakeResponse(201, {"received": 2, "stored": 2}),
            FakeResponse(201, {"received": 1, "stored": 0}),
        ]
    )
    result = upload_visits(
        visits(3), api_url=API_URL, token="tok", batch_size=2, session=session
    )
    assert len(session.requests) == 2
    assert result == {"received": 3, "stored": 2}


def test_batches_respect_the_size_limit() -> None:
    session = FakeSession([FakeResponse(201, {"received": 500, "stored": 500})] * 3)
    upload_visits(
        visits(1001), api_url=API_URL, token="tok", batch_size=500, session=session
    )
    assert [len(request["json"]) for request in session.requests] == [500, 500, 1]


def test_an_empty_day_still_posts_once() -> None:
    """Otherwise a quiet day is never acknowledged and is retried every night."""
    session = FakeSession([FakeResponse(201, {"received": 0, "stored": 0})])
    upload_visits([], api_url=API_URL, token="tok", session=session)
    assert session.requests[0]["json"] == []


# --- Failure handling ---


def test_a_server_error_is_retried() -> None:
    session = FakeSession(
        [
            FakeResponse(503, text="upstream"),
            FakeResponse(201, {"received": 1, "stored": 1}),
        ]
    )
    result = upload_visits(visits(1), api_url=API_URL, token="tok", session=session)
    assert len(session.requests) == 2
    assert result["stored"] == 1


def test_rate_limiting_is_retried() -> None:
    session = FakeSession(
        [
            FakeResponse(429, text="slow down"),
            FakeResponse(201, {"received": 1, "stored": 1}),
        ]
    )
    upload_visits(visits(1), api_url=API_URL, token="tok", session=session)
    assert len(session.requests) == 2


def test_a_connection_error_is_retried() -> None:
    import requests

    session = FakeSession(
        [
            requests.ConnectionError("no route to host"),
            FakeResponse(201, {"received": 1, "stored": 1}),
        ]
    )
    upload_visits(visits(1), api_url=API_URL, token="tok", session=session)
    assert len(session.requests) == 2


def test_retries_eventually_give_up() -> None:
    session = FakeSession([FakeResponse(503, text="still down")] * 3)
    with pytest.raises(UploadFailed, match="giving up after 3 attempts"):
        upload_visits(visits(1), api_url=API_URL, token="tok", session=session)


def test_a_rejected_credential_is_not_retried() -> None:
    """401 fails identically every time; three attempts only slow down the report."""
    session = FakeSession([FakeResponse(401, text="Unauthorized")])
    with pytest.raises(UploadFailed, match="ALLOWED_SERVICE_ACCOUNTS"):
        upload_visits(visits(1), api_url=API_URL, token="tok", session=session)
    assert len(session.requests) == 1


def test_a_rejected_batch_is_not_retried() -> None:
    session = FakeSession([FakeResponse(422, text="bad timestamp")])
    with pytest.raises(UploadFailed, match="422"):
        upload_visits(visits(1), api_url=API_URL, token="tok", session=session)
    assert len(session.requests) == 1


def test_a_success_without_a_json_body_is_accepted() -> None:
    session = FakeSession([FakeResponse(201)])
    result = upload_visits(visits(1), api_url=API_URL, token="tok", session=session)
    assert result["received"] == 1
