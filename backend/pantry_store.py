from datetime import UTC, date, datetime
from enum import Enum
from uuid import UUID

from psycopg import sql
from psycopg_pool import ConnectionPool

from pantry import PantryItem, PantryItemCreate, PantryItemUpdate, StorageLocation

# Every column, in the order the INSERT below writes them. Named rather than selected
# with `*` so a column added to the table cannot silently change what a query returns.
_COLUMNS = (
    "id",
    "name",
    "brand",
    "category",
    "storage_location",
    "quantity",
    "unit",
    "purchase_date",
    "expiration_date",
    "notes",
    "created_at",
    "updated_at",
)

_COLUMN_LIST = sql.SQL(", ").join(sql.Identifier(c) for c in _COLUMNS)

# Rows come back in creation order, which is what the file-backed store happened to
# produce and what the pantry page renders. id breaks ties so two items created in the
# same microsecond still sort deterministically.
_ORDER_BY = sql.SQL("ORDER BY created_at, id")


# What a PantryItem field can hold, and — once the enums are mapped to their values —
# what psycopg is handed as a query parameter. Spelled out rather than left as Any so
# adding a field of some type this cannot carry is a visible change here.
type FieldValue = str | float | UUID | date | datetime | Enum | None
type QueryParam = str | float | UUID | date | datetime | None


def _param(value: FieldValue) -> QueryParam:
    """Adapt a model value to something psycopg can send.

    Only the enums need help: Category/Unit/StorageLocation subclass str, but psycopg
    resolves a dumper by exact type and so would not find one for the subclass.
    """
    return value.value if isinstance(value, Enum) else value


class PantryStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def list_items(self, location: StorageLocation | None = None) -> list[PantryItem]:
        query = sql.SQL("SELECT {cols} FROM pantry_items").format(cols=_COLUMN_LIST)
        params: tuple[QueryParam, ...] = ()
        if location is not None:
            query = sql.SQL("{q} WHERE storage_location = %s").format(q=query)
            params = (location.value,)
        query = sql.SQL("{q} {order}").format(q=query, order=_ORDER_BY)

        with self._pool.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [PantryItem.model_validate(row) for row in rows]

    def get_item(self, item_id: UUID) -> PantryItem | None:
        query = sql.SQL("SELECT {cols} FROM pantry_items WHERE id = %s").format(
            cols=_COLUMN_LIST
        )
        with self._pool.connection() as conn:
            row = conn.execute(query, (item_id,)).fetchone()
        return PantryItem.model_validate(row) if row else None

    def create_item(self, data: PantryItemCreate) -> PantryItem:
        item = PantryItem(**data.model_dump())
        values = tuple(_param(getattr(item, column)) for column in _COLUMNS)
        query = sql.SQL(
            "INSERT INTO pantry_items ({cols}) VALUES ({placeholders}) RETURNING {cols}"
        ).format(
            cols=_COLUMN_LIST,
            placeholders=sql.SQL(", ").join(sql.Placeholder() * len(_COLUMNS)),
        )
        with self._pool.connection() as conn:
            row = conn.execute(query, values).fetchone()
        return PantryItem.model_validate(row)

    def update_item(self, item_id: UUID, data: PantryItemUpdate) -> PantryItem | None:
        # exclude_unset, not exclude_none: PATCH {"brand": null} clears the brand, while
        # a PATCH that omits "brand" leaves it alone. Only the fields the caller actually
        # sent reach the SET list.
        patch = data.model_dump(exclude_unset=True)

        # Validate that NOT NULL columns are not explicitly set to None. Raising early
        # gives a clear error instead of letting a constraint violation reach PostgreSQL.
        not_null_columns = ("name", "category", "storage_location", "quantity", "unit")
        for column in not_null_columns:
            if column in patch and patch[column] is None:
                raise ValueError(f"Field '{column}' cannot be set to null")

        # Always assigned, which also guarantees the SET list is never empty — a PATCH
        # with an empty body is a no-op that still touches the row, as it was before.
        patch["updated_at"] = datetime.now(UTC)

        assignments = sql.SQL(", ").join(
            sql.SQL("{col} = %s").format(col=sql.Identifier(column)) for column in patch
        )
        query = sql.SQL(
            "UPDATE pantry_items SET {assignments} WHERE id = %s RETURNING {cols}"
        ).format(assignments=assignments, cols=_COLUMN_LIST)
        values = tuple(_param(value) for value in patch.values()) + (item_id,)

        with self._pool.connection() as conn:
            row = conn.execute(query, values).fetchone()
        return PantryItem.model_validate(row) if row else None

    def delete_item(self, item_id: UUID) -> bool:
        with self._pool.connection() as conn:
            cursor = conn.execute("DELETE FROM pantry_items WHERE id = %s", (item_id,))
            return cursor.rowcount > 0
