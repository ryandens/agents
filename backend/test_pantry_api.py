from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import main
from main import authenticated
from pantry_store import PantryStore

OLIVE_OIL = {
    "name": "Olive Oil",
    "brand": "California Olive Ranch",
    "category": "condiments",
    "storage_location": "pantry",
    "quantity": 1.0,
    "unit": "bottle",
    "purchase_date": None,
    "expiration_date": None,
    "notes": None,
}

MILK = {
    "name": "Whole Milk",
    "brand": None,
    "category": "dairy",
    "storage_location": "fridge",
    "quantity": 0.5,
    "unit": "gallons",
    "purchase_date": None,
    "expiration_date": "2026-05-01",
    "notes": None,
}


@pytest.fixture
def client(store: PantryStore) -> Iterator[TestClient]:
    # The store is injected rather than left to the app's lifespan, which would open a
    # second pool against whatever DATABASE_URL happens to be set to — in a developer's
    # shell that is the local dev database, not the test container.
    main.app.dependency_overrides[authenticated] = lambda: {"sub": "test-user"}
    main.app.dependency_overrides[main.store] = lambda: store
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


# --- List ---


def test_list_empty(client: TestClient) -> None:
    resp = client.get("/api/pantry")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_returns_created_items(client: TestClient) -> None:
    client.post("/api/pantry", json=OLIVE_OIL)
    client.post("/api/pantry", json=MILK)
    resp = client.get("/api/pantry")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_filters_by_location(client: TestClient) -> None:
    client.post("/api/pantry", json=OLIVE_OIL)
    client.post("/api/pantry", json=MILK)

    pantry = client.get("/api/pantry?location=pantry").json()
    assert len(pantry) == 1
    assert pantry[0]["name"] == "Olive Oil"

    fridge = client.get("/api/pantry?location=fridge").json()
    assert len(fridge) == 1
    assert fridge[0]["name"] == "Whole Milk"


def test_list_invalid_location_returns_422(client: TestClient) -> None:
    resp = client.get("/api/pantry?location=basement")
    assert resp.status_code == 422


# --- Create ---


def test_create_returns_201_with_item(client: TestClient) -> None:
    resp = client.post("/api/pantry", json=OLIVE_OIL)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Olive Oil"
    assert body["category"] == "condiments"
    assert "id" in body
    assert "created_at" in body


def test_create_missing_required_field_returns_422(client: TestClient) -> None:
    resp = client.post("/api/pantry", json={"name": "Oil"})
    assert resp.status_code == 422


def test_create_invalid_enum_returns_422(client: TestClient) -> None:
    resp = client.post(
        "/api/pantry", json={**OLIVE_OIL, "category": "snacks_and_stuff"}
    )
    assert resp.status_code == 422


def test_create_preserves_optional_fields(client: TestClient) -> None:
    resp = client.post("/api/pantry", json=MILK)
    assert resp.status_code == 201
    body = resp.json()
    assert body["expiration_date"] == "2026-05-01"
    assert body["brand"] is None


# --- Get ---


def test_get_existing_item(client: TestClient) -> None:
    created = client.post("/api/pantry", json=OLIVE_OIL).json()
    resp = client.get(f"/api/pantry/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_nonexistent_item_returns_404(client: TestClient) -> None:
    resp = client.get("/api/pantry/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_get_malformed_uuid_returns_422(client: TestClient) -> None:
    resp = client.get("/api/pantry/not-a-uuid")
    assert resp.status_code == 422


# --- Update ---


def test_update_patches_quantity(client: TestClient) -> None:
    created = client.post("/api/pantry", json=OLIVE_OIL).json()
    resp = client.patch(f"/api/pantry/{created['id']}", json={"quantity": 0.25})
    assert resp.status_code == 200
    body = resp.json()
    assert body["quantity"] == 0.25
    assert body["name"] == "Olive Oil"


def test_update_does_not_change_unset_fields(client: TestClient) -> None:
    created = client.post("/api/pantry", json=OLIVE_OIL).json()
    client.patch(f"/api/pantry/{created['id']}", json={"notes": "Used half"})
    resp = client.get(f"/api/pantry/{created['id']}")
    body = resp.json()
    assert body["notes"] == "Used half"
    assert body["brand"] == "California Olive Ranch"


def test_update_nonexistent_item_returns_404(client: TestClient) -> None:
    resp = client.patch(
        "/api/pantry/00000000-0000-0000-0000-000000000000",
        json={"quantity": 1.0},
    )
    assert resp.status_code == 404


# --- Delete ---


def test_delete_existing_item_returns_204(client: TestClient) -> None:
    created = client.post("/api/pantry", json=OLIVE_OIL).json()
    resp = client.delete(f"/api/pantry/{created['id']}")
    assert resp.status_code == 204


def test_deleted_item_no_longer_fetchable(client: TestClient) -> None:
    created = client.post("/api/pantry", json=OLIVE_OIL).json()
    client.delete(f"/api/pantry/{created['id']}")
    resp = client.get(f"/api/pantry/{created['id']}")
    assert resp.status_code == 404


def test_delete_nonexistent_item_returns_404(client: TestClient) -> None:
    resp = client.delete("/api/pantry/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
