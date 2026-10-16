import {expect,it} from "vitest";
import {lastExerciseSet,copyMeasurements} from "../setDefaults";
import {newSet,type Workout} from "../types";
const workout = (id:string,date:string,reps:number|null):Workout => ({id,performed_on:date,notes:"",source_note:"",exercises:[{exercise_id:"press",notes:"",sets:[{...newSet(),reps}]}]});
it("uses the latest matching session, excludes the current workout and future dates", () => {
  const draft = workout("current","2000-02-01",99);
  const history = [workout("older","2000-01-01",8),workout("latest","2000-01-31",10),draft,workout("future","2000-03-01",12)];
  expect(lastExerciseSet(history,"press",draft)?.set.reps).toBe(10);
  expect(lastExerciseSet(history,"other",draft)).toBeNull();
});
it("prefers a working set, preserves duration and load basis, and resets observations", () => {
  const w = workout("past","2000-01-01",5);
  w.exercises[0].sets[0].phase = "warmup";
  w.exercises[0].sets.push({...newSet(),seconds:45,load_basis:"bodyweight",failure:true,notes:"old",target_reps:10});
  const last = lastExerciseSet([w],"press",workout("draft","2000-02-01",null))!;
  expect(copyMeasurements(last.set)).toMatchObject({seconds:45,reps:null,weight:null,load_basis:"bodyweight",failure:null,notes:"",target_reps:null,phase:"work"});
});
it("does not reach past a blank latest session to invent measurements", () => {
  expect(lastExerciseSet([workout("old","2000-01-01",8),workout("latest","2000-01-02",null)],"press",workout("draft","2000-02-01",null))).toBeNull();
});

it("converts existing kilogram history to pounds for new sets", () => {
  expect(copyMeasurements({...newSet(),weight:20,unit:"kg"})).toMatchObject({weight:44.09,unit:"lbs"});
});
