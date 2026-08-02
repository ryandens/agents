import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import ShortsChart from "../ShortsChart";
import type { ShortsDay } from "../types";

function day(iso: string, visits: number, unique = visits): ShortsDay {
  return { day: iso, visits, unique_shorts: unique };
}

const WEEK = [
  day("2026-07-27", 4),
  day("2026-07-28", 0),
  day("2026-07-29", 12, 9),
  day("2026-07-30", 1),
  day("2026-07-31", 2),
];

/** Each column is a button, so this is the whole chart in the order it is drawn. */
function columns() {
  return screen.getAllByRole("button");
}

describe("ShortsChart", () => {
  it("draws a column per day, left to right", () => {
    render(<ShortsChart days={WEEK} />);
    expect(columns()).toHaveLength(5);
    expect(columns()[0]).toHaveAccessibleName(/July 27/);
    expect(columns()[4]).toHaveAccessibleName(/July 31/);
  });

  it("names every column's numbers without needing a pointer", () => {
    // The chart is not the only way to read a value, and a column is not a decoration
    // that a screen reader has to guess at.
    render(<ShortsChart days={WEEK} />);
    expect(columns()[2]).toHaveAccessibleName("Wednesday, July 29: 12 Shorts, 9 unique");
  });

  it("says Short rather than Shorts for a single one", () => {
    render(<ShortsChart days={WEEK} />);
    expect(columns()[3]).toHaveAccessibleName(/: 1 Short,/);
  });

  it("scales columns against the axis top, not against each other", () => {
    // 12 with a top of 20 is 60% — not 100%, which is what "tallest column fills the
    // plot" would give and would make every chart look equally alarming.
    render(<ShortsChart days={WEEK} />);
    const bar = columns()[2].querySelector("span");
    expect(bar).toHaveStyle({ height: "60%" });
  });

  it("keeps a single Short visible", () => {
    // At a 20-unit axis one Short is 5% of 240px — 12px, fine. At a 200-unit axis it
    // is under three, so the bar carries a floor and a quiet day never reads as zero.
    render(<ShortsChart days={[day("2026-07-27", 1), day("2026-07-28", 200)]} />);
    const bar = columns()[0].querySelector("span");
    expect(bar).toHaveStyle({ minHeight: "3px" });
  });

  it("labels only the busiest column", () => {
    render(<ShortsChart days={WEEK} />);
    // A number on every column is chaos and goes unread; the extreme is the one worth
    // printing, and the tooltip carries the rest.
    expect(within(columns()[2]).getByText("12")).toBeInTheDocument();
    expect(within(columns()[0]).queryByText("4")).not.toBeInTheDocument();
  });

  it("prints no direct label when nothing was watched", () => {
    // The axis still reads 0 at the baseline; what must not appear is a "0" printed
    // on a column, which would label an extreme that does not exist.
    render(<ShortsChart days={[day("2026-07-27", 0), day("2026-07-28", 0)]} />);
    for (const column of columns()) {
      expect(within(column).queryByText("0")).not.toBeInTheDocument();
    }
  });

  it("always labels the most recent day on the axis", () => {
    // The stride is anchored to the end of the range, so today is labelled whatever
    // the range length does to the spacing.
    render(<ShortsChart days={WEEK} />);
    expect(screen.getByText("Jul 31")).toBeInTheDocument();
  });

  it("thins the axis labels on a long range", () => {
    const ninety = Array.from({ length: 90 }, (_, index) => {
      const date = new Date(2026, 4, 1 + index);
      const iso = [
        date.getFullYear(),
        String(date.getMonth() + 1).padStart(2, "0"),
        String(date.getDate()).padStart(2, "0"),
      ].join("-");
      return day(iso, index % 7);
    });

    render(<ShortsChart days={ninety} />);
    // Every column is still there; only the labels under them are thinned.
    expect(columns()).toHaveLength(90);
    const labelled = screen
      .getAllByText(/^[A-Z][a-z]{2} \d+$/)
      .filter((node) => node.textContent);
    expect(labelled.length).toBeLessThanOrEqual(8);
  });

  it("shows a value on hover and takes it away again", async () => {
    const user = userEvent.setup();
    render(<ShortsChart days={WEEK} />);

    await user.hover(columns()[2]);
    expect(screen.getByText("12 Shorts")).toBeInTheDocument();
    expect(screen.getByText(/9 unique · Wednesday, July 29/)).toBeInTheDocument();

    await user.unhover(columns()[2]);
    expect(screen.queryByText("12 Shorts")).not.toBeInTheDocument();
  });

  it("shows the same detail on keyboard focus as on hover", async () => {
    // A tooltip only a pointer can reach gates the value behind having a mouse.
    const user = userEvent.setup();
    render(<ShortsChart days={WEEK} />);

    await user.tab();
    expect(screen.getByText("4 Shorts")).toBeInTheDocument();

    await user.tab();
    expect(screen.queryByText("4 Shorts")).not.toBeInTheDocument();
    expect(screen.getByText("0 Shorts")).toBeInTheDocument();
  });

  it("shows one tooltip at a time", async () => {
    const user = userEvent.setup();
    render(<ShortsChart days={WEEK} />);

    await user.hover(columns()[0]);
    await user.hover(columns()[4]);
    expect(screen.queryByText("4 Shorts")).not.toBeInTheDocument();
    expect(screen.getByText("2 Shorts")).toBeInTheDocument();
  });

  it("renders a day with nothing as a hoverable zero rather than a gap", async () => {
    const user = userEvent.setup();
    render(<ShortsChart days={WEEK} />);

    await user.hover(columns()[1]);
    expect(screen.getByText("0 Shorts")).toBeInTheDocument();
  });
});
