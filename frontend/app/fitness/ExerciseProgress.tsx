import { useState } from "react";
import type { Exercise, SetRecord, Workout } from "./types";
import { exerciseProgress, type Metric } from "./progress";
import ProgressChart from "./ProgressChart";

export default function ExerciseProgress({workouts,exercises}: {workouts:Workout[];exercises:Exercise[]}) {
  const [selected,setSelected] = useState("");
  const [metric,setMetric] = useState<Metric>("weight");
  const [basis,setBasis] = useState<SetRecord["load_basis"]>("total");
  const [unit,setUnit] = useState<"lbs" | "kg">("lbs");
  const available = exercises.filter(exercise => workouts.some(workout => workout.exercises.some(entry => entry.exercise_id === exercise.id)));
  const exercise = available.find(entry => entry.id === selected) ?? available[0];
  const bases = [...new Set(workouts.flatMap(workout => workout.exercises.filter(entry => entry.exercise_id === exercise?.id)
    .flatMap(entry => entry.sets.filter(set => set.phase === "work" && set.weight !== null).map(set => set.load_basis))))];
  const loadBasis = bases.includes(basis) ? basis : bases[0] ?? "total";
  const points = exercise ? exerciseProgress(workouts,exercise.id,{metric,basis:loadBasis,unit}) : [];
  return <section className="fitness-card space-y-4" aria-label="Exercise progress">
    <h2 className="text-lg font-semibold">Exercise progress</h2>
    <div className="flex flex-wrap gap-3">
      <label>Exercise<select value={exercise?.id ?? ""} onChange={event => setSelected(event.target.value)}>
        {!available.length && <option value="">Log a workout to get started</option>}
        {available.map(entry => <option key={entry.id} value={entry.id}>{entry.name}</option>)}
      </select></label>
      <label>Measure<select value={metric} onChange={event => setMetric(event.target.value as Metric)}><option value="weight">Heaviest set</option><option value="reps">Most reps in a set</option><option value="seconds">Longest timed set</option></select></label>
      {metric === "weight" && <>
        <label>Load convention<select value={loadBasis} onChange={event => setBasis(event.target.value as SetRecord["load_basis"])}>
          {(bases.length ? bases : ["total"]).map(value => <option key={value} value={value}>{value.replace("_"," ")}</option>)}
        </select></label>
        <label>Chart unit<select value={unit} onChange={event => setUnit(event.target.value as "lbs" | "kg")}><option value="lbs">lb</option><option value="kg">kg</option></select></label>
      </>}
    </div>
    <p className="text-sm text-stone-500">Best recorded working set per day. Warmups, cooldowns, and missing values are excluded. Reps and duration are actual results, not targets. Load comparisons keep each convention separate.</p>
    <ProgressChart points={points} label={`${exercise?.name ?? "Exercise"} progress`} unit={metric === "weight" ? unit : metric === "seconds" ? "seconds" : "reps"}/>
  </section>;
}
