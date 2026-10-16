import { pounds } from "./progress";
import { newSet, type SetRecord, type Workout } from "./types";

/** Carry measurements forward, never observations or a previous failure. */
export function copyMeasurements(set: SetRecord): SetRecord {
  return {...newSet(), reps:set.reps, weight:set.weight === null ? null : pounds(set.weight,set.unit), seconds:set.seconds,
    unit:"lbs", load_basis:set.load_basis};
}

export function lastExerciseSet(workouts: Workout[], exerciseId: string, draft: Workout) {
  const workout = workouts.filter(w => w.id !== draft.id && w.performed_on <= draft.performed_on &&
    w.exercises.some(e => e.exercise_id === exerciseId))
    .sort((a,b) => b.performed_on.localeCompare(a.performed_on))[0];
  if (!workout) return null;
  const sets = workout.exercises.filter(e => e.exercise_id === exerciseId).flatMap(e => e.sets);
  const recorded = (s:SetRecord) => s.reps !== null || s.seconds !== null || s.weight !== null;
  const set = sets.find(s => s.phase === "work" && recorded(s)) ?? sets.find(recorded);
  return set ? {set, date:workout.performed_on} : null;
}
