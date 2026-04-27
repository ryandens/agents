from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


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
    return TestClient(app)


def test_chat_streams_sse(client):
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

    lines = [l for l in resp.text.splitlines() if l]
    data_lines = [l.removeprefix("data: ") for l in lines if l.startswith("data: ")]

    assert data_lines[0] == '{"type": "text-start", "id": "text-0"}'

    deltas = [l for l in data_lines if '"text-delta"' in l]
    assert len(deltas) == len(chunks)
    import json
    combined = "".join(json.loads(d)["delta"] for d in deltas)
    assert combined == "Hello, world!"

    assert data_lines[-2] == '{"type": "text-end", "id": "text-0"}'
    assert data_lines[-1] == "[DONE]"


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
                    {"role": "user", "content": "", "parts": [{"type": "text", "text": "keep"}]},
                ]
            },
        )

    called_messages = mock_call.call_args.kwargs["messages"]
    assert len(called_messages) == 1
    assert called_messages[0]["content"] == "keep"
