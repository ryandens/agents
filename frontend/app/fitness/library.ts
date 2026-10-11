import type { Exercise, SetRecord } from "./types";

export const equipment = [
  {name:"Machines",icon:"▤"}, {name:"Free weights",icon:"🏋"},
  {name:"Cables",icon:"↕"}, {name:"Bodyweight",icon:"◯"}, {name:"Cardio",icon:"🚴"},
];
export const areas = [
  {name:"Legs",icon:"🦵"}, {name:"Arms",icon:"💪"}, {name:"Chest",icon:"◈"},
  {name:"Back",icon:"↔"}, {name:"Shoulders",icon:"↑"}, {name:"Core",icon:"◎"},
];
export interface LibraryExercise extends Exercise {
  equipment: string; area: string; mode: "reps" | "time"; basis: SetRecord["load_basis"];
}
// Browsing metadata describes movements, never recorded performance. IDs stay stable.
const groups: [string,string,string[]][] = [
  ["Machines","Chest",["Machine chest press","Machine chest fly"]],
  ["Machines","Legs",["Leg press","Leg extension","Seated leg curl","Machine calf raise"]],
  ["Machines","Back",["Lat pulldown","Machine seated row"]],
  ["Machines","Shoulders",["Machine shoulder press"]],
  ["Machines","Arms",["Machine biceps curl","Machine triceps extension"]],
  ["Machines","Core",["Machine abdominal crunch"]],
  ["Free weights","Chest",["Barbell bench press","Dumbbell bench press","Incline dumbbell press"]],
  ["Free weights","Legs",["Barbell squat","Barbell deadlift","Dumbbell lunge","Goblet squat"]],
  ["Free weights","Back",["Dumbbell row","Barbell row"]],
  ["Free weights","Arms",["Dumbbell curl","Hammer curl","Barbell curl","Dumbbell triceps extension"]],
  ["Free weights","Shoulders",["Dumbbell shoulder press","Dumbbell lateral raise"]],
  ["Cables","Arms",["Cable triceps pushdown","Cable biceps curl"]],
  ["Cables","Chest",["Cable chest fly"]], ["Cables","Back",["Cable seated row","Cable face pull"]],
  ["Cables","Core",["Cable crunch"]],
  ["Bodyweight","Chest",["Push-up"]], ["Bodyweight","Back",["Pull-up"]],
  ["Bodyweight","Legs",["Bodyweight squat","Bodyweight lunge"]],
  ["Bodyweight","Arms",["Dip"]], ["Bodyweight","Core",["Crunch","Plank","Side plank","Leg raise"]],
  ["Cardio","",["Indoor cycle","Treadmill","Elliptical","Rowing machine","Stair climber"]],
];
export const library: LibraryExercise[] = groups.flatMap(([equipment,area,names]) => names.map(name => ({
  id:`library-${name.toLowerCase().replaceAll(" ","-")}`, name, equipment, area,
  mode: equipment === "Cardio" || name.includes("plank") || name === "Plank" ? "time" : "reps",
  basis: equipment === "Bodyweight" ? "bodyweight" : equipment === "Machines" || equipment === "Cables" ? "machine" : "unspecified",
})));
export const libraryEntry = (id: string) => library.find(e => e.id === id);
