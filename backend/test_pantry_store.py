from pathlib import Path
from uuid import uuid4

import pytest

from pantry import Category, PantryItemCreate, PantryItemUpdate, StorageLocation, Unit
from pantry_store import PantryStore

OLIVE_OIL = PantryItemCreate(
    name="Olive Oil",
    brand="California Olive Ranch",
    category=Category.condiments,
    storage_location=StorageLocation.pantry,
    quantity=1.0,
    unit=Unit.bottle,
)

MILK = PantryItemCreate(
    name="Whole Milk",
    category=Category.dairy,
    storage_location=StorageLocation.fridge,
    quantity=0.5,
    unit=Unit.gallons,
)


@pytest.fixture
def store(tmp_path: Path) -> PantryStore:
    return PantryStore(file_path=tmp_path / "pantry.json")


def test_empty_store_returns_empty_list(store: PantryStore) -> None:
    assert store.list_items() == []


def test_create_returns_item_with_generated_id(store: PantryStore) -> None:
    item = store.create_item(OLIVE_OIL)
    assert item.id is not None
    assert item.name == "Olive Oil"
    assert item.brand == "California Olive Ranch"
    assert item.category == Category.condiments
    assert item.storage_location == StorageLocation.pantry
    assert item.quantity == 1.0
    assert item.unit == Unit.bottle
    assert item.created_at is not None
    assert item.updated_at is not None


def test_list_returns_all_items(store: PantryStore) -> None:
    store.create_item(OLIVE_OIL)
    store.create_item(MILK)
    assert len(store.list_items()) == 2


def test_list_filters_by_pantry_location(store: PantryStore) -> None:
    store.create_item(OLIVE_OIL)
    store.create_item(MILK)
    results = store.list_items(location=StorageLocation.pantry)
    assert len(results) == 1
    assert results[0].name == "Olive Oil"


def test_list_filters_by_fridge_location(store: PantryStore) -> None:
    store.create_item(OLIVE_OIL)
    store.create_item(MILK)
    results = store.list_items(location=StorageLocation.fridge)
    assert len(results) == 1
    assert results[0].name == "Whole Milk"


def test_list_with_no_matching_location_returns_empty(store: PantryStore) -> None:
    store.create_item(OLIVE_OIL)
    assert store.list_items(location=StorageLocation.freezer) == []


def test_get_returns_existing_item(store: PantryStore) -> None:
    created = store.create_item(OLIVE_OIL)
    fetched = store.get_item(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.name == "Olive Oil"


def test_get_missing_item_returns_none(store: PantryStore) -> None:
    assert store.get_item(uuid4()) is None


def test_update_patches_only_provided_fields(store: PantryStore) -> None:
    created = store.create_item(OLIVE_OIL)
    updated = store.update_item(
        created.id, PantryItemUpdate(quantity=0.5, notes="Half used")
    )
    assert updated is not None
    assert updated.quantity == 0.5
    assert updated.notes == "Half used"
    assert updated.name == "Olive Oil"
    assert updated.brand == "California Olive Ranch"


def test_update_bumps_updated_at(store: PantryStore) -> None:
    created = store.create_item(OLIVE_OIL)
    updated = store.update_item(created.id, PantryItemUpdate(quantity=0.5))
    assert updated is not None
    assert updated.updated_at >= created.updated_at


def test_update_can_clear_optional_field(store: PantryStore) -> None:
    created = store.create_item(OLIVE_OIL)
    updated = store.update_item(created.id, PantryItemUpdate(brand=None))
    assert updated is not None
    assert updated.brand is None


def test_update_missing_item_returns_none(store: PantryStore) -> None:
    assert store.update_item(uuid4(), PantryItemUpdate(quantity=1.0)) is None


def test_delete_removes_item(store: PantryStore) -> None:
    created = store.create_item(OLIVE_OIL)
    assert store.delete_item(created.id) is True
    assert store.get_item(created.id) is None
    assert store.list_items() == []


def test_delete_does_not_affect_other_items(store: PantryStore) -> None:
    oil = store.create_item(OLIVE_OIL)
    milk = store.create_item(MILK)
    store.delete_item(oil.id)
    remaining = store.list_items()
    assert len(remaining) == 1
    assert remaining[0].id == milk.id


def test_delete_missing_item_returns_false(store: PantryStore) -> None:
    assert store.delete_item(uuid4()) is False


def test_data_persists_across_instances(tmp_path: Path) -> None:
    file_path = tmp_path / "pantry.json"
    store1 = PantryStore(file_path=file_path)
    created = store1.create_item(OLIVE_OIL)

    store2 = PantryStore(file_path=file_path)
    fetched = store2.get_item(created.id)
    assert fetched is not None
    assert fetched.name == "Olive Oil"
    assert fetched.id == created.id
