import { expect, it } from "vitest";
import { exerciseProgress, weightProgress } from "../progress";
import { newSet, type Workout } from "../types";

it("sorts body weight by date and converts mixed units consistently", () => {
  const points = weightProgress([
    {id:"later",measured_on:"2026-10-15",weight:80,unit:"kg"},
    {id:"earlier",measured_on:"2026-10-01",weight:180,unit:"lbs"},
  ],"lbs");
  expect(points.map(point => point.id)).toEqual(["earlier","later"]);
  expect(points[1].value).toBeCloseTo(176.37,2);
});

it("charts actual working sets without mixing load conventions, missing values, or warmups", () => {
  const workouts: Workout[] = [{performed_on:"2026-10-15",notes:"",source_note:"",exercises:[
    {exercise_id:"press",notes:"",sets:[
      {...newSet(),weight:20,unit:"kg",load_basis:"per_hand",reps:7,target_reps:12},
      {...newSet(),weight:50,unit:"lbs",load_basis:"per_hand",reps:6},
      {...newSet(),weight:150,load_basis:"total",reps:5},
      {...newSet(),weight:200,load_basis:"per_hand",phase:"warmup",reps:30},
      newSet(),
    ]},
    {exercise_id:"cycle",notes:"",sets:[{...newSet(),seconds:600}]},
  ]}];
  expect(exerciseProgress(workouts,"press", {metric:"weight",basis:"per_hand",unit:"lbs"})[0].value).toBe(50);
  expect(exerciseProgress(workouts,"press", {metric:"reps",basis:"per_hand",unit:"lbs"})[0].value).toBe(7);
  expect(exerciseProgress(workouts,"cycle", {metric:"seconds",basis:"total",unit:"lbs"})[0].value).toBe(600);
  expect(exerciseProgress(workouts,"press", {metric:"seconds",basis:"total",unit:"lbs"})).toEqual([]);
  expect(exerciseProgress([...workouts,...workouts],"press", {metric:"weight",basis:"total",unit:"lbs"})).toHaveLength(1);
});
