import { changeLog, type LocalLog, type Mutation } from "./database";
import { json, type BodyWeight, type Exercise, type Summary, type Workout } from "./types";

export async function saveWorkout(owner: string, value: Workout) {
  validateWorkout(value);
  const id = value.id ?? crypto.randomUUID();
  return changeLog(owner, log => {
    const previous = log.workouts.find(w => w.id === id);
    // Use the revision the editor opened, not an unseen newer local revision.
    if (previous && (previous.revision ?? 0) !== (value.revision ?? 0))
      throw new Error("This workout changed in another tab. Your draft is safe; export it or reopen the latest workout.");
    const mutationWorkout = {...value, id, revision: value.revision ?? 0};
    log.queue.push({id:crypto.randomUUID(),kind:"save",workout:mutationWorkout});
    log.workouts = [...log.workouts.filter(w => w.id !== id), {...mutationWorkout, revision:mutationWorkout.revision + 1}];
    log.draft = null;
  });
}
export async function deleteWorkout(owner: string, workout: Workout) {
  return changeLog(owner, log => {
    const current = log.workouts.find(w => w.id === workout.id);
    if (!current || current.revision !== workout.revision) throw new Error("Workout changed. Reload before deleting.");
    log.queue.push({id:crypto.randomUUID(),kind:"delete",workout});
    log.workouts = log.workouts.filter(w => w.id !== workout.id);
  });
}
export async function createExercise(owner: string, name: string): Promise<Exercise> {
  const clean = name.trim();
  if (!clean || clean.length > 120) throw new Error("Enter an exercise name of 1–120 characters.");
  const exercise = {id:crypto.randomUUID(),name:clean};
  await changeLog(owner, log => {
    log.exercises.push(exercise);
    log.queue.push({id:crypto.randomUUID(),kind:"exercise",exercise});
  });
  return exercise;
}
// One atomic lookup/insert keeps repeated library taps from creating duplicates.
export async function ensureLibraryExercise(owner: string, exercise: Exercise): Promise<Exercise> {
  await changeLog(owner, log => {
    if (log.exercises.some(e => e.id === exercise.id)) return;
    const record = {id:exercise.id, name:exercise.name};
    log.exercises.push(record);
    log.queue.push({id:crypto.randomUUID(),kind:"exercise",exercise:record});
  });
  return exercise;
}
export function validateWorkout(workout: Workout) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(workout.performed_on) || (!Number.isFinite(Date.parse(workout.performed_on)) || new Date(workout.performed_on).toISOString().slice(0,10) !== workout.performed_on)) throw new Error("Enter a valid workout date.");
  if (!workout.exercises.length || workout.exercises.length > 100) throw new Error("Include between 1 and 100 exercises.");
  if (workout.notes.length > 10000 || workout.source_note.length > 20000) throw new Error("Workout notes are too long.");
  for (const entry of workout.exercises) {
    if (entry.sets.length > 100 || entry.notes.length > 4000) throw new Error("Too many sets or exercise notes are too long.");
    for (const set of entry.sets) {
      for (const [value, min, max, whole] of [
        [set.reps,0,10000,true], [set.target_reps,1,10000,true],
        [set.weight,0,100000,false], [set.seconds,1,86400,true],
      ] as const) {
        if (value !== null && (!Number.isFinite(value) || value < min || value > max || (whole && !Number.isInteger(value))))
          throw new Error("Check set values: reps must be whole numbers, loads nonnegative, and durations positive.");
      }
      if (set.notes.length > 2000) throw new Error("Set notes are too long.");
      if (set.load_basis === "bodyweight" && set.weight !== null) throw new Error("Bodyweight sets should have a blank load.");
    }
  }
}
export function localSummary(log: LocalLog): Summary {
  return {workouts:log.workouts.length, exercises:log.exercises.flatMap(e => {
    const sessions = log.workouts.filter(w => w.exercises.some(x => x.exercise_id === e.id));
    if (!sessions.length) return [];
    const sets = sessions.flatMap(w => w.exercises.filter(x => x.exercise_id === e.id).flatMap(x => x.sets));
    return [{exercise_id:e.id,name:e.name,sessions:sessions.length,sets:sets.length,
      reps:sets.reduce((n,s) => n+(s.reps??0),0),seconds:sets.reduce((n,s) => n+(s.seconds??0),0),
      unknown_reps:sets.filter(s => s.reps === null && s.seconds === null).length,
      last_performed:sessions.map(w => w.performed_on).sort().at(-1)!}];
  })};
}
export class SyncError extends Error {
  constructor(message: string, public status = 0, public mutation?: Mutation) {super(message);}
}
export async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(url, {...init, cache:"no-store", signal:AbortSignal.timeout(6000)}); }
  catch {throw new SyncError("API unreachable. Saved on this device; reconnect to your VPN to sync.");}
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new SyncError(response.status === 401 ? "Sign in again to sync. Your local workouts are safe." :
      typeof body?.detail === "string" ? body.detail : "The server could not accept this change. Your local copy is safe.", response.status);
  }
  return response.json();
}
const flights = new Map<string, Promise<void>>();
export function syncLog(owner: string): Promise<void> {
  if (flights.has(owner)) return flights.get(owner)!;
  const run = async () => {
    const user = await request<{sub:string}>("/api/auth/me");
    if (user.sub !== owner) throw new SyncError("A different account is signed in. Sign in with the original account to sync.",401);
    // Do not trust navigator.onLine: Wi-Fi can be up while the private API is down.
    for (let i=0; i<100; i++) {
      const next = (await changeLog(owner)).queue[0];
      if (!next) break;
      try {
        const result = await request<{acknowledged:string}>("/api/fitness/sync",{...json("POST",next), headers:{"Content-Type":"application/json","X-Fitness-Owner":owner}});
        if (result.acknowledged !== next.id) throw new SyncError("Unexpected server acknowledgement; change remains pending.");
        await changeLog(owner, log => {log.queue = log.queue.filter(m => m.id !== next.id);});
      } catch(error) {
        if (error instanceof SyncError) error.mutation = next;
        throw error;
      }
    }
    const before = await changeLog(owner);
    const [workouts, exercises, bodyWeights] = await Promise.all([
      request<Workout[]>("/api/fitness/workouts"),request<Exercise[]>("/api/fitness/exercises"),
      request<BodyWeight[]>("/api/fitness/body-weight",{headers:{"X-Fitness-Owner":owner}}),
    ]);
    await changeLog(owner, log => {
      // Never overwrite a save made while the refresh was in flight.
      if (log.generation !== before.generation || log.queue.length) return;
      log.workouts = workouts; log.exercises = exercises; log.bodyWeights = bodyWeights; log.lastSync = new Date().toISOString();
    });
  };
  const promise = (navigator.locks ? navigator.locks.request("fitness-sync-" + owner, run) : run())
    .finally(() => flights.delete(owner));
  flights.set(owner,promise);
  return promise;
}
// Preserve the latest local version under a new identity rather than overwriting
// another device's changes. The next refresh restores the server version too.
export async function resolveConflict(owner: string, mutation: Mutation, keepCopy: boolean) {
  await changeLog(owner, log => {
    if (!("workout" in mutation)) throw new Error("Export your backup and contact support to resolve this exercise.");
    const current = log.workouts.find(w => w.id === mutation.workout.id);
    if (keepCopy && !current) throw new Error("There is no local workout to copy. Use the server version to resolve this deletion.");
    log.queue = log.queue.filter(m => !("workout" in m) || m.workout.id !== mutation.workout.id);
    log.workouts = log.workouts.filter(w => w.id !== mutation.workout.id);
    if (keepCopy && current) {
      const copy = {...current,id:crypto.randomUUID(),revision:0};
      log.queue.push({id:crypto.randomUUID(),kind:"save",workout:copy});
      log.workouts.push({...copy,revision:1});
    }
  });
}
export function downloadBackup(value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:"application/json"}));
  const link = document.createElement("a");
  link.href = url; link.download = "fitness-backup.json"; link.click();
  setTimeout(() => URL.revokeObjectURL(url),1000);
}


export async function saveBodyWeight(owner: string, measurement: BodyWeight) {
  if (!Number.isFinite(measurement.weight) || measurement.weight <= 0 || measurement.weight > 2000)
    throw new Error("Enter a weight greater than zero and at most 2,000.");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(measurement.measured_on) || !Number.isFinite(Date.parse(measurement.measured_on)) || new Date(measurement.measured_on).toISOString().slice(0,10) !== measurement.measured_on)
    throw new Error("Enter a valid measurement date.");
  await changeLog(owner, log => {
    log.bodyWeights.push(measurement);
    log.queue.push({id:crypto.randomUUID(),kind:"bodyweight",measurement});
  });
}

// A concurrent refresh may finish before a newly queued change is uploaded.
// Never report that change as saved on the server until its queue is empty.
export async function savePendingChanges(owner: string) {
  await syncLog(owner);
  if ((await changeLog(owner)).queue.length) await syncLog(owner);
  if ((await changeLog(owner)).queue.length) throw new SyncError("Changes are still pending. They will retry automatically.");
}
