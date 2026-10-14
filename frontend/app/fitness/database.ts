import type { Exercise, Workout } from "./types";

export type Mutation = { id: string; kind: "save" | "delete"; workout: Workout } | { id: string; kind: "exercise"; exercise: Exercise };
export interface LocalLog {
  workouts: Workout[]; exercises: Exercise[]; queue: Mutation[];
  draft: Workout | null; generation: number; lastSync: string | null;
}
export const emptyLog = (): LocalLog => ({workouts:[], exercises:[], queue:[], draft:null, generation:0, lastSync:null});
let database: Promise<IDBDatabase> | undefined;
function open(): Promise<IDBDatabase> {
  if (!database) database = new Promise((resolve, reject) => {
    const request = indexedDB.open("agents-fitness", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("accounts");
    request.onsuccess = () => {
      request.result.onversionchange = () => { request.result.close(); database = undefined; };
      resolve(request.result);
    };
    request.onerror = () => { database = undefined; reject(request.error); };
    request.onblocked = () => { database = undefined; reject(new Error("Close other app tabs and retry local storage.")); };
  });
  return database;
}
// A single read/write transaction makes local records + outbox changes indivisible,
// and serializes updates from multiple tabs. Resolve only after disk commit.
export async function changeLog(owner: string, update?: (log: LocalLog) => void): Promise<LocalLog> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("accounts", update ? "readwrite" : "readonly");
    const store = tx.objectStore("accounts");
    const request = store.get(owner);
    let log: LocalLog;
    request.onsuccess = () => {
      log = request.result ?? emptyLog();
      if (update) {
        try { update(log); log.generation++; store.put(log, owner); }
        catch (error) { tx.abort(); reject(error); }
      }
    };
    tx.oncomplete = () => { resolve(log); if (update) window.dispatchEvent(new Event("fitness-local-change")); };
    const rejectTransaction = () => reject(tx.error ?? new Error("Could not save on this device. Keep this page open and export your draft."));
    tx.onerror = rejectTransaction;
    tx.onabort = rejectTransaction;
  });
}
