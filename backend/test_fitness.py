import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import fitness_api
import main
from fitness import SetRecord, summarize
from fitness_samples import EXERCISES, WORKOUTS
from fitness_store import FitnessStore


def test_synthetic_samples_preserve_actual_reps_and_unknowns():
    shoulder = next(e for e in WORKOUTS[0].exercises if e.exercise_id == "chest-press")
    assert [s.reps for s in shoulder.sets] == [10, 6]
    assert shoulder.sets[-1].failure is True
    leg = next(e for e in WORKOUTS[-1].exercises if e.exercise_id == "leg-press")
    assert leg.sets[-1].weight is None
    assert leg.sets[-1].reps == 10
    core = next(e for e in WORKOUTS[1].exercises if e.exercise_id == "side-plank")
    assert core.sets == []
    assert all(w.source_note.startswith("Fictional demo session") for w in WORKOUTS)


def test_summary_counts_actual_reps_and_keeps_ambiguous_sets_out():
    rows = {r["exercise_id"]: r for r in summarize(WORKOUTS, EXERCISES)}
    assert rows["chest-press"]["reps"] == 27
    assert rows["chest-press"]["sets"] == 3
    assert rows["side-plank"]["sets"] == 0
    assert rows["indoor-cycle"]["seconds"] == 480
    assert rows["dumbbell-curl"]["reps"] == 21


@pytest.mark.parametrize(
    "data",
    [
        {"reps": -1},
        {"reps": 2.5},
        {"weight": float("nan")},
        {"seconds": 0},
        {"load_basis": "bodyweight", "weight": 20},
    ],
)
def test_invalid_set_rejected(data):
    with pytest.raises(ValidationError):
        SetRecord(**data)


@pytest.fixture
def client(clean_database):
    store = FitnessStore(clean_database)
    main.app.dependency_overrides[main.authenticated] = lambda: {"sub": "test-user"}
    main.app.dependency_overrides[fitness_api.store] = lambda: store
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


def test_import_edit_delete_and_roundtrip(client):
    assert client.post("/api/fitness/import-samples").json() == {"imported": 3}
    assert client.post("/api/fitness/import-samples").json() == {"imported": 0}
    workouts = client.get("/api/fitness/workouts").json()
    assert len(workouts) == 3
    assert workouts[0]["performed_on"] == "2000-01-12"
    assert workouts[0]["exercises"][-1]["sets"][-1]["weight"] is None
    first = workouts[0]
    wid = first.pop("id")
    first.pop("revision")
    first["exercises"][-1]["sets"][-1]["weight"] = 120
    assert client.put(f"/api/fitness/workouts/{wid}", json=first).status_code == 200
    assert (
        client.get("/api/fitness/workouts").json()[0]["exercises"][-1]["sets"][-1][
            "weight"
        ]
        == 120
    )
    assert client.get("/api/fitness/summary").json()["workouts"] == 3
    assert client.delete(f"/api/fitness/workouts/{wid}").status_code == 204
    assert client.delete(f"/api/fitness/workouts/{wid}").status_code == 404
    assert client.post("/api/fitness/import-samples").json() == {"imported": 0}
    assert len(client.get("/api/fitness/workouts").json()) == 2


def test_create_and_validation(client):
    exercise = {"id": "test-press", "name": "Test press"}
    assert client.post("/api/fitness/exercises", json=exercise).status_code == 201
    assert client.post("/api/fitness/exercises", json=exercise).status_code == 409
    body = {
        "performed_on": "2000-02-01",
        "exercises": [
            {
                "exercise_id": "test-press",
                "sets": [
                    {
                        "reps": 7,
                        "weight": 20,
                        "unit": "kg",
                        "load_basis": "per_hand",
                        "failure": True,
                    }
                ],
            }
        ],
    }
    assert client.post("/api/fitness/workouts", json=body).status_code == 201
    assert (
        client.get("/api/fitness/workouts").json()[0]["exercises"][0]["sets"][0]["unit"]
        == "kg"
    )
    body["exercises"][0]["exercise_id"] = "missing"
    assert client.post("/api/fitness/workouts", json=body).status_code == 422
    assert len(client.get("/api/fitness/workouts").json()) == 1


def test_fitness_requires_auth():
    client = TestClient(main.app)
    for path in ("/workouts", "/exercises", "/summary", "/body-weight"):
        assert client.get("/api/fitness" + path).status_code == 401
    assert client.post("/api/fitness/import-samples").status_code == 401


def sync_request(client, mutation):
    return client.post(
        "/api/fitness/sync", json=mutation, headers={"X-Fitness-Owner": "test-user"}
    )


