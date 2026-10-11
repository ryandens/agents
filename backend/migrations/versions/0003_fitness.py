"""Normalized workout log. Personal samples are imported explicitly, not in migrations."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE fitness_exercises (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL CHECK (length(trim(name)) > 0)
        );
        CREATE TABLE fitness_workouts (
            id UUID PRIMARY KEY,
            performed_on DATE NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            source_note TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ON fitness_workouts (performed_on DESC);
        CREATE TABLE fitness_entries (
            workout_id UUID REFERENCES fitness_workouts(id) ON DELETE CASCADE,
            position INTEGER NOT NULL CHECK (position >= 0),
            exercise_id TEXT NOT NULL REFERENCES fitness_exercises(id),
            notes TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (workout_id, position)
        );
        CREATE TABLE fitness_sets (
            workout_id UUID NOT NULL,
            entry_position INTEGER NOT NULL,
            position INTEGER NOT NULL CHECK (position >= 0),
            reps INTEGER CHECK (reps >= 0),
            target_reps INTEGER CHECK (target_reps > 0),
            weight DOUBLE PRECISION CHECK (weight >= 0 AND weight < 'Infinity'::float8),
            unit TEXT NOT NULL CHECK (unit IN ('lbs', 'kg')),
            load_basis TEXT NOT NULL CHECK (load_basis IN ('unspecified','total','per_hand','machine','bodyweight')),
            seconds INTEGER CHECK (seconds > 0),
            failure BOOLEAN,
            phase TEXT NOT NULL CHECK (phase IN ('work','warmup','cooldown')),
            notes TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (workout_id, entry_position, position),
            FOREIGN KEY (workout_id, entry_position)
                REFERENCES fitness_entries(workout_id, position) ON DELETE CASCADE,
            CHECK (load_basis != 'bodyweight' OR weight IS NULL)
        );
        CREATE TABLE fitness_imports (
            key TEXT PRIMARY KEY,
            imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade():
    op.execute(
        "DROP TABLE fitness_imports, fitness_sets, fitness_entries, fitness_workouts, fitness_exercises"
    )
