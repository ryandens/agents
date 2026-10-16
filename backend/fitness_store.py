from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from fitness import (
    BodyWeight,
    Exercise,
    Mutation,
    Workout,
    WorkoutInput,
    WorkoutLogInput,
    WorkoutRecordingContext,
)


class FitnessStore:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def body_weights(self, owner: str):
        with self.pool.connection() as conn:
            return [
                BodyWeight(**row)
                for row in conn.execute(
                    "SELECT id, measured_on, weight, unit FROM fitness_body_weights "
                    "WHERE owner=%s ORDER BY measured_on, created_at, id",
                    (owner,),
                ).fetchall()
            ]

    def delete_body_weight(self, owner: str, measurement_id: UUID):
        with self.pool.connection() as conn:
            conn.execute(
                "DELETE FROM fitness_body_weights WHERE owner=%s AND id=%s",
                (owner, measurement_id),
            )

    def record_from_chat(self, data: WorkoutLogInput, context: WorkoutRecordingContext):
        """Atomically record a whole log; one durable result per account/message."""
        from fastapi import HTTPException

        receipt_id = uuid5(
            NAMESPACE_URL, f"fitness-chat:{context.actor}:{context.message_id}"
        )
        names = {
            " ".join(entry.name.split()).casefold(): " ".join(entry.name.split())
            for entry in data.exercises
        }
        with self.pool.connection() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (str(receipt_id),),
            )
            prior = conn.execute(
                "SELECT actor, payload FROM fitness_mutations WHERE id=%s",
                (receipt_id,),
            ).fetchone()
            if prior:
                payload = prior["payload"]
                if (
                    prior["actor"] != context.actor
                    or payload.get("kind") != "chat-workout"
                    or payload.get("source_note") != context.source_note
                ):
                    raise HTTPException(
                        409,
                        "This message ID was already used for a different workout log. Send a new message.",
                    )
                return {**payload["result"], "already_recorded": True}
            exercises = {}
            # Consistent lock order avoids deadlocks for logs sharing exercises.
            for key, name in sorted(names.items()):
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    ("fitness-exercise:" + key,),
                )
                matches = conn.execute(
                    "SELECT id FROM fitness_exercises WHERE lower(name)=lower(%s) ORDER BY id",
                    (name,),
                ).fetchall()
                if len(matches) > 1:
                    raise HTTPException(
                        422,
                        f"Multiple exercises are named {name}. Choose a unique exercise name before recording.",
                    )
                exercise_id = (
                    matches[0]["id"]
                    if matches
                    else str(uuid5(NAMESPACE_URL, "fitness-exercise:" + key))
                )
                if not matches:
                    conn.execute(
                        "INSERT INTO fitness_exercises (id,name) VALUES (%s,%s)",
                        (exercise_id, name),
                    )
                exercises[key] = exercise_id
            workout = Workout(
                id=receipt_id,
                performed_on=data.performed_on,
                notes=data.notes,
                source_note=context.source_note,
                exercises=[
                    {
                        "exercise_id": exercises[
                            " ".join(entry.name.split()).casefold()
                        ],
                        "notes": entry.notes,
                        "sets": entry.sets,
                    }
                    for entry in data.exercises
                ],
            )
            self._write(conn, workout)
            result = {
                "id": str(workout.id),
                "performed_on": str(workout.performed_on),
                "exercises": len(workout.exercises),
                "sets": sum(len(entry.sets) for entry in workout.exercises),
                "already_recorded": False,
            }
            conn.execute(
                "INSERT INTO fitness_mutations (id,actor,payload) VALUES (%s,%s,%s)",
                (
                    receipt_id,
                    context.actor,
                    Jsonb(
                        {
                            "kind": "chat-workout",
                            "source_note": context.source_note,
                            "result": result,
                        }
                    ),
                ),
            )
            return result

    def exercises(self):
        with self.pool.connection() as conn:
            return [
                Exercise(**r)
                for r in conn.execute(
                    "SELECT id, name FROM fitness_exercises ORDER BY name"
                ).fetchall()
            ]

    def add_exercise(self, exercise: Exercise):
        with self.pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO fitness_exercises (id, name) VALUES (%s,%s) ON CONFLICT (id) DO NOTHING RETURNING id",
                (exercise.id, exercise.name),
            ).fetchone()
        return row is not None

    def list(self):
        # One snapshot for all three queries, including during concurrent edits.
        with self.pool.connection() as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            workouts = conn.execute(
                "SELECT id, performed_on, notes, source_note, revision FROM fitness_workouts ORDER BY performed_on DESC, created_at DESC, id"
            ).fetchall()
            entries = conn.execute(
                "SELECT * FROM fitness_entries ORDER BY position"
            ).fetchall()
            sets = conn.execute(
                "SELECT * FROM fitness_sets ORDER BY position"
            ).fetchall()
        by_entry = {}
        for s in sets:
            key = (s.pop("workout_id"), s.pop("entry_position"))
            s.pop("position")
            by_entry.setdefault(key, []).append(s)
        by_workout = {}
        for e in entries:
            wid, pos = e.pop("workout_id"), e.pop("position")
            e["sets"] = by_entry.get((wid, pos), [])
            by_workout.setdefault(wid, []).append(e)
        return [Workout(**w, exercises=by_workout.get(w["id"], [])) for w in workouts]

    def _write(self, conn, workout: Workout):
        conn.execute(
            "INSERT INTO fitness_workouts (id, performed_on, notes, source_note, revision) VALUES (%s,%s,%s,%s,%s)",
            (
                workout.id,
                workout.performed_on,
                workout.notes,
                workout.source_note,
                workout.revision,
            ),
        )
        for i, entry in enumerate(workout.exercises):
            conn.execute(
                "INSERT INTO fitness_entries VALUES (%s,%s,%s,%s)",
                (workout.id, i, entry.exercise_id, entry.notes),
            )
            for j, s in enumerate(entry.sets):
                conn.execute(
                    """INSERT INTO fitness_sets
                    (workout_id, entry_position, position, reps, target_reps, weight,
                     unit, load_basis, seconds, failure, phase, notes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        workout.id,
                        i,
                        j,
                        s.reps,
                        s.target_reps,
                        s.weight,
                        s.unit,
                        s.load_basis,
                        s.seconds,
                        s.failure,
                        s.phase,
                        s.notes,
                    ),
                )

    def save(self, data: WorkoutInput, workout_id: UUID | None = None):
        workout = Workout(
            **data.model_dump(), **({"id": workout_id} if workout_id else {})
        )
        with self.pool.connection() as conn:
            if workout_id:
                previous = conn.execute(
                    "DELETE FROM fitness_workouts WHERE id=%s RETURNING revision",
                    (workout_id,),
                ).fetchone()
                if previous is None:
                    return None
                workout.revision = previous["revision"] + 1
            self._write(conn, workout)
        return workout

    def delete(self, workout_id: UUID):
        with self.pool.connection() as conn:
            return (
                conn.execute(
                    "DELETE FROM fitness_workouts WHERE id=%s", (workout_id,)
                ).rowcount
                > 0
            )

    def sync(self, mutation: Mutation, actor: str):
        """Receipt and mutation commit together; retries after a lost response are safe."""
        from fastapi import HTTPException

        payload = mutation.model_dump(
            mode="json",
            exclude={"measurement"} if mutation.measurement is None else set(),
        )
        with self.pool.connection() as conn:
            inserted = conn.execute(
                "INSERT INTO fitness_mutations (id, actor, payload) VALUES (%s,%s,%s) "
                "ON CONFLICT DO NOTHING RETURNING id",
                (mutation.id, actor, Jsonb(payload)),
            ).fetchone()
            if not inserted:
                prior = conn.execute(
                    "SELECT actor, payload FROM fitness_mutations WHERE id=%s",
                    (mutation.id,),
                ).fetchone()
                if prior["actor"] != actor or prior["payload"] != payload:
                    raise HTTPException(
                        409, "Mutation ID was already used for different data"
                    )
                return
            if mutation.kind == "bodyweight":
                measurement = mutation.measurement
                row = conn.execute(
                    "INSERT INTO fitness_body_weights (owner,id,measured_on,weight,unit) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
                    (
                        actor,
                        measurement.id,
                        measurement.measured_on,
                        measurement.weight,
                        measurement.unit,
                    ),
                ).fetchone()
                if row is None:
                    raise HTTPException(
                        409, "Weight entry already exists; refresh your history"
                    )
                return
            if mutation.kind == "exercise":
                exercise = mutation.exercise
                conn.execute(
                    "INSERT INTO fitness_exercises (id,name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (exercise.id, exercise.name),
                )
                row = conn.execute(
                    "SELECT name FROM fitness_exercises WHERE id=%s", (exercise.id,)
                ).fetchone()
                if row["name"] != exercise.name:
                    raise HTTPException(409, "Exercise identity has changed")
                return
            workout = mutation.workout
            # Serialize creation too: an absent row cannot be SELECT FOR UPDATE locked.
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (str(workout.id),),
            )
            row = conn.execute(
                "SELECT revision FROM fitness_workouts WHERE id=%s FOR UPDATE",
                (workout.id,),
            ).fetchone()
            if (row["revision"] if row else 0) != workout.revision:
                raise HTTPException(
                    409,
                    "This workout changed on another device. Your local copy is safe.",
                )
            if mutation.kind == "delete":
                conn.execute("DELETE FROM fitness_workouts WHERE id=%s", (workout.id,))
                return
            for entry in workout.exercises:
                if not conn.execute(
                    "SELECT id FROM fitness_exercises WHERE id=%s", (entry.exercise_id,)
                ).fetchone():
                    raise HTTPException(422, "Exercise has not synced yet")
            conn.execute("DELETE FROM fitness_workouts WHERE id=%s", (workout.id,))
            self._write(
                conn, workout.model_copy(update={"revision": workout.revision + 1})
            )
