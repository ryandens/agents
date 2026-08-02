import { describe, expect, it } from "vitest";
import {
  axisTicks,
  formatDay,
  labelStride,
  niceMax,
  parseDay,
  summarise,
} from "../chart";
import type { ShortsDay } from "../types";

function day(iso: string, visits: number, unique = visits): ShortsDay {
  return { day: iso, visits, unique_shorts: unique };
}

describe("parseDay", () => {
  it("reads an API date as a local calendar day", () => {
    const parsed = parseDay("2026-08-01");
    expect(parsed.getFullYear()).toBe(2026);
    expect(parsed.getMonth()).toBe(7);
    expect(parsed.getDate()).toBe(1);
  });

  it("does not shift the date west of Greenwich", () => {
    // new Date("2026-08-01") is midnight UTC, which is 31 July in every American zone
    // — the whole graph would be drawn a day early. Comparing against the UTC parse is
    // what makes this test mean something rather than restate the implementation.
    expect(parseDay("2026-08-01").getDate()).toBe(1);
    expect(formatDay("2026-08-01")).toBe(
      new Date(2026, 7, 1).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      })
    );
  });
});

describe("niceMax", () => {
  it("gives an empty range a scale anyway", () => {
    expect(niceMax(0)).toBe(4);
  });

  it("rounds up to a clean number", () => {
    // A single Short tops the axis at 2, not at 1: the midpoint gridline has to land
    // on a whole number.
    expect(niceMax(1)).toBe(2);
    expect(niceMax(3)).toBe(4);
    expect(niceMax(5)).toBe(6);
    expect(niceMax(37)).toBe(40);
    expect(niceMax(61)).toBe(80);
    expect(niceMax(140)).toBe(200);
  });

  it("is never below the tallest column", () => {
    for (const tallest of [1, 2, 7, 9, 23, 99, 101, 999]) {
      expect(niceMax(tallest)).toBeGreaterThanOrEqual(tallest);
    }
  });

  it("puts the midpoint gridline on a whole number of Shorts", () => {
    // An axis labelled 2.5 would be marking a count that cannot happen.
    for (const tallest of [1, 3, 5, 9, 17, 44, 130, 700]) {
      expect(axisTicks(niceMax(tallest))[1] % 1).toBe(0);
    }
  });
});

describe("labelStride", () => {
  it("labels every day of a short range", () => {
    expect(labelStride(7)).toBe(1);
  });

  it("thins a long range to about eight labels", () => {
    expect(Math.ceil(30 / labelStride(30))).toBeLessThanOrEqual(8);
    expect(Math.ceil(90 / labelStride(90))).toBeLessThanOrEqual(8);
  });

  it("never returns zero", () => {
    expect(labelStride(0)).toBe(1);
  });
});

describe("summarise", () => {
  const week = [
    day("2026-07-27", 4),
    day("2026-07-28", 0),
    day("2026-07-29", 12, 9),
    day("2026-07-30", 0),
    day("2026-07-31", 2),
  ];

  it("adds up the range", () => {
    expect(summarise(week).total).toBe(18);
  });

  it("averages over every day, including the empty ones", () => {
    // 18 over 5 days, not 18 over the 3 days that had any — the point of the number
    // is the habit, and a day off is part of it.
    expect(summarise(week).average).toBe(3.6);
  });

  it("finds the busiest day", () => {
    expect(summarise(week).busiest?.day).toBe("2026-07-29");
  });

  it("counts the days with none", () => {
    expect(summarise(week).cleanDays).toBe(2);
  });

  it("treats the last day as today, since the range ends there", () => {
    expect(summarise(week).today?.day).toBe("2026-07-31");
  });

  it("gives ties to the earliest day", () => {
    const tied = [day("2026-07-27", 5), day("2026-07-28", 5)];
    expect(summarise(tied).busiest?.day).toBe("2026-07-27");
  });

  it("has no busiest day when nothing was watched", () => {
    const quiet = [day("2026-07-27", 0), day("2026-07-28", 0)];
    expect(summarise(quiet).busiest).toBeNull();
    expect(summarise(quiet).cleanDays).toBe(2);
  });

  it("survives an empty range", () => {
    expect(summarise([])).toEqual({
      today: null,
      total: 0,
      average: 0,
      busiest: null,
      cleanDays: 0,
    });
  });
});
