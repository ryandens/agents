"use client";
import { useState } from "react";
import { areas, equipment, library, type LibraryExercise } from "./library";

export default function ExerciseBrowser({onSelect}: {onSelect: (exercise:LibraryExercise) => void}) {
  const [gear,setGear] = useState("");
  const [area,setArea] = useState("");
  const matches = library.filter(e => (!gear || e.equipment === gear) && (!area || e.area === area));
  const tiles = (items:typeof areas, choose:(name:string)=>void) => <div className="exercise-category-grid">
    {items.map(item => <button type="button" key={item.name} onClick={() => choose(item.name)}>
      <span aria-hidden="true">{item.icon}</span><strong>{item.name}</strong><span aria-hidden="true">›</span>
    </button>)}
  </div>;
  return <div className="exercise-browser">
    {(gear || area) && <nav className="exercise-breadcrumb" aria-label="Exercise categories">
      <button type="button" onClick={() => {setGear("");setArea("");}}>All categories</button>
      {gear && <button type="button" onClick={() => setArea("")}>{gear}</button>}
      {area && <span>{area}</span>}
    </nav>}
    {!gear && !area ? <>
      <h4>By equipment</h4>{tiles(equipment,setGear)}
      <h4>By body area</h4>{tiles(areas,setArea)}
    </> : <>
      {gear && !area && gear !== "Cardio" && <><h4>Choose a body area</h4>{tiles(areas.filter(a => matches.some(e => e.area === a.name)),setArea)}</>}
      {area && !gear && <div className="category-filters" aria-label="Filter by equipment">{equipment.filter(g => matches.some(e => e.equipment === g.name)).map(g => <button type="button" key={g.name} onClick={() => setGear(g.name)}>{g.name}</button>)}</div>}
      {(!gear || area || gear === "Cardio") && <div className="exercise-results library-results">{matches.map(e => <button type="button" key={e.id} onClick={() => onSelect(e)}><span>{e.name}<small>{e.equipment}{e.area && ` · ${e.area}`}</small></span><span aria-hidden="true">+</span></button>)}</div>}
    </>}
  </div>;
}
