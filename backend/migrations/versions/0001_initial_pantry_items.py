"""initial pantry_items table

Revision ID: 0001
Revises:
Created: 2026-07-31

The schema the app used to create for itself at startup, moved here unchanged. It is
written as raw SQL rather than op.create_table() because that is what it already was —
there are no SQLAlchemy models to describe it with, and the SQL is the thing being
reviewed.

The enums (category, unit, storage_location) are TEXT, not a Postgres ENUM type or a
CHECK constraint: Unit alone has twenty members and both it and Category are expected to
grow, so a database-level constraint would turn every new member into a migration for no
protection the API layer does not already give. Nothing writes to this table except the
app, and pydantic validates on the way in and on the way out.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE pantry_items (
            id                UUID PRIMARY KEY,
            name              TEXT NOT NULL,
            brand             TEXT,
            category          TEXT NOT NULL,
            storage_location  TEXT NOT NULL,
            quantity          DOUBLE PRECISION NOT NULL,
            unit              TEXT NOT NULL,
            purchase_date     DATE,
            expiration_date   DATE,
            notes             TEXT,
            created_at        TIMESTAMPTZ NOT NULL,
            updated_at        TIMESTAMPTZ NOT NULL
        )
    """)
    # The one query shape the API filters on.
    op.execute("""
        CREATE INDEX pantry_items_storage_location_idx
            ON pantry_items (storage_location)
    """)


def downgrade() -> None:
    # Drops the pantry. Only reachable by running `alembic downgrade` deliberately, and
    # the cluster keeps 7 days of point-in-time recovery behind it.
    op.execute("DROP TABLE pantry_items")
