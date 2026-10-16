"""Entirely synthetic demo workouts; no personal workout history is embedded."""

from fitness import Exercise, SetRecord, Workout, WorkoutExercise

EXERCISES = [
    Exercise(id=key, name=name)
    for key, name in [
        ("chest-press", "Chest press"),
        ("leg-press", "Leg press"),
        ("side-plank", "Side plank"),
        ("indoor-cycle", "Indoor cycle"),
        ("dumbbell-curl", "Dumbbell curl"),
    ]
]

WORKOUTS = [
    Workout(
        performed_on="2000-01-03",
        source_note="""Fictional demo session A
Chest press: target 10 reps; 10 at 35 kg, 6 at 40 kg (failure).
Indoor cycle: 6 minutes work, 2 minutes cooldown.""",
        notes="Synthetic example: actual reps differ from the target.",
        exercises=[
            WorkoutExercise(
                exercise_id="chest-press",
                sets=[
                    SetRecord(
                        reps=10,
                        target_reps=10,
                        weight=35,
                        unit="kg",
                        load_basis="machine",
                    ),
                    SetRecord(
                        reps=6,
                        target_reps=10,
                        weight=40,
                        unit="kg",
                        load_basis="machine",
                        failure=True,
                    ),
                ],
            ),
            WorkoutExercise(
                exercise_id="indoor-cycle",
                sets=[SetRecord(seconds=360), SetRecord(seconds=120, phase="cooldown")],
            ),
        ],
    ),
    Workout(
        performed_on="2000-01-08",
        source_note="""Fictional demo session B
Side plank: 20 seconds; sides and set count unspecified.
Dumbbell curl: 12 reps at 15 lbs, 9 reps at 20 lbs; both arms.
Load convention unspecified.""",
        notes="Synthetic example: ambiguous observations remain notes.",
        exercises=[
            WorkoutExercise(
                exercise_id="side-plank",
                notes="20 seconds; sides and number of sets not recorded.",
            ),
            WorkoutExercise(
                exercise_id="dumbbell-curl",
                notes="Both arms; load convention unspecified. Reps are not doubled.",
                sets=[
                    SetRecord(reps=12, weight=15),
                    SetRecord(reps=9, weight=20),
                ],
            ),
        ],
    ),
    Workout(
        performed_on="2000-01-12",
        source_note="""Fictional demo session C
Chest press: 11 reps at 35 kg.
Leg press: 12 reps at 65 kg, 10 reps with load unrecorded.""",
        notes="Synthetic example: missing load stays unknown.",
        exercises=[
            WorkoutExercise(
                exercise_id="chest-press",
                sets=[SetRecord(reps=11, weight=35, unit="kg", load_basis="machine")],
            ),
            WorkoutExercise(
                exercise_id="leg-press",
                sets=[
                    SetRecord(reps=12, weight=65, unit="kg", load_basis="machine"),
                    SetRecord(reps=10, unit="kg", load_basis="machine"),
                ],
            ),
        ],
    ),
]
