from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from main import app, authenticated


def make_stream_mock(text_chunks: list[str]):
    """Build a mock that mimics anthropic AsyncMessageStream."""
    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=False)

    async def text_stream():
        for chunk in text_chunks:
            yield chunk

    mock_stream.text_stream = text_stream()

    final = MagicMock()
    final.usage.input_tokens = 10
    final.usage.output_tokens = 5
    mock_stream.get_final_message = AsyncMock(return_value=final)
    return mock_stream


@pytest.fixture
def client():
    app.dependency_overrides[authenticated] = lambda: {"sub": "test-user"}
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_chat_streams_sse(client):
    import json

    chunks = ["Hello", ", ", "world", "!"]
    mock_stream = make_stream_mock(chunks)

    with patch("main.client.messages.stream", return_value=mock_stream):
        resp = client.post(
            "/api/chat",
            json={
                "id": "test-chat",
                "messages": [
                    {
                        "id": "msg-1",
                        "role": "user",
                        "content": "",
                        "parts": [{"type": "text", "text": "Say hello"}],
                    }
                ],
            },
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    lines = [line for line in resp.text.splitlines() if line]
    data_lines = [
        line.removeprefix("data: ") for line in lines if line.startswith("data: ")
    ]

    # Every data line must be valid JSON — the AI SDK v6 DefaultChatTransport
    # parses each SSE line with JSON.parse and a strict schema. Non-JSON
    # sentinels like "[DONE]" cause a parse error that cancels the stream,
    # which over HTTP/2 (production) sends RST_STREAM and Firefox surfaces
    # as NS_ERROR_NET_PARTIAL_TRANSFER.
    events = []
    for raw in data_lines:
        events.append(json.loads(raw))

    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert types[1] == "text-start"
    assert types[-2] == "text-end"
    assert types[-1] == "finish"

    deltas = [e for e in events if e["type"] == "text-delta"]
    assert len(deltas) == len(chunks)
    assert "".join(d["delta"] for d in deltas) == "Hello, world!"


def test_chat_ignores_extra_fields(client):
    mock_stream = make_stream_mock(["Hi"])

    with patch("main.client.messages.stream", return_value=mock_stream):
        resp = client.post(
            "/api/chat",
            json={
                "id": "chat-id",
                "trigger": "user-message",
                "messageId": "m1",
                "messages": [
                    {
                        "id": "m1",
                        "role": "user",
                        "content": "",
                        "parts": [{"type": "text", "text": "Hi"}],
                        "createdAt": "2024-01-01T00:00:00Z",
                    }
                ],
            },
        )

    assert resp.status_code == 200


def test_chat_skips_empty_messages(client):
    mock_stream = make_stream_mock(["ok"])

    with patch("main.client.messages.stream", return_value=mock_stream) as mock_call:
        client.post(
            "/api/chat",
            json={
                "messages": [
                    {"role": "user", "content": "", "parts": []},
                    {
                        "role": "user",
                        "content": "",
                        "parts": [{"type": "text", "text": "keep"}],
                    },
                ]
            },
        )

    called_messages = mock_call.call_args.kwargs["messages"]
    assert len(called_messages) == 1
    assert called_messages[0]["content"] == "keep"


# --- Health ---
#
# /health is the gate user_data.sh waits on at boot and `just restart` waits on after a
# rollout, so what it does when the database is missing is load-bearing, not cosmetic.


def test_health_is_unhealthy_without_a_database(client):
    """No pool means the app came up without its data — that is not 'ok'."""
    assert main.pool is None
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "error"


def test_health_is_unhealthy_when_the_database_does_not_answer(client, monkeypatch):
    monkeypatch.setattr(main, "pool", MagicMock())
    monkeypatch.setattr(main.db, "ping", MagicMock(side_effect=OSError("no route")))

    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["database"] == "unreachable"


def test_lifespan_serves_health_against_a_migrated_database(
    migrated_database, monkeypatch
):
    """The startup path end to end: connect, then answer /health.

    Exercises what production actually runs, rather than the dependency override the
    pantry API tests use — nothing else would catch a pool that is never opened.
    """
    monkeypatch.setenv("DATABASE_URL", migrated_database)

    with TestClient(app) as started:
        assert main.pool is not None
        resp = started.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "database": "ok"}

    # Shut down cleanly, so a later test cannot pick up a closed pool.
    assert main.pool is None


def test_lifespan_does_not_create_the_schema(unmigrated_database, monkeypatch):
    """Starting the app against an empty database must not migrate it.

    This is the invariant the whole migration split rests on: schema ownership belongs
    to Alembic, run by a separate DDL role in its own deploy step. If startup created
    tables again, the runtime role would need CREATE back and the migration history
    would stop being the only source of truth for what the schema is.
    """
    monkeypatch.setenv("DATABASE_URL", unmigrated_database)

    with TestClient(app) as started:
        assert main.pool is not None
        # The process is up and the database answers, which is all /health claims.
        assert started.get("/health").status_code == 200

        with main.pool.connection() as conn:
            for table in ("pantry_items", "alembic_version"):
                row = conn.execute("SELECT to_regclass(%s) AS t", (table,)).fetchone()
                assert row["t"] is None, f"the app created {table}; migrations own it"
