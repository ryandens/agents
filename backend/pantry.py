from datetime import UTC, date, datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class StorageLocation(str, Enum):
    pantry = "pantry"
    fridge = "fridge"
    freezer = "freezer"


class Category(str, Enum):
    produce = "produce"
    dairy = "dairy"
    meat = "meat"
    seafood = "seafood"
    grains = "grains"
    legumes = "legumes"
    condiments = "condiments"
    spices = "spices"
    beverages = "beverages"
    snacks = "snacks"
    baking = "baking"
    canned = "canned"
    frozen = "frozen"
    other = "other"


class Unit(str, Enum):
    # Weight
    lbs = "lbs"
    oz = "oz"
    kg = "kg"
    g = "g"
    # Volume
    cups = "cups"
    tbsp = "tbsp"
    tsp = "tsp"
    fl_oz = "fl_oz"
    ml = "ml"
    liters = "liters"
    gallons = "gallons"
    # Count / container
    count = "count"
    bunch = "bunch"
    head = "head"
    clove = "clove"
    loaf = "loaf"
    can = "can"
    bottle = "bottle"
    box = "box"
    bag = "bag"
    jar = "jar"


class PantryItemCreate(BaseModel):
    name: str
    brand: str | None = None
    category: Category
    storage_location: StorageLocation
    quantity: float
    unit: Unit
    purchase_date: date | None = None
    expiration_date: date | None = None
    notes: str | None = None


class PantryItemUpdate(BaseModel):
    name: str | None = None
    brand: str | None = None
    category: Category | None = None
    storage_location: StorageLocation | None = None
    quantity: float | None = None
    unit: Unit | None = None
    purchase_date: date | None = None
    expiration_date: date | None = None
    notes: str | None = None

    # Every field is Optional so that omitting it means "leave alone", but that is not
    # the same as permitting null: these five are NOT NULL in the table, so
    # PATCH {"name": null} would otherwise reach Postgres and come back as a 500.
    # Rejecting here makes it a 422 with a body naming the field, which is what a
    # malformed request deserves.
    #
    # brand, purchase_date, expiration_date and notes are deliberately absent from this
    # list — they are nullable columns, and passing null is how the API clears them.
    @field_validator(
        "name", "category", "storage_location", "quantity", "unit", mode="before"
    )
    @classmethod
    def _reject_explicit_null(cls, value: object, info: ValidationInfo) -> object:
        # Only runs for fields the caller actually sent: pydantic does not validate
        # defaults unless asked to, so an omitted field never reaches this.
        if value is None:
            raise ValueError(
                f"{info.field_name} cannot be null; omit it to leave it unchanged"
            )
        return value


class PantryItem(PantryItemCreate):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
