from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

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
