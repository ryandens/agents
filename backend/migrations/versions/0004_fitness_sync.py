"""Offline sync revisions and durable mutation receipts."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE fitness_workouts ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
        CREATE TABLE fitness_mutations (
            id UUID PRIMARY KEY,
            actor TEXT NOT NULL,
            payload JSONB NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade():
    op.execute(
        "DROP TABLE fitness_mutations; ALTER TABLE fitness_workouts DROP COLUMN revision"
    )
