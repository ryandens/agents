import { useState } from "react";
import type { LocalLog } from "./database";
import { changeLog } from "./database";
import { request, saveBodyWeight, savePendingChanges } from "./offline";
import { pounds, weightProgress } from "./progress";
import ProgressChart from "./ProgressChart";
import { useConfirmation } from "./useConfirmation";

export default function BodyWeightLog({owner,log,onChange}: {owner:string;log:LocalLog;onChange:()=>void}) {
  const [date,setDate] = useState(() => new Date().toLocaleDateString("en-CA"));
  const [weight,setWeight] = useState("");
  const [busy,setBusy] = useState(false);
  const [notice,setNotice] = useState("");
  const [error,setError] = useState("");
  const {requestConfirmation,confirmationDialog} = useConfirmation();
  return <section className="fitness-card space-y-4" aria-label="Body weight">
    {confirmationDialog}
    <div><h2 className="text-lg font-semibold">Body weight</h2><p className="text-sm text-stone-500">Log a weigh-in independently of your workouts.</p></div>
    <form onSubmit={async event => {
      event.preventDefault(); setBusy(true); setError(""); setNotice("");
      try {
        await saveBodyWeight(owner,{id:crypto.randomUUID(),measured_on:date,weight:Number(weight),unit:"lbs"});
        setWeight("");
        try {await savePendingChanges(owner); setNotice("Weight saved.");}
        catch(e) {setNotice(`Weight saved on this device; server save pending. ${(e as Error).message}`);}
        onChange();
      } catch(e) {setError((e as Error).message);}
      finally {setBusy(false);}
    }}>
      <fieldset disabled={busy} className="flex flex-wrap items-end gap-3">
        <label>Weigh-in date<input type="date" required value={date} onChange={event => setDate(event.target.value)}/></label>
        <label>Body weight (lbs)<input type="number" inputMode="decimal" required min="0.1" max="2000" step="0.1" value={weight} onChange={event => setWeight(event.target.value)}/></label>
        <button className="fitness-primary" type="submit">{busy ? "Saving…" : "Log weight"}</button>
      </fieldset>
    </form>
    {notice && <p role="status">{notice}</p>}{error && <p role="alert" className="text-red-600">{error}</p>}
    <ProgressChart points={weightProgress(log.bodyWeights,"lbs")} label="Body weight over time" unit="lbs"/>
    {!!log.bodyWeights.length && <details><summary className="cursor-pointer">Weight history</summary>
      <ul className="space-y-2 mt-3">{[...log.bodyWeights].sort((a,b) => b.measured_on.localeCompare(a.measured_on)).map(entry => {
        const pending = log.queue.some(mutation => mutation.kind === "bodyweight" && mutation.measurement.id === entry.id);
        return <li key={entry.id} className="flex flex-wrap justify-between gap-2"><span>{entry.measured_on} · {pounds(entry.weight,entry.unit)} lbs{pending && " · pending save"}</span>
          <button disabled={busy || pending} onClick={async () => {
            if (!(await requestConfirmation("Delete this weight entry?"))) return;
            setBusy(true); setError("");
            try {
              await request(`/api/fitness/body-weight/${entry.id}`,{method:"DELETE",headers:{"X-Fitness-Owner":owner}});
              await changeLog(owner,data => {data.bodyWeights = data.bodyWeights.filter(value => value.id !== entry.id);});
              setNotice("Weight entry deleted."); onChange();
            } catch(e) {setError(`Could not confirm deletion. Retry when connected. ${(e as Error).message}`);}
            finally {setBusy(false);}
          }}>Delete weight from {entry.measured_on}</button>
        </li>;
      })}</ul>
    </details>}
  </section>;
}
