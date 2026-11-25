"use client";

import { useEffect, useState } from "react";
import { formatDayLong } from "../shorts/chart";
import { DEFAULT_RANGE, RANGES, type Range } from "../shorts/types";
import RedditChart from "./RedditChart";
import {
  communityName,
  NO_SUBREDDIT,
  type Metric,
  type RedditReport,
  type RedditVisits,
} from "./types";

const card =
  "rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-800 dark:bg-stone-900";
const control =
  "rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-sm text-stone-700 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-200";
const action =
  "rounded-lg px-3 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-40 dark:text-emerald-400 dark:hover:bg-emerald-950";
const PAGE_SIZE = 50;

function query(range: Range, subreddit: string): URLSearchParams {
  const params = new URLSearchParams({
    days: String(range),
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  });
  if (subreddit) params.set("subreddit", subreddit);
  return params;
}

export default function RedditPage() {
  const [range, setRange] = useState<Range>(DEFAULT_RANGE);
  const [subreddit, setSubreddit] = useState("");
  const [metric, setMetric] = useState<Metric>("visits");
  const [day, setDay] = useState("");
  const [offset, setOffset] = useState(0);
  const [showTable, setShowTable] = useState(false);
  const [retry, setRetry] = useState(0);
  const [report, setReport] = useState<{
    key: string;
    data?: RedditReport;
    error?: string;
  } | null>(null);
  const [records, setRecords] = useState<{
    key: string;
    data?: RedditVisits;
    error?: string;
  } | null>(null);
  const reportKey = `${range}:${subreddit}:${retry}`;
  const visitsKey = `${reportKey}:${day}:${offset}`;

  useEffect(() => {
    let cancelled = false;
    const params = query(range, subreddit);
    void fetch(`/api/reddit/daily?${params}`)
      .then(async (res) => {
        if (!res.ok)
          throw new Error(`Failed to load Reddit history (${res.status})`);
        const data: RedditReport = await res.json();
        if (!cancelled) setReport({ key: reportKey, data });
      })
      .catch((error) => {
        if (!cancelled)
          setReport({
            key: reportKey,
            error:
              error instanceof Error
                ? error.message
                : "Failed to load Reddit history",
          });
      });
    return () => {
      cancelled = true;
    };
  }, [range, subreddit, reportKey]);

  useEffect(() => {
    let cancelled = false;
    const params = query(range, subreddit);
    if (day) params.set("day", day);
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(offset));
    void fetch(`/api/reddit/visits?${params}`)
      .then(async (res) => {
        if (!res.ok)
          throw new Error(`Failed to load recorded visits (${res.status})`);
        const data: RedditVisits = await res.json();
        if (!cancelled) setRecords({ key: visitsKey, data });
      })
      .catch((error) => {
        if (!cancelled)
          setRecords({
            key: visitsKey,
            error:
              error instanceof Error
                ? error.message
                : "Failed to load recorded visits",
          });
      });
    return () => {
      cancelled = true;
    };
  }, [range, subreddit, day, offset, visitsKey]);

  function selectSubreddit(next: string) {
    setSubreddit(next);
    setOffset(0);
  }
  function selectDay(next: string) {
    setDay(next);
    setOffset(0);
  }
  const current = report?.key === reportKey ? report : null;
  const listing = records?.key === visitsKey ? records : null;
  const days = current?.data?.days ?? [];
  const uploaded = days.filter((d) => d.has_history);
  const total = uploaded.reduce((sum, d) => sum + d[metric], 0);
  const average = uploaded.length
    ? Math.round((total / uploaded.length) * 10) / 10
    : "—";
  const today = days.at(-1);
  // Compare equal halves of completed days; missing history must not look like a reduction.
  const completed = days.slice(0, -1);
  const half = Math.floor(completed.length / 2);
  const comparison = completed.slice(-half * 2);
  const complete = half > 0 && comparison.every((d) => d.has_history);
  const previous = comparison
    .slice(0, half)
    .reduce((sum, d) => sum + d[metric], 0);
  const recent = comparison.slice(half).reduce((sum, d) => sum + d[metric], 0);
  const change =
    complete && previous > 0
      ? Math.round(((recent - previous) / previous) * 100)
      : null;
  const metricLabel = metric === "visits" ? "Page opens" : "Raw visits";
  const scope = subreddit
    ? communityName(subreddit === NO_SUBREDDIT ? null : subreddit)
    : "All Reddit";

  return (
    <div className="flex h-full flex-col bg-stone-50 dark:bg-stone-950">
      <header className="shrink-0 border-b border-stone-200 bg-white px-6 py-4 dark:border-stone-800 dark:bg-stone-900">
        <h1 className="text-lg font-semibold text-stone-900 dark:text-stone-50">
          Reddit
        </h1>
        <p className="mt-0.5 text-xs text-stone-500 dark:text-stone-400">
          Make room for intentional browsing. Less scrolling, without giving up
          your communities.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="flex gap-1" aria-label="Date range">
            {RANGES.map((option) => (
              <button
                key={option}
                aria-pressed={range === option}
                onClick={() => {
                  setRange(option);
                  selectDay("");
                }}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium ${range === option ? "bg-emerald-600 text-white" : "text-stone-600 hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-stone-800"}`}
              >
                {option} days
              </button>
            ))}
          </div>
          <label className="sr-only" htmlFor="reddit-community">
            Subreddit
          </label>
          <select
            id="reddit-community"
            className={control}
            value={subreddit}
            onChange={(e) => selectSubreddit(e.target.value)}
          >
            <option value="">All Reddit</option>
            {(current?.data?.subreddits ?? []).map((row) => (
              <option
                key={row.subreddit ?? NO_SUBREDDIT}
                value={row.subreddit ?? NO_SUBREDDIT}
              >
                {communityName(row.subreddit)}
              </option>
            ))}
            {subreddit &&
              !current?.data?.subreddits.some(
                (row) => (row.subreddit ?? NO_SUBREDDIT) === subreddit,
              ) && <option value={subreddit}>{scope}</option>}
          </select>
          <label className="sr-only" htmlFor="reddit-metric">
            Measure
          </label>
          <select
            id="reddit-metric"
            className={control}
            value={metric}
            onChange={(e) => setMetric(e.target.value as Metric)}
          >
            <option value="visits">Estimated page opens</option>
            <option value="raw_visits">Raw site visits</option>
          </select>
        </div>
      </header>
      <div className="flex-1 overflow-y-auto px-6 py-4">
        <div className="mx-auto flex max-w-5xl flex-col gap-4">
          {current?.error ? (
            <ErrorMessage
              message={current.error}
              retry={() => setRetry((n) => n + 1)}
            />
          ) : !current?.data ? (
            <p
              className="py-12 text-center text-sm text-stone-400"
              role="status"
            >
              Loading Reddit history…
            </p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Tile
                  label="Today"
                  value={today?.has_history ? today[metric] : "—"}
                  detail={
                    today?.has_history
                      ? `${metricLabel.toLowerCase()} so far`
                      : "Not uploaded"
                  }
                />
                <Tile
                  label="Daily average"
                  value={average}
                  detail={`over ${uploaded.length} uploaded days`}
                />
                <Tile
                  label="Total"
                  value={uploaded.length ? total : "—"}
                  detail={`${metricLabel.toLowerCase()} · ${scope}`}
                />
                <Tile
                  label="Recent trend"
                  value={
                    change === null ? "—" : `${change > 0 ? "+" : ""}${change}%`
                  }
                  detail={
                    change === null
                      ? "Needs two complete periods and a nonzero baseline"
                      : `Last ${half} vs prior ${half} complete days; excludes today`
                  }
                />
              </div>
              <section className={card}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-sm font-medium text-stone-700 dark:text-stone-300">
                    {metricLabel} per day · {scope}
                  </h2>
                  <button
                    className={action}
                    onClick={() => setShowTable((v) => !v)}
                    aria-pressed={showTable}
                  >
                    {showTable ? "Show chart" : "Show table"}
                  </button>
                </div>
                <p className="mt-1 text-xs text-stone-500">
                  {uploaded.length} of {days.length} days uploaded. Missing days
                  are unknown and excluded from averages. Select a day to
                  inspect its visits.
                </p>
                {uploaded.length === 0 && (
                  <p className="mt-4 text-sm text-stone-500">
                    No history uploaded for this range yet.
                  </p>
                )}
                {showTable ? (
                  <div className="mt-3 max-h-96 overflow-auto">
                    <table className="w-full text-left text-sm">
                      <caption className="sr-only">
                        Reddit activity by day, newest first
                      </caption>
                      <thead>
                        <tr>
                          <th className="py-2">Day</th>
                          <th className="text-right">Page opens</th>
                          <th className="text-right">Raw visits</th>
                          <th className="text-right">Unique posts</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...days].reverse().map((d) => (
                          <tr
                            key={d.day}
                            className="border-t border-stone-100 dark:border-stone-800"
                          >
                            <th className="py-2 text-left font-normal">
                              <button
                                className="text-emerald-700 hover:underline dark:text-emerald-400"
                                onClick={() => selectDay(d.day)}
                              >
                                {formatDayLong(d.day)}
                              </button>
                            </th>
                            <td className="text-right tabular-nums">
                              {d.has_history ? d.visits : "Not uploaded"}
                            </td>
                            <td className="text-right tabular-nums">
                              {d.has_history ? d.raw_visits : "—"}
                            </td>
                            <td className="text-right tabular-nums">
                              {d.has_history ? d.unique_posts : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <RedditChart
                    days={days}
                    metric={metric}
                    selectedDay={day}
                    onSelect={selectDay}
                  />
                )}
              </section>
              <section className={card}>
                <h2 className="text-sm font-medium text-stone-700 dark:text-stone-300">
                  By subreddit
                </h2>
                <p className="mt-1 text-xs text-stone-500">
                  Across all Reddit in this date range. Select a community to
                  drill down.
                </p>
                {current.data.subreddits.length ? (
                  <div className="mt-3 max-h-72 overflow-auto">
                    <table className="w-full text-left text-sm">
                      <caption className="sr-only">Subreddit breakdown</caption>
                      <thead>
                        <tr>
                          <th className="py-2">Community</th>
                          <th className="text-right">Page opens</th>
                          <th className="text-right">Raw visits</th>
                        </tr>
                      </thead>
                      <tbody>
                        {current.data.subreddits.map((row) => (
                          <tr
                            key={row.subreddit ?? NO_SUBREDDIT}
                            className="border-t border-stone-100 dark:border-stone-800"
                          >
                            <th className="py-2 font-normal">
                              <button
                                className="text-emerald-700 hover:underline dark:text-emerald-400"
                                onClick={() =>
                                  selectSubreddit(row.subreddit ?? NO_SUBREDDIT)
                                }
                              >
                                {communityName(row.subreddit)}
                              </button>
                            </th>
                            <td className="text-right tabular-nums">
                              {row.visits}
                            </td>
                            <td className="text-right tabular-nums">
                              {row.raw_visits}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="mt-3 text-sm text-stone-500">
                    No Reddit visits recorded in this range.
                  </p>
                )}
                {subreddit && (
                  <button
                    className={`${action} mt-2`}
                    onClick={() => selectSubreddit("")}
                  >
                    Back to all Reddit
                  </button>
                )}
              </section>
            </>
          )}
          <section className={card} aria-busy={!listing}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-medium text-stone-700 dark:text-stone-300">
                Recorded visits · {scope}
                {day ? ` · ${formatDayLong(day)}` : ""}
              </h2>
              {day && (
                <button className={action} onClick={() => selectDay("")}>
                  All days in range
                </button>
              )}
            </div>
            <p className="mt-1 text-xs text-stone-500">
              Stored Safari records, including reloads and redirects. These are
              page visits, not minutes spent.
            </p>
            {listing?.error ? (
              <ErrorMessage
                message={listing.error}
                retry={() => setRetry((n) => n + 1)}
              />
            ) : !listing?.data ? (
              <p className="py-6 text-sm text-stone-400" role="status">
                Loading recorded visits…
              </p>
            ) : (
              <>
                <p className="mt-3 text-xs text-stone-500">
                  {listing.data.total} recorded visits
                  {listing.data.total > 0
                    ? ` · ${offset + 1}–${Math.min(offset + PAGE_SIZE, listing.data.total)}`
                    : ""}
                </p>
                {listing.data.visits.length ? (
                  <ul className="mt-2 divide-y divide-stone-100 dark:divide-stone-800">
                    {listing.data.visits.map((visit) => (
                      <li
                        key={`${visit.timestamp}:${visit.url}`}
                        className="py-3 text-sm"
                      >
                        <a
                          href={visit.url}
                          target="_blank"
                          rel="noreferrer"
                          className="block break-words text-emerald-700 hover:underline dark:text-emerald-400"
                        >
                          {visit.title || visit.url}
                        </a>
                        <p className="mt-0.5 break-all text-xs text-stone-400">
                          {visit.url}
                        </p>
                        <p className="mt-1 text-xs text-stone-500">
                          <time dateTime={visit.timestamp}>
                            {new Date(visit.timestamp).toLocaleString()}
                          </time>
                          {" · "}
                          <button
                            className="hover:underline"
                            onClick={() =>
                              selectSubreddit(visit.subreddit ?? NO_SUBREDDIT)
                            }
                          >
                            {communityName(visit.subreddit)}
                          </button>
                        </p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="py-6 text-sm text-stone-500">
                    No Reddit visits recorded for this selection.
                  </p>
                )}
                <div className="mt-2 flex gap-2">
                  <button
                    className={action}
                    disabled={offset === 0}
                    onClick={() => setOffset((n) => Math.max(0, n - PAGE_SIZE))}
                  >
                    Previous visits
                  </button>
                  <button
                    className={action}
                    disabled={offset + PAGE_SIZE >= listing.data.total}
                    onClick={() => setOffset((n) => n + PAGE_SIZE)}
                  >
                    Next visits
                  </button>
                </div>
              </>
            )}
          </section>
          <p className="pb-3 text-xs text-stone-400">
            Page opens collapse repeat records for the same post or page within
            two minutes, across reddit.com hosts and query strings. Subreddits
            come from the URL; home, search, profiles, and links without a
            community stay under Other Reddit pages. Visits cannot establish
            time spent, votes, or app usage. Private browsing is never recorded.
            Some history on a day does not guarantee a full day has synced.
          </p>
        </div>
      </div>
    </div>
  );
}

function Tile({
  label,
  value,
  detail,
}: {
  label: string;
  value: number | string;
  detail: string;
}) {
  return (
    <div className={card}>
      <div className="text-xs font-medium text-stone-500">{label}</div>
      <div className="mt-1 text-3xl font-semibold text-stone-900 dark:text-stone-50">
        {value}
      </div>
      <div className="mt-1.5 text-xs text-stone-400">{detail}</div>
    </div>
  );
}
function ErrorMessage({
  message,
  retry,
}: {
  message: string;
  retry: () => void;
}) {
  return (
    <div className="py-6 text-center">
      <p role="alert" className="text-sm text-red-500">
        {message}
      </p>
      <button className={action} onClick={retry}>
        Retry
      </button>
    </div>
  );
}
