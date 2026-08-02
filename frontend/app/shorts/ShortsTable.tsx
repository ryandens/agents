"use client";

import { formatDayLong } from "./chart";
import type { ShortsDay } from "./types";

/**
 * The chart's table twin.
 *
 * Not a fallback for when the chart fails — the same data, reachable without hovering,
 * without a pointer, and without seeing colour at all. The chart's tooltips are then
 * free to be an enhancement rather than the only way to read a value.
 *
 * Newest first, which is the opposite of the chart's left-to-right order: a table is
 * read from the top, and the day you want is almost always today.
 */
export default function ShortsTable({ days }: { days: ShortsDay[] }) {
  return (
    <div className="max-h-96 overflow-y-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">
          YouTube Shorts opened per day, newest first
        </caption>
        <thead className="sticky top-0 bg-white dark:bg-stone-900">
          <tr className="border-b border-stone-200 text-left dark:border-stone-800">
            <th scope="col" className="py-2 pr-4 font-medium text-stone-500 dark:text-stone-400">
              Day
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium text-stone-500 dark:text-stone-400">
              Shorts
            </th>
            <th scope="col" className="py-2 text-right font-medium text-stone-500 dark:text-stone-400">
              Unique
            </th>
          </tr>
        </thead>
        <tbody>
          {[...days].reverse().map((day) => (
            <tr
              key={day.day}
              className="border-b border-stone-100 last:border-0 dark:border-stone-800/60"
            >
              <th
                scope="row"
                className="py-1.5 pr-4 font-normal text-stone-700 dark:text-stone-300"
              >
                {formatDayLong(day.day)}
              </th>
              {/* tabular-nums here and not on the stat tiles: these are columns of
                  numbers that have to line up under each other. */}
              <td className="py-1.5 pr-4 text-right tabular-nums text-stone-900 dark:text-stone-100">
                {day.visits}
              </td>
              <td className="py-1.5 text-right tabular-nums text-stone-500 dark:text-stone-400">
                {day.unique_shorts}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
