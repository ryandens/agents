import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pantry import PantryItem, PantryItemCreate, PantryItemUpdate, StorageLocation

_DEFAULT_FILE = Path(__file__).parent / "data" / "pantry.json"


class PantryStore:
    def __init__(self, file_path: Path = _DEFAULT_FILE) -> None:
        self._file = file_path

    def _load(self) -> list[PantryItem]:
        if not self._file.exists():
            return []
        with open(self._file) as f:
            data = json.load(f)
        return [PantryItem.model_validate(item) for item in data]

    def _save(self, items: list[PantryItem]) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._file, "w") as f:
            json.dump([item.model_dump(mode="json") for item in items], f, indent=2)

    def list_items(self, location: StorageLocation | None = None) -> list[PantryItem]:
        items = self._load()
        if location is not None:
            items = [i for i in items if i.storage_location == location]
        return items

    def get_item(self, item_id: UUID) -> PantryItem | None:
        return next((i for i in self._load() if i.id == item_id), None)

    def create_item(self, data: PantryItemCreate) -> PantryItem:
        items = self._load()
        item = PantryItem(**data.model_dump())
        items.append(item)
        self._save(items)
        return item

    def update_item(self, item_id: UUID, data: PantryItemUpdate) -> PantryItem | None:
        items = self._load()
        for idx, item in enumerate(items):
            if item.id == item_id:
                patch = data.model_dump(exclude_unset=True)
                patch["updated_at"] = datetime.now(UTC)
                updated = item.model_copy(update=patch)
                items[idx] = updated
                self._save(items)
                return updated
        return None

    def delete_item(self, item_id: UUID) -> bool:
        items = self._load()
        filtered = [i for i in items if i.id != item_id]
        if len(filtered) == len(items):
            return False
        self._save(filtered)
        return True
