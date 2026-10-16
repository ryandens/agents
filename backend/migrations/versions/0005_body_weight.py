"""Account-scoped body weight measurements, independent of workouts."""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE fitness_body_weights (
            owner TEXT NOT NULL,
            id UUID NOT NULL,
            measured_on DATE NOT NULL,
            weight DOUBLE PRECISION NOT NULL CHECK (weight > 0 AND weight <= 2000),
            unit TEXT NOT NULL CHECK (unit IN ('lbs', 'kg')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (owner, id)
        );
        CREATE INDEX fitness_body_weights_owner_date ON fitness_body_weights (owner, measured_on)
    """)


def downgrade():
    op.execute("DROP TABLE fitness_body_weights")
