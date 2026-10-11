from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException

from auth import authenticated
from fitness import Exercise, Mutation, Workout, WorkoutInput, summarize
from fitness_store import FitnessStore

router = APIRouter(prefix="/api/fitness", dependencies=[Depends(authenticated)])


def store():
    import main

    if main.pool is None:
        raise HTTPException(503, "Fitness storage is unavailable")
    return FitnessStore(main.pool)


Store = Annotated[FitnessStore, Depends(store)]


@router.get("/exercises", response_model=list[Exercise])
def exercises(db: Store):
    return db.exercises()


@router.post("/exercises", response_model=Exercise, status_code=201)
def add_exercise(data: Exercise, db: Store):
    if not db.add_exercise(data):
        raise HTTPException(409, "Exercise ID already exists")
    return data


@router.get("/workouts", response_model=list[Workout])
def workouts(db: Store):
    return db.list()


def validate_exercises(data, db):
    known = {e.id for e in db.exercises()}
    if any(e.exercise_id not in known for e in data.exercises):
        raise HTTPException(422, "Choose an existing exercise or create it first")


@router.post("/workouts", response_model=Workout, status_code=201)
def create(data: WorkoutInput, db: Store):
    validate_exercises(data, db)
    return db.save(data)


@router.put("/workouts/{workout_id}", response_model=Workout)
def update(workout_id: UUID, data: WorkoutInput, db: Store):
    validate_exercises(data, db)
    result = db.save(data, workout_id)
    if result is None:
        raise HTTPException(404, "Workout not found")
    return result


@router.delete("/workouts/{workout_id}", status_code=204)
def delete(workout_id: UUID, db: Store):
    if not db.delete(workout_id):
        raise HTTPException(404, "Workout not found")


@router.post("/import-samples")
def import_samples(db: Store):
    return {"imported": db.import_samples()}


@router.get("/summary")
def summary(db: Store):
    workouts = db.list()
    return {"workouts": len(workouts), "exercises": summarize(workouts, db.exercises())}


@router.post("/sync")
def sync(
    data: Mutation,
    db: Store,
    user: Annotated[dict, Depends(authenticated)],
    owner: Annotated[str, Header(alias="X-Fitness-Owner")],
):
    if owner != user["sub"]:
        raise HTTPException(
            403, "Sign in with the original account to sync these workouts"
        )
    db.sync(data, user["sub"])
    return {"acknowledged": str(data.id)}
