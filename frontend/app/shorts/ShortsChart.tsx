"use client";

import { useState } from "react";
import { axisTicks, formatDay, formatDayLong, labelStride, niceMax } from "./chart";
import type { ShortsDay } from "./types";

/**
 * A column per day, drawn in HTML rather than SVG.
 *
 * An SVG would need a viewBox, and a viewBox scales its text with the container — the
 * axis labels would shrink to six pixels in a narrow window and swell in a wide one.
 * Divs in a flex row are responsive without any of that: the columns share the width,
 * the labels stay the size they were asked to be, and each column is already a real
 * focusable element rather than a `<rect>` that has to be taught to be one.
 */

const PLOT_HEIGHT = 240;

export default function ShortsChart({ days }: { days: ShortsDay[] }) {
  // Which column the pointer or the keyboard is on. One tooltip at a time; null is
  // "none", which is also the state after a blur, so the tooltip never outlives focus.
  const [active, setActive] = useState<number | null>(null);

  const tallest = days.reduce((most, day) => Math.max(most, day.visits), 0);
  const top = niceMax(tallest);
  const stride = labelStride(days.length);
  // The one column that gets a number printed on it. Labelling every column is the
  // fastest way to make a chart unreadable; the extreme is the one worth calling out,
  // and the tooltip and the table carry the other eighty-nine.
  const busiest = days.reduce(
    (best, day, index) => (day.visits > days[best]?.visits ? index : best),
    0
  );
  const showBusiest = tallest > 0;

  return (
    <div>
      {/* mt-5 leaves room for the direct label, which sits above a column that may be
          the full height of the plot. */}
      <div className="relative mt-5" style={{ height: PLOT_HEIGHT }}>
        {axisTicks(top).map((tick) => (
          <div
            key={tick}
            className="absolute inset-x-0 flex items-center gap-2"
            style={{ bottom: `${(tick / top) * 100}%`, transform: "translateY(50%)" }}
          >
            <span className="w-8 shrink-0 text-right text-[11px] tabular-nums text-stone-400 dark:text-stone-500">
              {tick}
            </span>
            {/* Solid hairlines. A dashed grid reads as a threshold or a projection
                when it is only a ruler. The baseline is a step darker than the rest. */}
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
          {days.map((day, index) => {
            const height = (day.visits / top) * 100;
            const isActive = active === index;
            return (
              <button
                key={day.day}
                type="button"
                // The whole column is the hit target, full height and full slot
                // width, so nobody has to land on a two-pixel bar to read a quiet day.
                className="group relative flex h-full flex-1 cursor-default items-end justify-center focus:outline-none"
                onMouseEnter={() => setActive(index)}
                onMouseLeave={() => setActive((current) => (current === index ? null : current))}
                onFocus={() => setActive(index)}
                onBlur={() => setActive((current) => (current === index ? null : current))}
                aria-label={!day.history_uploaded ? `${formatDayLong(day.day)}: Not uploaded` : day.visits === 0 ? `${formatDayLong(day.day)}: 0 Shorts — Shorts-free. Nice work!` : `${formatDayLong(day.day)}: ${day.visits} ${
                  day.visits === 1 ? "Short" : "Shorts"
                }, ${day.unique_shorts} unique`}
              >
                {!day.history_uploaded ? (
                  <span aria-hidden="true" className="mb-0.5 w-full max-w-6 border-b-2 border-dashed border-stone-400" />
                ) : day.visits === 0 ? (
                  <span aria-hidden="true" className="text-sm font-bold text-emerald-700 dark:text-emerald-400">✓</span>
                ) : (
                  <span
                    // Square where it meets the baseline, rounded at the data end.
                    className="relative w-full max-w-6 rounded-t-[4px] transition-[filter] group-hover:brightness-110 group-focus-visible:brightness-110"
                    style={{
                      height: `${height}%`,
                      background: "var(--chart-series)",
                      // Keeps a single Short visible: at a 40-column axis one unit is
                      // under three pixels, and a bar too short to see reads as zero.
                      minHeight: 3,
                    }}
                  >
                    {showBusiest && index === busiest && (
                      <span className="absolute -top-5 left-1/2 -translate-x-1/2 text-[11px] font-medium tabular-nums whitespace-nowrap text-stone-500 dark:text-stone-400">
                        {day.visits}
                      </span>
                    )}
                  </span>
                )}

                {isActive && <Tooltip day={day} height={height} index={index} count={days.length} />}
              </button>
            );
          })}
        </div>
      </div>

      <div className="mt-2 flex gap-[2px] pl-10">
        {days.map((day, index) => (
          <div
            key={day.day}
            className="flex-1 text-center text-[11px] whitespace-nowrap text-stone-400 dark:text-stone-500"
          >
            {/* Anchored to the end of the range so the last column — today — is always
                labelled, whatever the range length does to the stride. */}
            {(days.length - 1 - index) % stride === 0 ? formatDay(day.day) : ""}
          </div>
        ))}
      </div>
    </div>
  );
}

function Tooltip({
  day,
  height,
  index,
  count,
}: {
  day: ShortsDay;
  height: number;
  index: number;
  count: number;
}) {
  // Centred on the column, except near the ends, where centring would hang the box
  // off the edge of the card.
  const position = count > 1 ? index / (count - 1) : 0.5;
  const shift = position < 0.1 ? "0" : position > 0.9 ? "-100%" : "-50%";

  return (
    <div
      className="pointer-events-none absolute left-1/2 z-10 rounded-lg bg-stone-900 px-2.5 py-1.5 text-left shadow-lg dark:bg-stone-700"
      style={{ bottom: `calc(${height}% + 8px)`, transform: `translateX(${shift})` }}
    >
      {/* The value leads and the label follows: the reader already knows which day
          they are pointing at — they came for the number. */}
      <div className="text-sm font-semibold whitespace-nowrap text-white">
        {day.history_uploaded ? `${day.visits} ${day.visits === 1 ? "Short" : "Shorts"}` : "Not uploaded"}
      </div>
      {day.history_uploaded && day.visits === 0 && (
        <div className="text-xs whitespace-nowrap text-emerald-300">Shorts-free. Nice work!</div>
      )}
      <div className="text-[11px] whitespace-nowrap text-stone-300">
        {day.history_uploaded ? `${day.unique_shorts} unique · ` : "Awaiting Safari history · "}{formatDayLong(day.day)}
      </div>
    </div>
  );
}
