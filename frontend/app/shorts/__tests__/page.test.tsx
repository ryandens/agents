import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ShortsDay } from "../types";

// Hoisted before the page import, so the page under test gets these and not the real
// chart — this file is about what the page asks for and what it does with the answer.
vi.mock("../ShortsChart", () => ({
  default: ({ days }: { days: ShortsDay[] }) => (
    <div data-testid="chart">{days.length} columns</div>
  ),
}));

vi.mock("../ShortsTable", () => ({
  default: ({ days }: { days: ShortsDay[] }) => (
    <div data-testid="table">{days.length} rows</div>
  ),
}));

const { default: ShortsPage } = await import("../page");

function day(iso: string, visits: number, unique = visits): ShortsDay {
  return { day: iso, visits, unique_shorts: unique };
}

const WEEK = [
  day("2026-07-27", 4),
  day("2026-07-28", 0),
  day("2026-07-29", 12, 9),
  day("2026-07-30", 0),
  day("2026-07-31", 2),
];

function mockFetch(days: ShortsDay[] = WEEK) {
  const fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(days) })
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function lastRequest(fetch: ReturnType<typeof mockFetch>): URL {
  const calls = fetch.mock.calls as unknown as [string][];
  return new URL(calls[calls.length - 1][0], "https://agents.example");
}

beforeEach(() => vi.unstubAllGlobals());
afterEach(() => vi.restoreAllMocks());

describe("ShortsPage", () => {
  it("asks for 30 days by default", async () => {
    const fetch = mockFetch();
    render(<ShortsPage />);

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(lastRequest(fetch).searchParams.get("days")).toBe("30");
  });

  it("sends the browser's time zone, so the days are cut where the reader is", async () => {
    // Without this the server cuts days in UTC and an evening of scrolling on the US
    // east coast lands on tomorrow's column.
    const fetch = mockFetch();
    render(<ShortsPage />);

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    const sent = lastRequest(fetch).searchParams.get("tz");
    expect(sent).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
    expect(sent).toBeTruthy();
  });

  it("refetches when the range changes", async () => {
    const user = userEvent.setup();
    const fetch = mockFetch();
    render(<ShortsPage />);
    await screen.findByTestId("chart");

    await user.click(screen.getByRole("button", { name: "90 days" }));

    await waitFor(() =>
      expect(lastRequest(fetch).searchParams.get("days")).toBe("90")
    );
  });

  it("marks the selected range", async () => {
    const user = userEvent.setup();
    mockFetch();
    render(<ShortsPage />);
    await screen.findByTestId("chart");

    expect(screen.getByRole("button", { name: "30 days" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    await user.click(screen.getByRole("button", { name: "7 days" }));
    expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(screen.getByRole("button", { name: "30 days" })).toHaveAttribute(
      "aria-pressed",
      "false"
    );
  });

  it("leads with today", async () => {
    // The last day of the range, at hero size. Today is 31 July in the fixture.
    mockFetch();
    render(<ShortsPage />);

    const today = await screen.findByText("Today");
    const tile = today.parentElement as HTMLElement;
    expect(within(tile).getByText("2")).toBeInTheDocument();
  });

  it("summarises the range alongside it", async () => {
    mockFetch();
    render(<ShortsPage />);

    await screen.findByTestId("chart");
    expect(screen.getByText("Daily average")).toBeInTheDocument();
    expect(screen.getByText("3.6")).toBeInTheDocument();
    expect(screen.getByText("Busiest day")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("Days with none")).toBeInTheDocument();
  });

  it("describes the days it got back, not the range it asked for", async () => {
    // The two agree every time the API behaves. When they do not, the average has to
    // be labelled with the days it was actually computed over — "over 30 days" on a
    // five-day answer is a claim the reader cannot check.
    mockFetch(WEEK);
    render(<ShortsPage />);

    await screen.findByTestId("chart");
    expect(screen.getByText("over 5 days")).toBeInTheDocument();
    expect(screen.getByText("of 5")).toBeInTheDocument();
  });

  it("hands the chart every day it was given", async () => {
    mockFetch();
    render(<ShortsPage />);
    expect(await screen.findByTestId("chart")).toHaveTextContent("5 columns");
  });

  it("swaps the chart for a table and back", async () => {
    // The table twin is the same data without needing to hover or to see colour.
    const user = userEvent.setup();
    mockFetch();
    render(<ShortsPage />);
    await screen.findByTestId("chart");

    await user.click(screen.getByRole("button", { name: "Show table" }));
    expect(screen.getByTestId("table")).toHaveTextContent("5 rows");
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show chart" }));
    expect(screen.getByTestId("chart")).toBeInTheDocument();
  });

  it("says so plainly when there is nothing to draw", async () => {
    mockFetch([day("2026-07-30", 0), day("2026-07-31", 0)]);
    render(<ShortsPage />);

    // "the last 2 days", from the two days that came back — the same rule the tiles
    // follow, so the empty state cannot claim a range it was not given.
    expect(await screen.findByText(/No Shorts in the last 2 days/)).toBeInTheDocument();
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
  });

  it("reports a failure and offers to try again", async () => {
    const user = userEvent.setup();
    const fetch = vi.fn(() => Promise.resolve({ ok: false, status: 503, json: () => {} }));
    vi.stubGlobal("fetch", fetch);
    render(<ShortsPage />);

    expect(await screen.findByText(/Failed to load \(503\)/)).toBeInTheDocument();

    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(WEEK) }))
    );
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByTestId("chart")).toBeInTheDocument();
  });

  it("holds the previous render while the next one loads", async () => {
    // No skeleton and no layout jump on a range change — the columns and the tiles
    // stay where they are and fade rather than disappearing.
    const user = userEvent.setup();
    let release: (value: unknown) => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(WEEK) })
        .mockImplementationOnce(
          () => new Promise((resolve) => (release = resolve))
        )
    );
    render(<ShortsPage />);
    const chart = await screen.findByTestId("chart");

    await user.click(screen.getByRole("button", { name: "7 days" }));
    expect(chart).toBeInTheDocument();
    expect(chart.parentElement?.parentElement).toHaveClass("opacity-50");

    release({ ok: true, json: () => Promise.resolve(WEEK) });
    await waitFor(() =>
      expect(chart.parentElement?.parentElement).toHaveClass("opacity-100")
    );
  });
});
