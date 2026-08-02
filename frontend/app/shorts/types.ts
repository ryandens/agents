/** One local calendar day, as `/api/youtube-shorts/daily` reports it. */
export interface ShortsDay {
  /** ISO date — `2026-08-01`. Already cut in the browser's own time zone. */
  day: string;
  /** Page loads of a Shorts URL that day. */
  visits: number;
  /** Distinct videos among them. Watching one Short four times is 4 and 1. */
  unique_shorts: number;
}

/**
 * The ranges the filter row offers, in days.
 *
 * 90 is the ceiling on what a column per day can still show honestly at the width of
 * a browser window; the API allows a year, and a range longer than this would want
 * weekly buckets rather than a narrower column.
 */
export const RANGES = [7, 30, 90] as const;

export type Range = (typeof RANGES)[number];

export const DEFAULT_RANGE: Range = 30;