def test_offline_retry_and_revisions(client):
    from uuid import uuid4

    exercise = {"id": "offline-press", "name": "Offline press"}
    op = {"id": str(uuid4()), "kind": "exercise", "exercise": exercise}
    assert sync_request(client, op).status_code == 200
    assert sync_request(client, op).status_code == 200
    workout = {
        "id": str(uuid4()),
        "revision": 0,
        "performed_on": "2000-02-02",
        "exercises": [{"exercise_id": exercise["id"], "sets": [{"reps": 10}]}],
    }
    save = {"id": str(uuid4()), "kind": "save", "workout": workout}
    assert sync_request(client, save).status_code == 200
    # The response was lost: replay the exact operation.
    assert sync_request(client, save).status_code == 200
    rows = client.get("/api/fitness/workouts").json()
    assert len(rows) == 1 and rows[0]["revision"] == 1
    next_save = {
        **save,
        "id": str(uuid4()),
        "workout": {**workout, "revision": 1, "notes": "Edited offline"},
    }
    assert sync_request(client, next_save).status_code == 200
    stale = {**save, "id": str(uuid4())}
    assert sync_request(client, stale).status_code == 409
    assert client.get("/api/fitness/workouts").json()[0]["notes"] == "Edited offline"
    # A receipt cannot be reused for different content.
    assert (
        sync_request(
            client, {**save, "workout": {**workout, "notes": "Changed"}}
        ).status_code
        == 409
    )
    delete = {
        "id": str(uuid4()),
        "kind": "delete",
        "workout": {**workout, "revision": 2},
    }
    assert sync_request(client, delete).status_code == 200
    assert sync_request(client, delete).status_code == 200
    assert sync_request(client, save).status_code == 200
    assert client.get("/api/fitness/workouts").json() == []


def test_sync_rolls_back_receipt_for_retry_and_checks_account(client):
    from uuid import uuid4

    exercise = {"id": "not-yet-synced", "name": "New exercise"}
    workout = {
        "id": str(uuid4()),
        "revision": 0,
        "performed_on": "2000-02-02",
        "exercises": [{"exercise_id": exercise["id"]}],
    }
    mutation = {"id": str(uuid4()), "kind": "save", "workout": workout}
    assert sync_request(client, mutation).status_code == 422
    assert (
        client.post(
            "/api/fitness/sync",
            json=mutation,
            headers={"X-Fitness-Owner": "someone-else"},
        ).status_code
        == 403
    )
    assert client.post("/api/fitness/exercises", json=exercise).status_code == 201
    assert sync_request(client, mutation).status_code == 200


def test_body_weight_persists_independently_and_retries_safely(client):
    from uuid import uuid4

    measurement = {
        "id": str(uuid4()),
        "measured_on": "2026-10-15",
        "weight": 182.4,
        "unit": "lbs",
    }
    mutation = {"id": str(uuid4()), "kind": "bodyweight", "measurement": measurement}
    assert sync_request(client, mutation).status_code == 200
    assert sync_request(client, mutation).status_code == 200
    assert client.get("/api/fitness/body-weight").json() == [measurement]
    assert client.get("/api/fitness/workouts").json() == []
    # A new store reads the persisted row, not process-local state.
    original = main.app.dependency_overrides[fitness_api.store]()
    assert FitnessStore(original.pool).body_weights("test-user")[0].weight == 182.4
    assert (
        sync_request(
            client, {**mutation, "measurement": {**measurement, "weight": 180}}
        ).status_code
        == 409
    )
    assert (
        client.delete(f"/api/fitness/body-weight/{measurement['id']}").status_code
        == 200
    )
    assert (
        client.delete(f"/api/fitness/body-weight/{measurement['id']}").status_code
        == 200
    )
    # Retrying an earlier acknowledged create cannot resurrect a deletion.
    assert sync_request(client, mutation).status_code == 200
    assert client.get("/api/fitness/body-weight").json() == []


def test_body_weight_is_private_to_account(client):
    from uuid import uuid4

    measurement = {
        "id": str(uuid4()),
        "measured_on": "2026-10-15",
        "weight": 80,
        "unit": "kg",
    }
    mutation = {"id": str(uuid4()), "kind": "bodyweight", "measurement": measurement}
    assert sync_request(client, mutation).status_code == 200
    main.app.dependency_overrides[main.authenticated] = lambda: {"sub": "other-user"}
    assert client.get("/api/fitness/body-weight").json() == []
    assert (
        client.delete(f"/api/fitness/body-weight/{measurement['id']}").status_code
        == 200
    )
    assert sync_request(client, mutation).status_code == 403
    main.app.dependency_overrides[main.authenticated] = lambda: {"sub": "test-user"}
    assert client.get("/api/fitness/body-weight").json() == [measurement]
    assert (
        client.get(
            "/api/fitness/body-weight", headers={"X-Fitness-Owner": "other-user"}
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/fitness/body-weight/{measurement['id']}",
            headers={"X-Fitness-Owner": "other-user"},
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"weight": 0},
        {"weight": -1},
        {"weight": 2001},
        {"unit": "stone"},
        {"measured_on": "2026-02-30"},
    ],
)
def test_invalid_body_weight_rejected(client, patch):
    from uuid import uuid4

    measurement = {
        "id": str(uuid4()),
        "measured_on": "2026-10-15",
        "weight": 182.4,
        "unit": "lbs",
        **patch,
    }
    mutation = {"id": str(uuid4()), "kind": "bodyweight", "measurement": measurement}
    assert sync_request(client, mutation).status_code == 422
    assert client.get("/api/fitness/body-weight").json() == []
