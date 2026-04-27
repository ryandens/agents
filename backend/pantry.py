from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


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
    brand: Optional[str] = None
    category: Category
    storage_location: StorageLocation
    quantity: float
    unit: Unit
    purchase_date: Optional[date] = None
    expiration_date: Optional[date] = None
    notes: Optional[str] = None


class PantryItemUpdate(BaseModel):
    name: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[Category] = None
    storage_location: Optional[StorageLocation] = None
    quantity: Optional[float] = None
    unit: Optional[Unit] = None
    purchase_date: Optional[date] = None
    expiration_date: Optional[date] = None
    notes: Optional[str] = None


class PantryItem(PantryItemCreate):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
