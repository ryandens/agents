"use client";
import { useEffect, useState } from "react";
import OfflineSetup from "../components/OfflineSetup";
import WorkoutForm from "./WorkoutForm";
import { json, type Workout } from "./types";
import { useAuth } from "../components/AuthProvider";
import { changeLog, emptyLog } from "./database";
import { deleteWorkout, downloadBackup, localSummary, request, resolveConflict, SyncError, syncLog } from "./offline";
import "./fitness.css";

export default function FitnessPage() {
  const { user } = useAuth();
  return <FitnessLog key={user.sub} owner={user.sub} />;
}

function FitnessLog({owner}: {owner:string}) {
  const [log, setLog] = useState(emptyLog);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [syncStatus, setSyncStatus] = useState("Saved on this device");
  const [syncError, setSyncError] = useState<SyncError | null>(null);
  const [editing, setEditing] = useState<Workout | "new" | null>(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("");
  const workouts = [...log.workouts].sort((a,b) => b.performed_on.localeCompare(a.performed_on));
  const exercises = log.exercises;
  const summary = localSummary(log);
  useEffect(() => {
    let cancelled = false;
    const read = () => changeLog(owner).then(data => {
      if (!cancelled) { setLog(data); setLoading(false); }
    }).catch(() => {
      if (!cancelled) { setError("Local storage is unavailable. Workouts cannot be safely saved on this device."); setLoading(false); }
    });
    const sync = async () => {
      if (document.visibilityState === "hidden") return;
      if (!cancelled) setSyncStatus("Checking connection…");
      try {
        await syncLog(owner);
        if (!cancelled) {setSyncError(null); setSyncStatus("Connected to the API");}
      } catch(e) {
        if (!cancelled) {
          setSyncStatus((e as Error).message);
          setSyncError(e instanceof SyncError ? e : null);
        }
      }
      await read();
    };
    void read();
    void sync();
    window.addEventListener("fitness-local-change",read);
    window.addEventListener("fitness-sync",sync);
    window.addEventListener("online",sync);
    window.addEventListener("focus",sync);
    document.addEventListener("visibilitychange",sync);
    const retry = setInterval(sync,30000);
    const refresh = setInterval(read,3000);
    return () => {
      cancelled = true; clearInterval(retry); clearInterval(refresh);
      window.removeEventListener("fitness-local-change",read);
      window.removeEventListener("fitness-sync",sync);
      window.removeEventListener("online",sync); window.removeEventListener("focus",sync);
      document.removeEventListener("visibilitychange",sync);
    };
  }, [owner]);
  function reload() { window.dispatchEvent(new Event("fitness-sync")); }
  async function importNotes() {
    setBusy(true); setError("");
    try {
      // Drain local writes before importing demo records.
      await syncLog(owner);
      const result = await request<{imported:number}>("/api/fitness/import-samples", json("POST"));
      setNotice(result.imported ? `Imported ${result.imported} workouts. These are fictional demo workouts.` : "These demo workouts have already been imported.");
      reload();
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <main className="fitness mx-auto w-full max-w-5xl px-4 sm:px-8 py-8 space-y-6">
    <header hidden={!!editing} className={editing ? "hidden" : "flex flex-wrap justify-between gap-4 items-start"}>
      <div><p className="text-xs uppercase tracking-widest text-emerald-700 dark:text-emerald-400 font-semibold">Your training log</p><h1 className="text-3xl font-semibold mt-2">Fitness</h1><p className="text-stone-500 mt-2">One workout. One exercise. One set at a time.</p></div>
      {!editing && <button className="fitness-primary" disabled={loading} onClick={() => setEditing(log.draft ?? "new")}>{log.draft ? "Resume draft" : "+ Log workout"}</button>}
    </header>
    <details open={!editing} className="fitness-card space-y-3" aria-label="Offline and sync status">
      <summary className="cursor-pointer text-sm font-medium">Connection & backups</summary>
      <OfflineSetup />
      <p role="status" className="font-medium">{log.queue.length ? `${log.queue.length} changes saved on this device · waiting to sync` : log.lastSync ? (log.draft ? "Completed workouts synced · draft stays on this device" : "All saved changes synced") : "Ready to save on this device"}</p>
      <p className="text-sm text-stone-500">{syncStatus}</p>
      {log.lastSync && <p className="text-xs text-stone-500">Last synced {new Date(log.lastSync).toLocaleString()}</p>}
      <div className="flex flex-wrap gap-2">
        <button onClick={reload}>Sync now</button>
        <button onClick={() => downloadBackup(log)}>Export local backup</button>
        {syncError?.status === 401 && <a href="/api/auth/login" className="underline p-2">Sign in to sync</a>}
      </div>
      <p className="text-xs text-stone-500">Sync retries while this app is open and when you return to it. Your VPN must be connected. Saved drafts survive closing the app.</p>
      {syncError?.status === 409 && syncError.mutation && syncError.mutation.kind !== "exercise" && <div className="space-y-2">
        <p>Another device changed this workout. You can use the server version, or keep a separate copy if your local workout still exists.</p>
        <div className="flex flex-wrap gap-2">{(log.workouts.some(w => w.id === (syncError.mutation?.kind !== "exercise" ? syncError.mutation?.workout.id : undefined)) ? [true,false] : [false]).map(copy => <button key={String(copy)} onClick={async () => {
          if (!copy && !window.confirm("Discard the queued local changes for this workout and use the server version?")) return;
          try {await resolveConflict(owner,syncError.mutation!,copy); setSyncError(null); reload();}
          catch(e) {setError((e as Error).message);}
        }}>{copy ? "Keep local as a new workout" : "Use server version"}</button>)}</div>
      </div>}
    </details>
    {error && <div role="alert" className="fitness-card text-red-600">{error} <button onClick={reload}>Retry</button></div>}
    {notice && <p role="status">{notice}</p>}
    {loading ? <p role="status">Loading workouts…</p> : editing ? <WorkoutForm owner={owner} initial={editing === "new" ? undefined : editing} exercises={exercises} workouts={log.workouts} onCancel={() => setEditing(null)} onSaved={() => {setEditing(null); setNotice("Workout saved on this device."); reload();}} /> : <>
      {log.draft && <div className="fitness-card flex flex-wrap gap-3 items-center"><p>You have an unfinished workout saved on this device.</p><button onClick={() => setEditing(log.draft)}>Resume draft</button><button onClick={async () => {
        if (window.confirm("Discard the unfinished draft?")) {
          try {await changeLog(owner,data => {data.draft=null;});} catch(e) {setError((e as Error).message);}
        }
      }}>Discard draft</button></div>}
      <section className="fitness-card flex flex-wrap items-center justify-between gap-4">
        <div><h2 className="font-semibold">Try a fictional workout log</h2><p className="text-sm text-stone-500 max-w-xl mt-1">Import three synthetic sessions dated January 2000. These examples demonstrate reps, loads, timed activity, and missing values; they are not your workout history.</p></div>
        <button disabled={busy} onClick={importNotes}>{busy ? "Importing…" : "Import demo workouts"}</button>
      </section>
      {summary && <section className="fitness-card space-y-4">
        <div className="flex items-baseline justify-between"><h2 className="text-lg font-semibold">Exercise overview</h2><span className="text-sm text-stone-500">{summary.workouts} workouts logged</span></div>
        <p className="text-sm text-stone-500">All recorded sessions. Reps are actual counts as logged; time includes cooldowns. Notes without clear sets are excluded. Loads are shown per set below, without combining different equipment or load conventions.</p>
        {summary.exercises.length === 0 ? <p>No workouts yet. Log a workout or import demo workouts to get started.</p> : <div className="overflow-x-auto"><table className="w-full text-sm text-left"><thead><tr>{["Exercise","Sessions","Sets","Recorded reps","Time","Last trained"].map(h => <th key={h} className="py-3 pr-5 whitespace-nowrap">{h}</th>)}</tr></thead><tbody>{summary.exercises.map(e => <tr key={e.exercise_id} className="border-t border-stone-200 dark:border-stone-700"><td className="py-3 pr-5">{e.name}</td><td>{e.sessions}</td><td>{e.sets}</td><td>{e.reps}{e.unknown_reps > 0 && <span className="block text-xs text-stone-500">{e.unknown_reps} unknown</span>}</td><td className="whitespace-nowrap pr-3">{e.seconds ? `${Math.floor(e.seconds/60)}m ${e.seconds%60}s` : "—"}</td><td className="whitespace-nowrap">{e.last_performed}</td></tr>)}</tbody></table></div>}
      </section>}
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-semibold">Workout history</h2><label>Filter by exercise<select value={filter} onChange={e => setFilter(e.target.value)}><option value="">All exercises</option>{exercises.map(e => <option key={e.id} value={e.id}>{e.name}</option>)}</select></label></div>
      {workouts.filter(w => !filter || w.exercises.some(e => e.exercise_id === filter)).map(w => <article className="fitness-card space-y-4" key={w.id}>
        <div className="flex justify-between items-center"><h3 className="text-lg font-semibold">{new Date(w.performed_on + "T12:00:00").toLocaleDateString(undefined,{weekday:"short",month:"long",day:"numeric",year:"numeric"})}</h3><div className="flex gap-2"><button onClick={() => {if (!log.draft || window.confirm("Replace the unfinished draft with this workout?")) setEditing(w);}}>Edit</button><button disabled={busy} onClick={async () => {
          if (!window.confirm("Delete this workout and its sets?")) return;
          setBusy(true);
          try {await deleteWorkout(owner,w); reload();} catch(e) {setError((e as Error).message);} finally {setBusy(false);}
        }}>Delete</button></div></div>
        {log.queue.some(m => m.kind !== "exercise" && m.workout.id === w.id) && <p className="text-sm text-amber-700 dark:text-amber-400">Saved on this device · pending sync</p>}
        {w.notes && <p className="text-sm text-stone-500">{w.notes}</p>}
        {w.exercises.map((e,i) => <div key={i} className="border-t border-stone-200 dark:border-stone-700 pt-3">
          <h4 className="font-medium">{exercises.find(x => x.id === e.exercise_id)?.name ?? e.exercise_id}</h4>
          <ol className="flex flex-wrap gap-2 mt-2">{e.sets.map((s,j) => <li key={j} className="rounded-lg bg-stone-100 dark:bg-stone-800 px-3 py-2 text-sm">
            <span className="text-stone-500 mr-2">{j+1}.</span>{s.reps !== null ? `${s.reps} reps` : s.seconds === null ? "Reps unknown" : ""}
            {s.weight !== null ? ` @ ${s.weight} ${s.unit}` : s.seconds === null && s.load_basis !== "bodyweight" ? " · load unknown" : ""}
            {s.load_basis !== "unspecified" && ` · ${s.load_basis.replace("_"," ")}`}
            {s.seconds !== null && ` ${s.seconds}s`}{s.phase !== "work" && ` · ${s.phase}`}
            {s.failure === true && " · failure"}{s.failure === false && " · no failure"}{s.target_reps !== null && s.target_reps !== s.reps && ` (target ${s.target_reps})`}
            {s.notes && <span className="block text-stone-500">{s.notes}</span>}
          </li>)}</ol>
          {e.notes && <p className="text-sm text-stone-500 mt-2">{e.notes}</p>}
        </div>)}
        {w.source_note && <details className="text-sm"><summary className="cursor-pointer">Original notes</summary><pre className="whitespace-pre-wrap mt-3 text-stone-500">{w.source_note}</pre></details>}
      </article>)}
      {filter && !workouts.some(w => w.exercises.some(e => e.exercise_id === filter)) && <p>No workouts for this exercise.</p>}
    </>}
  </main>;
}
