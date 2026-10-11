"use client";
import { useState } from "react";

export default function TouchValue({label, name, value, kind, onChange}: {
  label:string; name:string; value:number|null; kind:"reps"|"weight"|"seconds"; onChange:(value:number|null)=>void;
}) {
  const [open,setOpen] = useState(false);
  const [digits,setDigits] = useState("");
  const [replace,setReplace] = useState(true);
  const presets = kind === "reps" ? [5,8,10,12,15] : kind === "seconds" ? [30,45,60,300,600] : [10,20,30,50,70,80,100];
  const max = kind === "seconds" ? 86400 : kind === "weight" ? 100000 : 10000;
  const valid = digits === "" || (Number.isFinite(Number(digits)) && Number(digits) <= max && Number(digits) >= (kind === "seconds" ? 1 : 0));
  function finish(next:number|null) {onChange(next);setOpen(false);}
  return <div className="touch-value">
    <label>{label}<input aria-label={name} type="number" readOnly value={value ?? ""} placeholder="Tap"
      onClick={() => {setDigits(value === null ? "" : String(value));setReplace(true);setOpen(!open);}}
      onKeyDown={event => {if (event.key === "Enter" || event.key === " ") {event.preventDefault();setDigits(value === null ? "" : String(value));setReplace(true);setOpen(!open);}}}
      onChange={event => onChange(event.target.value === "" ? null : Number(event.target.value))}/></label>
    {open && <div className="touch-value-panel" role="group" aria-label={`Choose ${name}`}>
      <div className="picker-heading"><strong>{label}</strong><button type="button" onClick={() => setOpen(false)}>Cancel</button></div>
      <div className="value-presets">{presets.map(n => <button type="button" key={n} onClick={() => finish(n)}>{kind === "seconds" && n >= 60 ? `${n/60} min` : n}</button>)}</div>
      <div className="value-stepper">
        <button type="button" aria-label={`Decrease ${label}`} onClick={() => {setDigits(String(Math.max(kind === "seconds" ? 1 : 0,Number(digits || 0)-(kind === "weight" ? 5 : 1))));setReplace(false);}}>−</button>
        <output aria-live="polite">{digits || "—"}</output>
        <button type="button" aria-label={`Increase ${label}`} onClick={() => {setDigits(String(Math.min(max,Number(digits || 0)+(kind === "weight" ? 5 : 1))));setReplace(false);}}>+</button>
      </div>
      <div className="value-keypad">{["1","2","3","4","5","6","7","8","9",kind === "weight" ? "." : "Clear","0","⌫"].map(key => <button type="button" key={key} aria-label={key === "⌫" ? "Backspace" : /^\d$/.test(key) ? `Digit ${key}` : key} onClick={() => {
        const current = replace ? "" : digits;
        setReplace(false);
        if (key === "Clear") setDigits("");
        else if (key === "⌫") setDigits(current.slice(0,-1));
        else if (current.length < 8 && !(key === "." && current.includes("."))) setDigits(current + key);
      }}>{key}</button>)}</div>
      <div className="value-actions"><button type="button" onClick={() => finish(null)}>Clear value</button><button type="button" className="fitness-primary" disabled={!valid} onClick={() => finish(digits === "" ? null : Number(digits))}>Done</button></div>
    </div>}
  </div>;
}
