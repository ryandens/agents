import { useId } from "react";
import type { Point } from "./progress";

export default function ProgressChart({points, label, unit}: {points:Point[];label:string;unit:string}) {
  const titleId = useId();
  if (!points.length) return <p className="text-sm text-stone-500">No measurements yet for this chart.</p>;
  const dates = points.map(point => Date.parse(point.date));
  const first = Math.min(...dates), last = Math.max(...dates);
  const values = points.map(point => point.value);
  const low = Math.min(...values), high = Math.max(...values);
  const padding = Math.max((high-low)*0.15, 1);
  const min = Math.max(0,low-padding), max = high+padding;
  const x = (index:number) => last === first ? 220 : 60 + (dates[index]-first)/(last-first)*330;
  const y = (value:number) => 190 - (value-min)/(max-min)*150;
  const format = (value:number) => Number(value.toFixed(1)).toLocaleString();
  return <div className="space-y-2">
    <svg viewBox="0 0 440 235" role="img" aria-labelledby={titleId} className="w-full text-emerald-700 dark:text-emerald-400">
      <title id={titleId}>{label}, {unit}, {points[0].date} to {points.at(-1)!.date}</title>
      {[min,(min+max)/2,max].map(value => <g key={value}>
        <line x1="60" x2="390" y1={y(value)} y2={y(value)} stroke="currentColor" opacity="0.15"/>
        <text x="50" y={y(value)+4} textAnchor="end" fill="currentColor" fontSize="14">{format(value)}</text>
      </g>)}
      <polyline points={points.map((point,index) => `${x(index)},${y(point.value)}`).join(" ")} fill="none" stroke="currentColor" strokeWidth="2.5"/>
      {points.map((point,index) => <circle key={point.id} cx={x(index)} cy={y(point.value)} r="4" fill="currentColor"><title>{point.date}: {format(point.value)} {unit}</title></circle>)}
      <text x="60" y="220" fill="currentColor" fontSize="14">{points[0].date}</text>
      <text x="390" y="220" textAnchor="end" fill="currentColor" fontSize="14">{points.at(-1)!.date}</text>
    </svg>
    <p className="text-xs text-stone-500">{unit} · {points.length} recorded {points.length === 1 ? "point" : "points"}. The vertical axis is scaled to the recorded range.</p>
    <details><summary className="cursor-pointer text-sm">View chart data</summary>
      <table className="w-full text-sm text-left"><caption className="sr-only">{label}</caption><thead><tr><th>Date</th><th>{unit}</th></tr></thead>
        <tbody>{points.map(point => <tr key={point.id}><td>{point.date}</td><td>{format(point.value)}</td></tr>)}</tbody>
      </table>
    </details>
  </div>;
}
