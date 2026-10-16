import type { BodyWeight, SetRecord, Workout } from "./types";

export type Point = {id: string; date: string; value: number};
export type Metric = "weight" | "reps" | "seconds";
export function convertWeight(value: number, from: "lbs" | "kg", to: "lbs" | "kg") {
  return from === to ? value : from === "kg" ? value * 2.2046226218 : value / 2.2046226218;
}
export function weightProgress(entries: BodyWeight[], unit: "lbs" | "kg"): Point[] {
  return entries.map(entry => ({id:entry.id,date:entry.measured_on,value:convertWeight(entry.weight,entry.unit,unit)}))
    .sort((a,b) => a.date.localeCompare(b.date));
}
export function exerciseProgress(workouts: Workout[], exercise: string, {metric,basis,unit}: {metric: Metric; basis: SetRecord["load_basis"]; unit: "lbs" | "kg"}): Point[] {
  const days = new Map<string,number>();
  for (const workout of workouts) {
    const values = workout.exercises.filter(entry => entry.exercise_id === exercise)
      .flatMap(entry => entry.sets)
      .filter(set => set.phase === "work" && (metric !== "weight" || set.load_basis === basis))
      .flatMap(set => {
        const value = set[metric];
        return value === null ? [] : [metric === "weight" ? convertWeight(value,set.unit,unit) : value];
      });
    if (values.length) days.set(workout.performed_on, Math.max(days.get(workout.performed_on) ?? -Infinity,...values));
  }
  return [...days].sort(([a],[b]) => a.localeCompare(b)).map(([date,value]) => ({id:date,date,value}));
}

export function pounds(value: number, unit: "lbs" | "kg") {
  return Number(convertWeight(value,unit,"lbs").toFixed(2));
}
