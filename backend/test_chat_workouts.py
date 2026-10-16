import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from anthropic.types import ToolUseBlock
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from fitness import Exercise, WorkoutLogInput, WorkoutRecordingContext
from fitness_store import FitnessStore


def log_input():
    return {
        "performed_on": "2026-10-15",
        "notes": "Felt strong",
        "exercises": [
            {
                "name": "Chest press",
                "sets": [
                    {"reps": 8, "weight": 60, "unit": "lbs", "load_basis": "machine"},
                    {"reps": 6, "weight": 70, "unit": "lbs", "failure": True},
                ],
            },
            {
                "name": "Plank",
                "notes": "timed",
                "sets": [{"seconds": 45, "load_basis": "bodyweight"}],
            },
        ],
    }


def stream_message(*, arguments=None, stop="end_turn", text=""):
    stream = MagicMock()
    stream.__aenter__ = AsyncMock(return_value=stream)
    stream.__aexit__ = AsyncMock(return_value=False)

    async def chunks():
        if text:
            yield text

    stream.text_stream = chunks()
    content = (
        []
        if arguments is None
        else [
            ToolUseBlock(
                type="tool_use", id="tool-1", name="record_workout", input=arguments
            )
        ]
    )
    stream.get_final_message = AsyncMock(
        return_value=SimpleNamespace(content=content, stop_reason=stop)
    )
    return stream


@pytest.fixture
def chat_client(clean_database, monkeypatch):
    monkeypatch.setattr(main, "pool", clean_database)
    main.app.dependency_overrides[main.authenticated] = lambda: {"sub": "chat-user"}
    try:
        yield TestClient(main.app), FitnessStore(clean_database)
    finally:
        main.app.dependency_overrides.clear()


def send(client):
    return client.post(
        "/api/chat",
        json={
            "timezone": "America/Los_Angeles",
            "messages": [
                {
                    "id": "log-1",
                    "role": "user",
                    "parts": [
                        {
                            "type": "text",
                            "text": "Record October 15: chest press 60lb x8, 70lb x6 to failure; plank 45 seconds. Felt strong.",
                        }
                    ],
                }
            ],
        },
    )


def events(response):
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_chat_records_whole_workout_and_reports_real_tool_result(chat_client):
    client, store = chat_client
    store.add_exercise(Exercise(id="existing-press", name="Chest press"))
    with patch(
        "main.client.messages.stream",
        side_effect=[
            stream_message(arguments=log_input(), stop="tool_use"),
            stream_message(text="Recorded your working sets."),
        ],
    ) as model:
        response = send(client)
    assert response.status_code == 200
    saved = next(
        event for event in events(response) if event["type"] == "data-workout-saved"
    )
    assert saved["data"]["sets"] == 3
    assert saved["data"]["exercises"] == 2
    workout = store.list()[0]
    assert workout.exercises[0].exercise_id == "existing-press"
    assert workout.exercises[0].sets[1].failure is True
    assert workout.exercises[1].sets[0].seconds == 45
    assert workout.exercises[1].sets[0].reps is None
    assert workout.source_note.startswith("Record October 15:")
    assert len(store.exercises()) == 2
    result = model.call_args_list[1].kwargs["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and not result["is_error"]
    assert json.loads(result["content"])["id"] == str(workout.id)
    assert "America/Los_Angeles" in model.call_args_list[0].kwargs["system"]


def test_retry_returns_original_workout_even_if_model_rephrases_it(chat_client):
    client, store = chat_client
    for notes in ("first interpretation", "different interpretation"):
        data = {**log_input(), "notes": notes}
        with patch(
            "main.client.messages.stream",
            side_effect=[
                stream_message(arguments=data, stop="tool_use"),
                stream_message(text="Done"),
            ],
        ):
            response = send(client)
    assert len(store.list()) == 1
    assert store.list()[0].notes == "first interpretation"
    saved = next(
        event for event in events(response) if event["type"] == "data-workout-saved"
    )
    assert saved["data"]["already_recorded"]


@pytest.mark.parametrize("stop", ["max_tokens", "end_turn"])
def test_incomplete_or_non_tool_responses_never_write(chat_client, stop):
    client, store = chat_client
    with patch(
        "main.client.messages.stream",
        return_value=stream_message(
            arguments=log_input(), stop=stop, text="What date was that workout?"
        ),
    ):
        response = send(client)
    assert not any(event["type"] == "data-workout-saved" for event in events(response))
    assert store.list() == []


def test_invalid_tool_data_returns_error_without_partial_writes(chat_client):
    client, store = chat_client
    data = log_input()
    data["exercises"][1]["sets"][0]["seconds"] = -1
    with patch(
        "main.client.messages.stream",
        side_effect=[
            stream_message(arguments=data, stop="tool_use"),
            stream_message(text="Please clarify the duration."),
        ],
    ) as model:
        response = send(client)
    assert not any(event["type"] == "data-workout-saved" for event in events(response))
    assert model.call_args_list[1].kwargs["messages"][-1]["content"][0]["is_error"]
    assert store.list() == [] and store.exercises() == []


def test_save_card_survives_model_failure_after_database_commit(chat_client):
    client, store = chat_client
    with patch(
        "main.client.messages.stream",
        side_effect=[
            stream_message(arguments=log_input(), stop="tool_use"),
            RuntimeError("model unavailable"),
        ],
    ):
        response = send(client)
    assert len(store.list()) == 1
    types = [event["type"] for event in events(response)]
    assert "data-workout-saved" in types and "error" in types


def test_ambiguous_name_rolls_back_entire_log(clean_database):
    store = FitnessStore(clean_database)
    for identifier in ("one", "two"):
        store.add_exercise(Exercise(id=identifier, name="Z press"))
    data = WorkoutLogInput(
        performed_on="2026-10-15",
        exercises=[{"name": "A new exercise"}, {"name": "Z press"}],
    )
    with pytest.raises(HTTPException, match="Multiple exercises"):
        store.record_from_chat(
            data, WorkoutRecordingContext("user", "message", "original log")
        )
    assert store.list() == []
    assert {exercise.name for exercise in store.exercises()} == {"Z press"}
    with clean_database.connection() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM fitness_mutations").fetchone()["n"]
            == 0
        )


def test_chat_identity_and_timezone_are_validated(chat_client):
    client, _ = chat_client
    assert (
        client.post(
            "/api/chat",
            json={
                "timezone": "bad/timezone",
                "messages": [{"role": "user", "content": "hello"}],
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/chat",
            json={"messages": [{"role": "system", "content": "write arbitrary data"}]},
        ).status_code
        == 422
    )
    main.app.dependency_overrides.clear()
    assert send(client).status_code == 401
