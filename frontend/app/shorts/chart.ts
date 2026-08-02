import type { ShortsDay } from "./types";

/**
 * Parse an API date as a *local* calendar day.
 *
 * `new Date("2026-08-01")` is midnight UTC, which formats as 31 July anywhere west of
 * Greenwich — so the whole graph would render a day early for the person it is about.
 * The backend already decided which local day each visit belongs to; these strings are
 * calendar dates, not instants, and have to be built as such.
 */
export function parseDay(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day);
}

/** `Aug 1` — the x-axis tick. */
export function formatDay(iso: string): string {
  return parseDay(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

/** `Saturday, August 1` — the tooltip and the table, where there is room to say it. */
export function formatDayLong(iso: string): string {
  return parseDay(iso).toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

/**
 * The top of the y-axis: the smallest clean number at or above the tallest column.
 *
 * The steps are all even so that the midpoint gridline is a whole number of Shorts —
 * an axis reading 2.5 would be labelling something that cannot happen, and there is no
 * 1× step here for that reason: a single Short would otherwise put the top at 1 and
 * the midpoint at a half. An empty range still gets a scale, because an axis with no
 * numbers on it looks broken rather than quiet.
 */
export function niceMax(tallest: number): number {
  if (tallest <= 0) return 4;
  const magnitude = 10 ** Math.floor(Math.log10(tallest));
  for (const step of [2, 4, 6, 8]) {
    const candidate = step * magnitude;
    if (candidate >= tallest) return candidate;
  }
  return 10 * magnitude;
}

/** Gridline values, bottom to top. Three lines: the axis carries the rest. */
export function axisTicks(top: number): number[] {
  return [0, top / 2, top];
}

/**
 * Show every nth date under the columns.
 *
 * 90 labels do not fit and would render as a grey smear, so thin them to about eight
 * and let the tooltip carry the exact date for every column.
 */
export function labelStride(count: number): number {
  return Math.max(1, Math.ceil(count / 8));
}

export interface Summary {
  /** The day the graph ends on — the one the reader is currently having. */
  today: ShortsDay | null;
  total: number;
  /** Mean over every day in the range, including the zeroes. One decimal place. */
  average: number;
  /** The tallest column, or null if nothing was watched at all. Ties go to the earliest. */
  busiest: ShortsDay | null;
  /** Days in the range with none at all — the number worth trying to grow. */
  cleanDays: number;
}

export function summarise(days: ShortsDay[]): Summary {
  const total = days.reduce((sum, day) => sum + day.visits, 0);
  // Deliberately no range-wide "unique Shorts" figure. The daily counts cannot be
  // added up — a video watched on Monday and again on Friday is one video and would
  // be counted twice — and answering it properly needs a question the API does not
  // ask. A number that is quietly wrong is worse than a number that is absent.
  const busiest = days.reduce<ShortsDay | null>(
    (best, day) => (day.visits > 0 && (!best || day.visits > best.visits) ? day : best),
    null
  );
  return {
    today: days.length > 0 ? days[days.length - 1] : null,
    total,
    average: days.length > 0 ? Math.round((total / days.length) * 10) / 10 : 0,
    busiest,
    cleanDays: days.filter((day) => day.visits === 0).length,
  };
}
