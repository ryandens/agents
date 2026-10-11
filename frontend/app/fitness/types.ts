export interface Exercise { id: string; name: string }
export interface SetRecord {
  reps: number | null; target_reps: number | null; weight: number | null;
  unit: "lbs" | "kg"; load_basis: "unspecified" | "total" | "per_hand" | "machine" | "bodyweight";
  seconds: number | null; failure: boolean | null; phase: "work" | "warmup" | "cooldown"; notes: string;
}
export interface Entry { exercise_id: string; notes: string; sets: SetRecord[] }
export interface Workout { id?: string; revision?: number; performed_on: string; notes: string; source_note: string; exercises: Entry[] }
export interface Summary { workouts: number; exercises: { exercise_id: string; name: string; sessions: number; sets: number; reps: number; seconds: number; unknown_reps: number; last_performed: string }[] }
export const newSet = (): SetRecord => ({ reps: null, target_reps: null, weight: null, unit: "lbs", load_basis: "unspecified", seconds: null, failure: null, phase: "work", notes: "" });
export const json = (method: string, body?: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
