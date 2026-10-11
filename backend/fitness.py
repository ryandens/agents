"""Workout facts, not prescriptions. Null means unrecorded, never zero."""

from datetime import date
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Exercise(Model):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=120)


class SetRecord(Model):
    reps: int | None = Field(default=None, ge=0, le=10000)
    target_reps: int | None = Field(default=None, ge=1, le=10000)
    weight: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)
    unit: Literal["lbs", "kg"] = "lbs"
    load_basis: Literal["unspecified", "total", "per_hand", "machine", "bodyweight"] = (
        "unspecified"
    )
    seconds: int | None = Field(default=None, ge=1, le=86400)
    failure: bool | None = None
    phase: Literal["work", "warmup", "cooldown"] = "work"
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def bodyweight_has_no_external_load(self):
        if self.load_basis == "bodyweight" and self.weight is not None:
            raise ValueError("Use null weight for bodyweight sets")
        return self


class WorkoutExercise(Model):
    exercise_id: str = Field(min_length=1, max_length=80)
    notes: str = Field(default="", max_length=4000)
    sets: list[SetRecord] = Field(default_factory=list, max_length=100)


class WorkoutInput(Model):
    performed_on: date
    notes: str = Field(default="", max_length=10000)
    source_note: str = Field(default="", max_length=20000)
    exercises: list[WorkoutExercise] = Field(min_length=1, max_length=100)


class Workout(WorkoutInput):
    id: UUID = Field(default_factory=uuid4)
    revision: int = Field(default=1, ge=0)


def summarize(workouts: list[Workout], exercises: list[Exercise]) -> list[dict]:
    result = []
    for exercise in exercises:
        sessions = [
            w
            for w in workouts
            if any(e.exercise_id == exercise.id for e in w.exercises)
        ]
        sets = [
            s
            for w in sessions
            for e in w.exercises
            if e.exercise_id == exercise.id
            for s in e.sets
        ]
        if sessions:
            result.append(
                {
                    "exercise_id": exercise.id,
                    "name": exercise.name,
                    "sessions": len(sessions),
                    "sets": len(sets),
                    "reps": sum(s.reps or 0 for s in sets),
                    "seconds": sum(s.seconds or 0 for s in sets),
                    "unknown_reps": sum(
                        s.reps is None and s.seconds is None for s in sets
                    ),
                    "last_performed": max(w.performed_on for w in sessions),
                }
            )
    return result


class Mutation(Model):
    id: UUID
    kind: Literal["save", "delete", "exercise"]
    workout: Workout | None = None
    exercise: Exercise | None = None

    @model_validator(mode="after")
    def matching_payload(self):
        if self.kind == "exercise":
            if self.exercise is None or self.workout is not None:
                raise ValueError("Exercise mutation requires only an exercise")
        elif self.workout is None or self.exercise is not None:
            raise ValueError("Workout mutation requires only a workout")
        return self
