"use client";

import { useEffect, useState } from "react";
import { formatDayLong, summarise } from "./chart";
import ShortsChart from "./ShortsChart";
import ShortsTable from "./ShortsTable";
import { DEFAULT_RANGE, RANGES, Range, ShortsDay } from "./types";

/**
 * The browser's own time zone, sent with every request.
 *
 * The server has no idea which day the reader is having — it runs in UTC and the
 * visits are stored in UTC — so the one machine that does know has to say. Without
 * this, an evening of scrolling on the US east coast lands on tomorrow's column.
 */
function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

export default function ShortsPage() {
  const [range, setRange] = useState<Range>(DEFAULT_RANGE);
  const [days, setDays] = useState<ShortsDay[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showTable, setShowTable] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  // Raised by whichever handler is about to change the query, not inside the effect:
  // a setState in an effect body costs a second render pass for something the click
  // already knew. Same shape as the pantry page.
  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const params = new URLSearchParams({
          days: String(range),
          tz: browserTimeZone(),
        });
        const res = await fetch(`/api/youtube-shorts/daily?${params}`);
        if (!res.ok) throw new Error(`Failed to load (${res.status})`);

        if (!cancelled) {
          setDays(await res.json());
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load Shorts history");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [range, reloadToken]);

  function changeRange(next: Range) {
    // Clicking the range you are already on is not a reload; without this guard it
    // would raise the loading flag that the effect it never re-runs would have cleared.
    if (next === range) return;
    setLoading(true);
    setRange(next);
  }

  function retry() {
    setLoading(true);
    setReloadToken((token) => token + 1);
  }

  const summary = summarise(days ?? []);

  return (
    <div className="flex h-full flex-col bg-stone-50 dark:bg-stone-950">
      <header className="shrink-0 border-b border-stone-200 bg-white px-6 py-4 dark:border-stone-800 dark:bg-stone-900">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-stone-900 dark:text-stone-50">
              YouTube Shorts
            </h1>
            <p className="mt-0.5 text-xs text-stone-500 dark:text-stone-400">
              Shorts you opened each day, from your Safari history
            </p>
          </div>
          <button
            onClick={() => setShowTable((shown) => !shown)}
            className="rounded-lg px-3 py-1.5 text-sm font-medium text-stone-600 transition-colors hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-stone-800"
            aria-pressed={showTable}
          >
            {showTable ? "Show chart" : "Show table"}
          </button>
        </div>

        {/* One filter row, above everything it scopes — the chart, the tiles and the
            table all re-render against the same slice, so the numbers always agree. */}
        <div className="mt-3 flex gap-1">
          {RANGES.map((option) => (
            <button
              key={option}
              onClick={() => changeRange(option)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                range === option
                  ? "bg-emerald-600 text-white"
                  : "text-stone-600 hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-stone-800"
              }`}
              aria-pressed={range === option}
            >
              {option} days
            </button>
          ))}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {error ? (
          <div className="flex h-32 flex-col items-center justify-center gap-2">
            <p className="text-sm text-red-500">{error}</p>
            <button
              onClick={retry}
              className="text-xs text-emerald-600 hover:underline"
            >
              Retry
            </button>
          </div>
        ) : days === null ? (
          <div className="flex h-32 items-center justify-center text-sm text-stone-400">
            Loading…
          </div>
        ) : (
          // Refetching holds the previous render at reduced opacity rather than
          // dropping back to a skeleton: the axis, the columns and the tiles all keep
          // their places, so changing the range does not make the page jump.
          <div
            className={`mx-auto flex max-w-5xl flex-col gap-4 transition-opacity ${
              loading ? "opacity-50" : "opacity-100"
            }`}
          >
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <HeroTile
                label="Today"
                value={summary.today?.visits ?? 0}
                detail={
                  summary.today ? `${summary.today.unique_shorts} unique` : "no data"
                }
              />
              {/* Described by what came back, not by what was asked for. The two are
                  the same number every time the API behaves, and when they are not,
                  the average is over the days it was actually computed from — a tile
                  reading "21.5 over 30 days" for ninety days of data is a lie the
                  reader has no way to catch. */}
              <StatTile
                label="Daily average"
                value={summary.average}
                detail={`over ${days.length} days`}
              />
              <StatTile
                label="Busiest day"
                value={summary.busiest?.visits ?? 0}
                detail={summary.busiest ? formatDayLong(summary.busiest.day) : "none yet"}
              />
              <StatTile
                label="Days with none"
                value={summary.cleanDays}
                detail={`of ${days.length}`}
              />
            </div>

            <section className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
              <h2 className="text-sm font-medium text-stone-700 dark:text-stone-300">
                Shorts per day
              </h2>
              {summary.total === 0 && !loading ? (
                <p className="py-12 text-center text-sm text-stone-400">
                  No Shorts in the last {days.length} days. Either a good week, or the
                  exporter has not run yet — <code>just cli-status</code> says which.
                </p>
              ) : showTable ? (
                <div className="mt-3">
                  <ShortsTable days={days} />
                </div>
              ) : (
                <ShortsChart days={days} />
              )}
            </section>

            <p className="text-xs text-stone-400 dark:text-stone-500">
              One count per Shorts page Safari recorded, so swiping through the feed
              without the address bar changing is not counted separately. Private
              browsing is never recorded at all.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * The one number the page leads with, at the size that says so.
 *
 * Proportional figures, not tabular: `tabular-nums` gives every digit the width of a
 * zero, which looks loose at this size. The table is where digits have to line up.
 */
function HeroTile({
  label,
  value,
  detail,
}: {
  label: string;
  value: number;
  detail: string;
}) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="text-xs font-medium text-stone-500 dark:text-stone-400">
        {label}
      </div>
      <div className="mt-1 text-5xl leading-none font-semibold text-stone-900 dark:text-stone-50">
        {value}
      </div>
      <div className="mt-1.5 text-xs text-stone-400 dark:text-stone-500">{detail}</div>
    </div>
  );
}

function StatTile({
  label,
  value,
  detail,
}: {
  label: string;
  value: number;
  detail: string;
}) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900">
      <div className="text-xs font-medium text-stone-500 dark:text-stone-400">
        {label}
      </div>
      <div className="mt-1 text-2xl leading-none font-semibold text-stone-900 dark:text-stone-50">
        {value}
      </div>
      <div className="mt-1.5 text-xs text-stone-400 dark:text-stone-500">{detail}</div>
    </div>
  );
}
