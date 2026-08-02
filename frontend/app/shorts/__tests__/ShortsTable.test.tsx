import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ShortsTable from "../ShortsTable";
import type { ShortsDay } from "../types";

const WEEK: ShortsDay[] = [
  { day: "2026-07-29", visits: 12, unique_shorts: 9 },
  { day: "2026-07-30", visits: 0, unique_shorts: 0 },
  { day: "2026-07-31", visits: 2, unique_shorts: 2 },
];

function rows() {
  return within(screen.getByRole("table")).getAllByRole("row").slice(1);
}

describe("ShortsTable", () => {
  it("lists the newest day first", () => {
    // The opposite of the chart's left-to-right order on purpose: a table is read from
    // the top and the day you want is almost always today.
    render(<ShortsTable days={WEEK} />);
    expect(rows()[0]).toHaveTextContent("July 31");
    expect(rows()[2]).toHaveTextContent("July 29");
  });

  it("carries both numbers for every day", () => {
    render(<ShortsTable days={WEEK} />);
    const busiest = rows()[2];
    expect(within(busiest).getByText("12")).toBeInTheDocument();
    expect(within(busiest).getByText("9")).toBeInTheDocument();
  });

  it("keeps the days with none", () => {
    // A table that dropped the empty days would not be the chart's twin — it would be
    // a different, shorter claim about the same range.
    render(<ShortsTable days={WEEK} />);
    expect(rows()).toHaveLength(3);
    expect(rows()[1]).toHaveTextContent("July 30");
  });

  it("names its columns", () => {
    render(<ShortsTable days={WEEK} />);
    expect(screen.getByRole("columnheader", { name: "Day" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Shorts" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Unique" })).toBeInTheDocument();
  });

  it("does not reorder the array it was handed", () => {
    // The page hands the same array to the chart, which draws it oldest-first.
    const days = [...WEEK];
    render(<ShortsTable days={days} />);
    expect(days.map((d) => d.day)).toEqual(WEEK.map((d) => d.day));
  });
});
