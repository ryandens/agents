import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import RedditPage from "../page";
import type { RedditReport } from "../types";

const report: RedditReport = {
  days: [
    {
      day: "2026-07-27",
      has_history: true,
      visits: 4,
      raw_visits: 9,
      unique_posts: 2,
    },
    {
      day: "2026-07-28",
      has_history: false,
      visits: 0,
      raw_visits: 0,
      unique_posts: 0,
    },
    {
      day: "2026-07-29",
      has_history: true,
      visits: 0,
      raw_visits: 0,
      unique_posts: 0,
    },
  ],
  subreddits: [
    { subreddit: "python", visits: 3, raw_visits: 7 },
    { subreddit: null, visits: 1, raw_visits: 2 },
  ],
};

function mockFetch(
  options: { total?: number; hasFailed?: boolean; data?: RedditReport } = {},
) {
  const fetch = vi.fn(async (input: string) => {
    const url = new URL(input, "https://agents.example");
    const raw = url.pathname.endsWith("/visits");
    return {
      ok: !options.hasFailed,
      status: options.hasFailed ? 500 : 200,
      json: async () =>
        raw
          ? {
              visits: [
                {
                  timestamp: "2026-07-27T12:00:00Z",
                  url: "https://old.reddit.com/r/python/comments/abc123/example/?sort=new",
                  title: "Example post",
                  subreddit: "python",
                },
              ],
              total: options.total ?? 1,
              limit: 50,
              offset: Number(url.searchParams.get("offset") ?? 0),
            }
          : (options.data ?? report),
    };
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
function urls(fetch: ReturnType<typeof mockFetch>, path: string) {
  return fetch.mock.calls
    .map(([input]) => new URL(input, "https://agents.example"))
    .filter((url) => url.pathname.endsWith(path));
}
afterEach(() => vi.unstubAllGlobals());

describe("Reddit tracker", () => {
  it("requests timezone-aware history and raw visits from existing records", async () => {
    const fetch = mockFetch();
    render(<RedditPage />);
    expect(
      await screen.findByRole("heading", {
        name: "Page opens per day · All Reddit",
      }),
    ).toBeInTheDocument();
    expect(urls(fetch, "/daily")[0].searchParams.get("days")).toBe("30");
    expect(urls(fetch, "/daily")[0].searchParams.get("tz")).toBeTruthy();
    const link = await screen.findByRole("link", { name: "Example post" });
    expect(link).toHaveAttribute(
      "href",
      "https://old.reddit.com/r/python/comments/abc123/example/?sort=new",
    );
    expect(
      screen.getByText(/without giving up your communities/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/free days|Nice work|Every.*is a win/i),
    ).not.toBeInTheDocument();
  });

  it("switches the graph to raw counts without another request", async () => {
    const user = userEvent.setup();
    const fetch = mockFetch();
    render(<RedditPage />);
    await screen.findByRole("heading", { name: /Page opens per day/ });
    await user.selectOptions(screen.getByLabelText("Measure"), "raw_visits");
    expect(
      screen.getByRole("heading", { name: /Raw visits per day/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /July 27: 9 raw visits/ }),
    ).toBeInTheDocument();
    expect(urls(fetch, "/daily")).toHaveLength(1);
  });

  it("keeps missing days distinct from recorded zeros and excludes them from averages", async () => {
    mockFetch();
    render(<RedditPage />);
    await screen.findByRole("heading", { name: /Page opens per day/ });
    expect(
      screen.getByRole("button", { name: /July 28: Not uploaded/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /July 29: 0 page opens/ }),
    ).toBeInTheDocument();
    expect(screen.getByText("over 2 uploaded days")).toBeInTheDocument();
    expect(
      screen.getByText("Needs two complete periods and a nonzero baseline"),
    ).toBeInTheDocument();
  });

  it("filters the chart and recorded visits by a selected subreddit", async () => {
    const user = userEvent.setup();
    const fetch = mockFetch();
    render(<RedditPage />);
    await screen.findByRole("heading", { name: /Page opens per day/ });
    await user.selectOptions(screen.getByLabelText("Subreddit"), "python");
    await screen.findByRole("heading", {
      name: "Page opens per day · r/python",
    });
    expect(urls(fetch, "/daily").at(-1)?.searchParams.get("subreddit")).toBe(
      "python",
    );
    expect(urls(fetch, "/visits").at(-1)?.searchParams.get("subreddit")).toBe(
      "python",
    );
    await user.click(
      screen.getByRole("button", { name: "Back to all Reddit" }),
    );
    await screen.findByRole("heading", {
      name: "Page opens per day · All Reddit",
    });
    expect(urls(fetch, "/daily").at(-1)?.searchParams.has("subreddit")).toBe(
      false,
    );
  });

  it("drills into unattributed pages from the community table", async () => {
    const user = userEvent.setup();
    const fetch = mockFetch();
    render(<RedditPage />);
    const table = await screen.findByRole("table", {
      name: "Subreddit breakdown",
    });
    await user.click(
      within(table).getByRole("button", { name: "Other Reddit pages" }),
    );
    await screen.findByRole("heading", {
      name: /Page opens per day · Other Reddit pages/,
    });
    expect(urls(fetch, "/daily").at(-1)?.searchParams.get("subreddit")).toBe(
      "__none__",
    );
  });

  it("selects a day from the chart, then clears it when changing ranges", async () => {
    const user = userEvent.setup();
    const fetch = mockFetch();
    render(<RedditPage />);
    await screen.findByRole("heading", { name: /Page opens per day/ });
    await user.click(
      screen.getByRole("button", { name: /July 27: 4 page opens/ }),
    );
    await waitFor(() =>
      expect(urls(fetch, "/visits").at(-1)?.searchParams.get("day")).toBe(
        "2026-07-27",
      ),
    );
    await user.click(screen.getByRole("button", { name: "7 days" }));
    await waitFor(() =>
      expect(urls(fetch, "/visits").at(-1)?.searchParams.get("days")).toBe("7"),
    );
    expect(urls(fetch, "/visits").at(-1)?.searchParams.has("day")).toBe(false);
  });

  it("provides a daily table with raw counts and unique posts", async () => {
    const user = userEvent.setup();
    mockFetch();
    render(<RedditPage />);
    await screen.findByRole("heading", { name: /Page opens per day/ });
    await user.click(screen.getByRole("button", { name: "Show table" }));
    const table = screen.getByRole("table", {
      name: "Reddit activity by day, newest first",
    });
    expect(
      within(table).getByRole("columnheader", { name: "Unique posts" }),
    ).toBeInTheDocument();
    expect(within(table).getByText("Not uploaded")).toBeInTheDocument();
    await user.click(within(table).getByRole("button", { name: /July 27/ }));
    expect(
      screen.getByRole("button", { name: "All days in range" }),
    ).toBeInTheDocument();
  });

  it("paginates raw records and resets pagination when filtering", async () => {
    const user = userEvent.setup();
    const fetch = mockFetch({ total: 51 });
    render(<RedditPage />);
    await screen.findByRole("link", { name: "Example post" });
    await user.click(screen.getByRole("button", { name: "Next visits" }));
    await waitFor(() =>
      expect(urls(fetch, "/visits").at(-1)?.searchParams.get("offset")).toBe(
        "50",
      ),
    );
    await screen.findByRole("link", { name: "Example post" });
    expect(screen.getByRole("button", { name: "Next visits" })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("Subreddit"), "python");
    await waitFor(() =>
      expect(urls(fetch, "/visits").at(-1)?.searchParams.get("offset")).toBe(
        "0",
      ),
    );
  });

  it("offers retry when history fails to load", async () => {
    const user = userEvent.setup();
    const options = { hasFailed: true };
    mockFetch(options);
    render(<RedditPage />);
    await screen.findAllByRole("alert");
    options.hasFailed = false;
    await user.click(screen.getAllByRole("button", { name: "Retry" })[0]);
    expect(
      await screen.findByRole("heading", { name: /Page opens per day/ }),
    ).toBeInTheDocument();
  });
  it("compares completed periods and excludes the partial current day", async () => {
    const data: RedditReport = {
      ...report,
      days: [10, 10, 5, 5, 999].map((visits, index) => ({
        day: `2026-07-${27 + index}`,
        has_history: true,
        visits,
        raw_visits: visits,
        unique_posts: 1,
      })),
    };
    mockFetch({ data });
    render(<RedditPage />);
    expect(await screen.findByText("-50%")).toBeInTheDocument();
    expect(
      screen.getByText(/Last 2 vs prior 2 complete days; excludes today/),
    ).toBeInTheDocument();
  });

  it("discards an old raw-record response after changing the subreddit", async () => {
    const user = userEvent.setup();
    let resolveOld: (value: unknown) => void = () => {
      throw new Error("The initial request has not started");
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const url = new URL(input, "https://agents.example");
        if (url.pathname.endsWith("/daily"))
          return { ok: true, json: async () => report };
        if (!url.searchParams.has("subreddit"))
          return new Promise((resolve) => {
            resolveOld = resolve;
          });
        return {
          ok: true,
          json: async () => ({ visits: [], total: 0, limit: 50, offset: 0 }),
        };
      }),
    );
    render(<RedditPage />);
    await screen.findByRole("heading", { name: /Page opens per day/ });
    await user.selectOptions(screen.getByLabelText("Subreddit"), "python");
    await screen.findByText("No Reddit visits recorded for this selection.");
    await act(async () => {
      resolveOld({
        ok: true,
        json: async () => ({
          visits: [
            {
              timestamp: "2026-07-27T12:00:00Z",
              url: "https://reddit.com/r/news",
              title: "Stale visit",
              subreddit: "news",
            },
          ],
          total: 1,
        }),
      });
    });
    expect(screen.queryByText("Stale visit")).not.toBeInTheDocument();
    expect(
      screen.getByText("No Reddit visits recorded for this selection."),
    ).toBeInTheDocument();
  });
});
