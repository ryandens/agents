import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { changeLog, emptyLog, type LocalLog } from "../database";
import { ensureLibraryExercise, createExercise, deleteWorkout, localSummary, resolveConflict, saveWorkout, syncLog } from "../offline";
import { newSet, type Workout } from "../types";

vi.mock("../database", async importOriginal => {
  const actual = await importOriginal<typeof import("../database")>();
  return {...actual,changeLog:vi.fn()};
});
let accounts: Map<string,LocalLog>;
beforeEach(() => {
  accounts = new Map();
  vi.mocked(changeLog).mockImplementation(async (owner,update) => {
    const log = structuredClone(accounts.get(owner) ?? emptyLog());
    update?.(log);
    if (update) log.generation++;
    accounts.set(owner,log);
    return structuredClone(log);
  });
});
afterEach(() => vi.unstubAllGlobals());
const workout = ():Workout => ({id:crypto.randomUUID(),revision:0,performed_on:"2000-01-01",notes:"",source_note:"",
  exercises:[{exercise_id:"press",notes:"",sets:[{...newSet(),reps:7,target_reps:8,failure:true}]}]});
const response = (data:unknown,status=200) => ({ok:status===200,status,json:async () => data});
const read = () => changeLog("a");

it("partitions accounts and persists edits with ordered expected revisions", async () => {
  await createExercise("a","Press");
  const w = workout();
  await saveWorkout("a",w);
  await saveWorkout("a",{...(await read()).workouts[0],notes:"second version"});
  const log = await read();
  expect(log.queue.map(m => m.kind)).toEqual(["exercise","save","save"]);
  expect(log.queue.flatMap(m => m.kind==="save" ? [m.workout.revision] : [])).toEqual([0,1]);
  expect((await changeLog("b")).queue).toEqual([]);
  expect(localSummary({...log,exercises:[{id:"press",name:"Press"}]}).exercises[0].reps).toBe(7);
});

it("retries the same operation after a lost acknowledgement without losing a later edit", async () => {
  const w = workout();
  await saveWorkout("a",w);
  const first = (await read()).queue[0];
  const fetch = vi.fn(async (url:string) => {
    if (url === "/api/auth/me") return response({sub:"a"});
    throw new TypeError("lost response");
  });
  vi.stubGlobal("fetch",fetch);
  await expect(syncLog("a")).rejects.toThrow("API unreachable");
  await saveWorkout("a",{...(await read()).workouts[0],notes:"later edit"});
  expect((await read()).queue[0].id).toBe(first.id);
  const sent: string[] = [];
  fetch.mockImplementation(async (url:string, ...args:unknown[]) => {
    if (url === "/api/auth/me") return response({sub:"a"});
    if (url === "/api/fitness/sync") {
      const op = JSON.parse((args[0] as RequestInit).body as string);
      sent.push(op.id);
      return response({acknowledged:op.id});
    }
    return response(url.endsWith("workouts") ? [{...w,revision:2,notes:"later edit"}] : []);
  });
  await syncLog("a");
  expect(sent[0]).toBe(first.id);
  expect((await read()).queue).toEqual([]);
  expect((await read()).workouts[0].notes).toBe("later edit");
});

it("does not upload under a different account or discard expired-session work", async () => {
  await saveWorkout("a",workout());
  const fetch = vi.fn(async () => response({sub:"b"}));
  vi.stubGlobal("fetch",fetch);
  await expect(syncLog("a")).rejects.toThrow("different account");
  expect(fetch).toHaveBeenCalledTimes(1);
  fetch.mockResolvedValue(response({},401));
  await expect(syncLog("a")).rejects.toThrow("Sign in");
  expect((await read()).queue).toHaveLength(1);
});

it("does not let a server refresh overwrite a new local save", async () => {
  vi.stubGlobal("fetch",vi.fn(async (url:string) => {
    if (url==="/api/auth/me") return response({sub:"a"});
    if (url.endsWith("workouts")) await saveWorkout("a",workout());
    return response([]);
  }));
  await syncLog("a");
  expect((await read()).workouts).toHaveLength(1);
  expect((await read()).queue).toHaveLength(1);
});

it("preserves failed/conflicting mutations, then can keep the local version as a copy", async () => {
  await saveWorkout("a",workout());
  vi.stubGlobal("fetch",vi.fn(async (url:string) => url==="/api/auth/me"
    ? response({sub:"a"}) : response({detail:"Conflict"},409)));
  await expect(syncLog("a")).rejects.toThrow("Conflict");
  const log = await read();
  const oldId = log.workouts[0].id;
  await resolveConflict("a",log.queue[0],true);
  const resolved = await read();
  expect(resolved.queue).toHaveLength(1);
  expect(resolved.workouts[0].id).not.toBe(oldId);
  expect(resolved.workouts[0].exercises).toEqual(log.workouts[0].exercises);
});

it("queues offline deletion after an unsynced creation", async () => {
  await saveWorkout("a",workout());
  await deleteWorkout("a",(await read()).workouts[0]);
  expect((await read()).workouts).toEqual([]);
  expect((await read()).queue.map(m=>m.kind)).toEqual(["save","delete"]);
});

it("rejects invalid local data before putting it in the outbox",async () => {
  const w = workout();
  w.exercises[0].sets[0].reps = -1;
  await expect(saveWorkout("a",w)).rejects.toThrow("Check set values");
  expect((await read()).queue).toEqual([]);
});

it("does not discard a queued deletion when asked to copy a missing local workout", async () => {
  await saveWorkout("a",workout());
  await deleteWorkout("a",(await read()).workouts[0]);
  const before = await read();
  await expect(resolveConflict("a",before.queue[1],true)).rejects.toThrow("no local workout");
  expect((await read()).queue).toEqual(before.queue);
});


it("registers an offline library selection only once, independently per account", async () => {
  const exercise = {id:"library-leg-press",name:"Leg press"};
  await ensureLibraryExercise("a",exercise);
  await ensureLibraryExercise("a",exercise);
  expect((await read()).exercises).toEqual([exercise]);
  expect((await read()).queue).toHaveLength(1);
  expect((await changeLog("b")).exercises).toEqual([]);
  await ensureLibraryExercise("b",exercise);
  expect((await changeLog("b")).queue).toHaveLength(1);
});
