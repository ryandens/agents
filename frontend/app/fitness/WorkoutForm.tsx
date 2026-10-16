"use client";

import { useEffect, useRef, useState } from "react";
import { newSet, type Exercise, type Workout, type SetRecord, type Entry } from "./types";
import { changeLog } from "./database";
import { createExercise, ensureLibraryExercise, downloadBackup, saveWorkout, savePendingChanges, validateWorkout } from "./offline";
import { copyMeasurements, lastExerciseSet } from "./setDefaults";
import ExerciseBrowser from "./ExerciseBrowser";
import { libraryEntry, type LibraryExercise } from "./library";
import SetEditor, { describeSet } from "./SetEditor";

export default function WorkoutForm({ owner, initial, exercises, workouts = [], onSaved, onCancel }: {
  owner: string; initial?: Workout; exercises: Exercise[]; workouts?: Workout[]; onSaved: (pendingReason?: string) => void; onCancel: () => void;
}) {
  const [draft, setDraft] = useState<Workout>(() => initial ?? {
    id: crypto.randomUUID(), revision: 0, performed_on: new Date().toLocaleDateString("en-CA"),
    notes: "", source_note: "", exercises: [],
  });
  const [createdExercises, setCreatedExercises] = useState<Exercise[]>([]);
  const catalog = [...exercises, ...createdExercises.filter(e => !exercises.some(existing => existing.id === e.id))];
  const [query, setQuery] = useState("");
  const [pickerOpen, setPickerOpen] = useState(!initial?.exercises.length);
  const [rowKeys, setRowKeys] = useState(() => (initial?.exercises ?? []).map(e => ({
    id: crypto.randomUUID(), sets: e.sets.map(() => crypto.randomUUID()),
  })));
  const [removed, setRemoved] = useState<
    {kind:"exercise"; position:number; entry:Entry; keys:{id:string;sets:string[]}; label:string} |
    {kind:"set"; position:number; parent:string; set:SetRecord; key:string; label:string} | null
  >(null);
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [storedDraft, setStoredDraft] = useState<Workout | null>(null);
  const [draftStatus, setDraftStatus] = useState("");
  const title = useRef<HTMLHeadingElement>(null);


  useEffect(() => {
    let active = true;
    changeLog(owner, log => { log.draft = draft; })
      .then(() => { if (active) {setStoredDraft(draft); setDraftStatus("");} })
      .catch(() => { if (active) setDraftStatus("Draft could not be saved. Keep this page open and export a backup."); });
    return () => { active = false; };
  }, [draft, owner]);
  const count = draft.exercises.reduce((total, e) => total + e.sets.length, 0);
  const incomplete = draft.exercises.reduce((total, e) => total + e.sets.filter(s =>
    (s.reps === null && s.seconds === null) || (s.reps !== null && s.weight === null && s.load_basis !== "bodyweight")
  ).length, 0);
  const exerciseName = (id: string) => catalog.find(e => e.id === id)?.name ?? id;
  function patchSet(i: number, j: number, patch: Partial<SetRecord>) {
    setDraft(d => ({ ...d, exercises: d.exercises.map((e, k) => k === i ? {
      ...e, sets: e.sets.map((s, l) => l === j ? { ...s, ...patch } : s),
    } : e) }));
  }
  function startingSet(id: string) {
    const last = lastExerciseSet(workouts, id, draft);
    return last ? copyMeasurements(last.set) : {...newSet(),load_basis:libraryEntry(id)?.basis ?? "unspecified"};
  }
  function addExercise(exercise: Exercise) {
    setRowKeys(keys => [...keys,{id:crypto.randomUUID(),sets:[crypto.randomUUID()]}]);
    setDraft(d => ({...d, exercises:[...d.exercises,{exercise_id:exercise.id, notes:"", sets:[startingSet(exercise.id)]}]}));
    setPickerOpen(false); setQuery("");
  }
  function addSet(index: number, repeat: boolean) {
    const entry = draft.exercises[index];
    const source = repeat ? entry.sets.at(-1) : entry.sets[0];
    const next = source ? copyMeasurements(source) : startingSet(entry.exercise_id);
    setRowKeys(keys => keys.map((k,i) => i === index ? {...k,sets:[...k.sets,crypto.randomUUID()]} : k));
    setDraft(d => ({...d, exercises:d.exercises.map((e,i) => i === index ? {...e,sets:[...e.sets,next]} : e)}));
  }
  function removeSet(i: number, j: number) {
    setRemoved({kind:"set",parent:rowKeys[i].id,key:rowKeys[i].sets[j],
      position:j,set:draft.exercises[i].sets[j],label:`Set ${j+1} removed from ${exerciseName(draft.exercises[i].exercise_id)}`});
    setDraft(d => ({...d,exercises:d.exercises.map((e,k) => k === i ? {...e,sets:e.sets.filter((_,n) => n !== j)} : e)}));
    setRowKeys(keys => keys.map((k,n) => n === i ? {...k,sets:k.sets.filter((_,s) => s !== j)} : k));
  }
  function removeExercise(i: number) {
    setRemoved({kind:"exercise",position:i,entry:draft.exercises[i],keys:rowKeys[i],
      label:`${exerciseName(draft.exercises[i].exercise_id)} removed`});
    setDraft(d => ({...d,exercises:d.exercises.filter((_,k) => k !== i)}));
    setRowKeys(keys => keys.filter((_,k) => k !== i));
  }
  function undoRemoval() {
    if (!removed) return;
    if (removed.kind === "exercise") {
      setDraft(d => ({...d,exercises:d.exercises.toSpliced(removed.position,0,removed.entry)}));
      setRowKeys(keys => keys.toSpliced(removed.position,0,removed.keys));
    } else {
      const index = rowKeys.findIndex(k => k.id === removed.parent);
      if (index < 0) return;
      setDraft(d => ({...d,exercises:d.exercises.map((e,i) => i === index ? {...e,sets:e.sets.toSpliced(removed.position,0,removed.set)} : e)}));
      setRowKeys(keys => keys.map((k,i) => i === index ? {...k,sets:k.sets.toSpliced(removed.position,0,removed.key)} : k));
    }
    setRemoved(null);
  }
  async function createAndAdd() {
    setBusy(true); setError("");
    try {
      const exercise = await createExercise(owner, query);
      setCreatedExercises(c => [...c,exercise]); addExercise(exercise);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  function openPicker() {
    setPickerOpen(true);

  }
  async function addFromLibrary(template: LibraryExercise) {
    setBusy(true); setError("");
    try {
      const exercise = await ensureLibraryExercise(owner, template);
      setCreatedExercises(c => c.some(e => e.id === exercise.id) ? c : [...c,exercise]);
      addExercise(exercise);
    } catch (e) {setError((e as Error).message);}
    finally {setBusy(false);}
  }
  const results = catalog.filter(e => e.name.toLowerCase().includes(query.trim().toLowerCase()))
    .sort((a,b) => a.name.localeCompare(b.name));
  return <form noValidate className="workout-form" onKeyDown={event => {
    // The phone keyboard's Enter/Done key must not submit an unfinished session.
    if (event.key === "Enter" && event.target instanceof HTMLInputElement) event.preventDefault();
  }} onSubmit={async event => {
    event.preventDefault(); setError("");
    try {
      validateWorkout(draft);
      setBusy(true);
      await saveWorkout(owner, draft);
      try { await savePendingChanges(owner); }
      catch (e) {
        onSaved((e as Error).message);
        return;
      }
      onSaved();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }}>
    <header className="workout-form-header">
      <div className="workout-eyebrow">{review ? "Workout summary" : "Workout log"}</div>
      <h2 ref={title} tabIndex={-1}>{review ? "Ready to save?" : initial?.revision ? "Edit your workout" : "Your workout"}</h2>
      <p>{review ? "Check what you recorded before saving." : "Enter your sets below. Your draft is saved as you go."}</p>
      <p className={draftStatus ? "draft-state draft-error" : "draft-state"} role="status">
        {draftStatus || (storedDraft === draft ? "✓ Draft saved on this device" : "Saving draft on this device…")}
      </p>
      {draftStatus && <button type="button" onClick={() => downloadBackup(draft)}>Export draft backup</button>}
    </header>

    <fieldset disabled={busy} className="workout-body">
      <details className="workout-details workout-session">
        <summary><span>{new Date(draft.performed_on + "T12:00:00").toLocaleDateString(undefined,{month:"short",day:"numeric",year:"numeric"})}</span><span>Date & workout notes</span></summary>
        <label>Workout date<input required type="date" value={draft.performed_on} onChange={e => setDraft({...draft,performed_on:e.target.value})}/></label>
        <label>Workout notes<textarea maxLength={10000} value={draft.notes} onChange={e => setDraft({...draft,notes:e.target.value})} placeholder="How did the session feel?"/></label>
        <button type="button" onClick={() => downloadBackup(draft)}>Export draft backup</button>
        {draft.source_note && <details><summary>Original notes</summary><pre className="whitespace-pre-wrap text-sm">{draft.source_note}</pre></details>}
      </details>

      {review ? <section className="workout-review" aria-label="Workout review">
        <div className="workout-totals"><strong>{draft.exercises.length} exercises</strong><strong>{count} sets</strong></div>
        {incomplete > 0 && <p className="workout-missing">{incomplete} {incomplete === 1 ? "set has" : "sets have"} missing reps, time, or weight. Blanks will stay unknown; they won’t become zero.</p>}
        {draft.exercises.map((entry,i) => <section key={rowKeys[i].id} className="workout-review-exercise">
          <h3>{exerciseName(entry.exercise_id)}</h3>
          {entry.sets.length ? <ol>{entry.sets.map((s,j) => <li key={rowKeys[i].sets[j]}><span>Set {j+1}</span><div>{describeSet(s)}{s.target_reps !== null && <small>Target: {s.target_reps} reps</small>}{s.load_basis !== "unspecified" && <small>Load: {s.load_basis.replace("_"," ")}</small>}{s.notes && <small>{s.notes}</small>}</div></li>)}</ol> : <p>No sets recorded</p>}
          {entry.notes && <p>{entry.notes}</p>}
          <button type="button" onClick={() => {setReview(false);}}>Edit {exerciseName(entry.exercise_id)}</button>
        </section>)}
      </section> : <>
        {draft.exercises.length === 0 && <div className="workout-empty"><span aria-hidden="true">01</span><h3>Start with your first exercise</h3><p>Choose equipment or a body area. Tap an exercise to start.</p></div>}
        {draft.exercises.map((entry,i) => {
          const name = exerciseName(entry.exercise_id);
          const last = lastExerciseSet(workouts, entry.exercise_id, draft);
          return <section key={rowKeys[i].id} className="workout-exercise">
            <header className="exercise-heading">
              <div><h3>{name}</h3><span>{entry.sets.length} {entry.sets.length === 1 ? "set" : "sets"}</span></div>
              <button type="button" className="remove-control" aria-label={`Remove ${name} exercise`} onClick={() => removeExercise(i)}>Remove exercise</button>
            </header>
            <div className="exercise-panel">
              {last && <p className="set-history">Last workout · {last.date}: <strong>{describeSet(copyMeasurements(last.set))}</strong><span>Starting values for new sets. Adjust to what you complete today.</span></p>}
              {entry.sets.map((set,j) => <SetEditor key={rowKeys[i].sets[j]} set={set} exercise={name} number={j+1} defaultMode={libraryEntry(entry.exercise_id)?.mode}
                onChange={patch => patchSet(i,j,patch)} onRemove={() => removeSet(i,j)}/>)}
              {!entry.sets.length && <p className="workout-hint">No sets yet. Add a set below, or keep this exercise as a note.</p>}
              <div className="set-add-actions">
                <button type="button" disabled={entry.sets.length >= 100} onClick={() => addSet(i,false)}>+ Add set</button>
                <button type="button" disabled={!entry.sets.length || entry.sets.length >= 100} onClick={() => addSet(i,true)}>Repeat last set</button>
              </div>
              <p className="workout-hint">Add set uses set 1’s values. Each set can be adjusted separately.</p>
              <details className="workout-details exercise-options"><summary>Exercise notes</summary>
                <label>Exercise notes<textarea maxLength={4000} value={entry.notes} onChange={event => setDraft(d => ({...d,exercises:d.exercises.map((e,k) => k === i ? {...e,notes:event.target.value} : e)}))}/></label>
              </details>
            </div>
          </section>;
        })}
        {pickerOpen ? <section className="exercise-picker" aria-label="Choose an exercise">
          <div className="picker-heading"><h3>Add an exercise</h3>{draft.exercises.length > 0 && <button type="button" onClick={() => setPickerOpen(false)}>Close</button>}</div>
          <fieldset disabled={draft.exercises.length >= 100}><ExerciseBrowser onSelect={addFromLibrary}/></fieldset>
          {catalog.length > 0 && <h4 className="saved-exercises-heading">Your exercises</h4>}
          <details className="workout-details"><summary>Search or create an exercise</summary>
          <label>Search exercises<input type="search" maxLength={120} autoComplete="off" placeholder="e.g. Leg press" value={query} onChange={e => setQuery(e.target.value)}/></label>
          </details>
          <div className="exercise-results">{results.map(e => <button type="button" key={e.id} disabled={draft.exercises.length >= 100} onClick={() => addExercise(e)}><span>{e.name}</span><span aria-hidden="true">+</span></button>)}</div>
          {!results.length && <p className="workout-hint">{query.trim() ? "No matching exercises. You can create one below." : "Choose from the categories above."}</p>}
          {query.trim() && !catalog.some(e => e.name.toLowerCase() === query.trim().toLowerCase()) && <button className="create-exercise" type="button" disabled={busy || draft.exercises.length >= 100} onClick={createAndAdd}>Create & add “{query.trim()}”</button>}
          <p className="workout-hint">Use separate names for different machines or movement variations.</p>
        </section> : <button className="add-exercise-button" type="button" disabled={draft.exercises.length >= 100} onClick={openPicker}>+ Add another exercise</button>}
      </>}
    </fieldset>

    <footer className="workout-save-bar">
      {removed && <div className="removal-notice"><span role="status">{removed.label}</span><button type="button" disabled={busy} onClick={undoRemoval}>Undo</button></div>}
      {error && <p role="alert" className="workout-error">{error}</p>}
      <div className="workout-save-info"><span>{draft.exercises.length} {draft.exercises.length === 1 ? "exercise" : "exercises"} · {count} {count === 1 ? "set" : "sets"}</span><span>{busy ? "Saving…" : "Finish when you’re ready"}</span></div>
      {!review && draft.exercises.length > 0 && <button className="preview-workout" disabled={busy} type="button" onClick={() => {
        setReview(true); setTimeout(() => title.current?.focus(),0);
      }}>Preview summary</button>}
      <div className="workout-save-actions">
        <button disabled={busy} type="button" onClick={() => {
          if (review) {setReview(false);return;}
          onCancel();
        }}>{review ? "Back to sets" : "Close draft"}</button>
        <button className="fitness-primary" disabled={busy || !draft.exercises.length} type="submit">{busy ? "Saving…" : "Save workout"}</button>
      </div>
    </footer>
  </form>;
}
