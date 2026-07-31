from datetime import date
from uuid import uuid4

from psycopg_pool import ConnectionPool

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

# Every optional field populated, so the round-trip test has something to check in each
# of the nullable columns.
FROZEN_PEAS = PantryItemCreate(
    name="Frozen Peas",
    brand="Cascadian Farm",
    category=Category.frozen,
    storage_location=StorageLocation.freezer,
    quantity=16.0,
    unit=Unit.bag,
    purchase_date=date(2026, 4, 1),
    expiration_date=date(2027, 1, 15),
    notes="Back of the drawer",
)


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


def test_data_persists_across_instances(clean_database: ConnectionPool) -> None:
    """A second store sees the first one's writes — the point of moving off the disk."""
    created = PantryStore(clean_database).create_item(OLIVE_OIL)

    fetched = PantryStore(clean_database).get_item(created.id)
    assert fetched is not None
    assert fetched.name == "Olive Oil"
    assert fetched.id == created.id


def test_round_trip_preserves_every_field(store: PantryStore) -> None:
    """Nothing is lost or coerced on the way through Postgres and back.

    The store maps enums to TEXT and dates to DATE by hand, so this is the test that
    would catch a column dropped from the INSERT or a value that no longer validates.
    """
    created = store.create_item(FROZEN_PEAS)
    fetched = store.get_item(created.id)
    assert fetched == created
    assert fetched is not None
    assert fetched.category == Category.frozen
    assert fetched.storage_location == StorageLocation.freezer
    assert fetched.unit == Unit.bag
    assert fetched.purchase_date == date(2026, 4, 1)
    assert fetched.expiration_date == date(2027, 1, 15)
    assert fetched.notes == "Back of the drawer"


def test_list_returns_items_in_creation_order(store: PantryStore) -> None:
    first = store.create_item(OLIVE_OIL)
    second = store.create_item(MILK)
    third = store.create_item(FROZEN_PEAS)
    assert [i.id for i in store.list_items()] == [first.id, second.id, third.id]
