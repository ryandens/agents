"use client";

import { useState } from "react";
import TouchValue from "./TouchValue";
import type { SetRecord } from "./types";

export function describeSet(set: SetRecord) {
  const parts = [];
  if (set.reps !== null) parts.push(`${set.reps} reps`);
  if (set.seconds !== null) parts.push(`${set.seconds}s`);
  if (set.weight !== null) parts.push(`${set.weight} ${set.unit}`);
  if (set.load_basis === "bodyweight") parts.push("Bodyweight");
  if (!parts.length) parts.push("Not recorded yet");
  if (set.failure === true) parts.push("Failure");
  if (set.phase !== "work") parts.push(set.phase);
  return parts.join(" · ");
}

export default function SetEditor({ set, exercise, number, onChange, onRemove, defaultMode = "reps" }: {
  set: SetRecord; exercise: string; number: number; defaultMode?: "reps" | "time";
  onChange: (patch: Partial<SetRecord>) => void; onRemove: () => void;
}) {
  const [mode, setMode] = useState<"reps" | "time">(set.seconds !== null && set.reps === null ? "time" : defaultMode);
  function numberInput(field: "reps" | "weight" | "seconds" | "target_reps", label: string) {
    return <label>{label}
      <input aria-label={`${exercise} set ${number} ${field}`}
        type="number" inputMode={field === "weight" ? "decimal" : "numeric"}
        min={field === "seconds" || field === "target_reps" ? 1 : 0}
        max={field === "weight" ? 100000 : field === "seconds" ? 86400 : 10000}
        step={field === "weight" ? "any" : 1} placeholder="—"
        value={set[field] ?? ""}
        onChange={e => onChange({[field]: e.target.value === "" ? null : Number(e.target.value)})} />
    </label>;
  }
  return <div className="set-editor" role="group" aria-label={`${exercise} set ${number}`}>
    <div className="set-entry-row">
      <span className="set-index" aria-label={`Set ${number}`}>{number}</span>
      <TouchValue label={mode === "reps" ? "Reps" : "Seconds"} name={`${exercise} set ${number} ${mode === "reps" ? "reps" : "seconds"}`} kind={mode === "reps" ? "reps" : "seconds"} value={mode === "reps" ? set.reps : set.seconds} onChange={value => onChange({[mode === "reps" ? "reps" : "seconds"]:value})}/>
      {set.load_basis === "bodyweight" ? <div className="bodyweight-label">Load<strong>Bodyweight</strong></div>
        : <TouchValue label={`Weight · ${set.unit}`} name={`${exercise} set ${number} weight`} kind="weight" value={set.weight} onChange={weight => onChange({weight})}/>}
      <button type="button" className="remove-set-button" aria-label={`Remove ${exercise} set ${number}`} onClick={onRemove}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 10v7m4-7v7"/></svg>
        <span>Remove</span>
      </button>
    </div>
    <div className="set-shortcuts">
      <button type="button" aria-pressed={set.failure === true} onClick={() => onChange({failure:set.failure === true ? null : true})}>
        {set.failure === true ? "✓ " : "+ "}Reached failure
      </button>
      <div className="set-mode" role="group" aria-label={`Measure ${exercise} set ${number}`}>
        <button type="button" aria-pressed={mode === "reps"} onClick={() => setMode("reps")}>Reps</button>
        <button type="button" aria-pressed={mode === "time"} onClick={() => setMode("time")}>Time</button>
      </div>
    </div>
    <details className="workout-details">
      <summary>Set options & notes{set.notes || set.phase !== "work" || set.load_basis !== "unspecified" || set.target_reps !== null ? " · recorded" : ""}</summary>
      <div className="set-options-grid">
        <label>Weight unit<select value={set.unit} onChange={e => onChange({unit:e.target.value as SetRecord["unit"]})}><option value="lbs">Pounds (lbs)</option><option value="kg">Kilograms (kg)</option></select></label>
        <label>Weight represents<select value={set.load_basis} onChange={e => {
          if (e.target.value === "bodyweight" && set.weight !== null && !window.confirm("Remove the recorded weight and mark this as bodyweight?")) return;
          onChange({load_basis:e.target.value as SetRecord["load_basis"], ...(e.target.value === "bodyweight" ? {weight:null} : {})});
        }}>
          <option value="unspecified">Not specified</option><option value="total">Total weight</option>
          <option value="per_hand">Weight per hand</option><option value="machine">Machine setting</option><option value="bodyweight">Bodyweight</option>
        </select></label>
        {numberInput("target_reps", "Target reps (optional)")}
        {mode === "reps" ? numberInput("seconds", "Time · seconds (optional)") : numberInput("reps", "Reps (optional)")}
        <label>Set type<select value={set.phase} onChange={e => onChange({phase:e.target.value as SetRecord["phase"]})}><option value="work">Working set</option><option value="warmup">Warmup</option><option value="cooldown">Cooldown</option></select></label>
        <label>Failure recorded<select value={set.failure === null ? "" : String(set.failure)} onChange={e => onChange({failure:e.target.value === "" ? null : e.target.value === "true"})}><option value="">Not recorded</option><option value="true">Yes</option><option value="false">No</option></select></label>
      </div>
      <label>Set notes<textarea maxLength={2000} value={set.notes} placeholder="Form, effort, or anything to remember" onChange={e => onChange({notes:e.target.value})}/></label>
    </details>
  </div>;
}
