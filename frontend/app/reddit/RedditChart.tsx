"use client";

import { useState } from "react";
import {
  axisTicks,
  formatDay,
  formatDayLong,
  labelStride,
  niceMax,
} from "../shorts/chart";
import type { Metric, RedditDay } from "./types";

export default function RedditChart({
  days,
  metric,
  selectedDay,
  onSelect,
}: {
  days: RedditDay[];
  metric: Metric;
  selectedDay: string;
  onSelect: (day: string) => void;
}) {
  const [active, setActive] = useState<string | null>(null);
  const top = niceMax(Math.max(0, ...days.map((day) => day[metric])));
  const label = metric === "visits" ? "page opens" : "raw visits";
  return (
    <div>
      <div className="relative mt-6 h-60">
        {axisTicks(top).map((tick) => (
          <div
            key={tick}
            className="absolute inset-x-0 flex items-center gap-2"
            style={{
              bottom: `${(tick / top) * 100}%`,
              transform: "translateY(50%)",
            }}
          >
            <span className="w-8 shrink-0 text-right text-[11px] tabular-nums text-stone-400">
              {tick}
            </span>
            <div
              className="h-px flex-1"
              style={{
                background:
                  tick === 0 ? "var(--chart-axis)" : "var(--chart-gridline)",
              }}
            />
          </div>
        ))}
        <div className="absolute inset-y-0 right-0 left-10 flex items-end gap-[2px]">
          {days.map((day, index) => (
            <button
              key={day.day}
              type="button"
              onClick={() => onSelect(day.day)}
              onMouseEnter={() => setActive(day.day)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(day.day)}
              onBlur={() => setActive(null)}
              aria-pressed={selectedDay === day.day}
              aria-label={`${formatDayLong(day.day)}: ${day.has_history ? `${day[metric]} ${label}` : "Not uploaded"}. Show recorded visits`}
              className={`relative flex h-full min-w-0 flex-1 items-end justify-center rounded-sm focus-visible:outline-2 focus-visible:outline-emerald-600 ${selectedDay === day.day ? "bg-emerald-100/60 dark:bg-emerald-950" : "hover:bg-stone-100 dark:hover:bg-stone-800"}`}
            >
              {!day.has_history ? (
                <span
                  aria-hidden="true"
                  className="mb-0.5 w-full max-w-6 border-b-2 border-dashed border-stone-400"
                />
              ) : (
                <span
                  aria-hidden="true"
                  className="w-full max-w-6 rounded-t-sm"
                  style={{
                    height: `${(day[metric] / top) * 100}%`,
                    minHeight: day[metric] ? 3 : 2,
                    background: day[metric]
                      ? "var(--chart-series)"
                      : "var(--chart-axis)",
                  }}
                />
              )}
              {active === day.day && (
                <span
                  className="pointer-events-none absolute bottom-full z-10 rounded-lg bg-stone-900 px-2.5 py-1.5 text-left text-xs whitespace-nowrap text-white shadow-lg"
                  style={{
                    left: index < days.length / 2 ? 0 : undefined,
                    right: index >= days.length / 2 ? 0 : undefined,
                  }}
                >
                  <strong className="block">
                    {day.has_history
                      ? `${day[metric]} ${label}`
                      : "Not uploaded"}
                  </strong>
                  {formatDayLong(day.day)}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>
      <div className="mt-2 flex gap-[2px] pl-10">
        {days.map((day, index) => (
          <div
            key={day.day}
            className="min-w-0 flex-1 text-center text-[11px] whitespace-nowrap text-stone-400"
          >
            {(days.length - 1 - index) % labelStride(days.length) === 0 && (
              <span
                className={
                  (days.length - 1 - index) % (labelStride(days.length) * 2) === 0
                    ? undefined
                    : "hidden sm:inline"
                }
              >
                {formatDay(day.day)}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
