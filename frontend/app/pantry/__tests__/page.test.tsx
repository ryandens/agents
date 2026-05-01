import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PantryItem } from "../types";

// Mocks must be at module top level — vi.mock is hoisted before imports
vi.mock("../../components/AuthProvider", () => ({
  useAuth: () => ({ token: "test-token" }),
}));

vi.mock("../PantryForm", () => ({
  default: ({
    onSaved,
    onClose,
    defaultLocation,
  }: {
    onSaved: (i: PantryItem) => void;
    onClose: () => void;
    defaultLocation?: string;
  }) => (
    <div data-testid="pantry-form" data-location={defaultLocation ?? "none"}>
      <button onClick={() => onSaved(OLIVE_OIL)}>Save</button>
      <button onClick={onClose}>Close</button>
    </div>
  ),
}));

vi.mock("../PantryItemCard", () => ({
  default: ({
    item,
    onEdit,
    onDeleted,
  }: {
    item: PantryItem;
    onEdit: (i: PantryItem) => void;
    onDeleted: (id: string) => void;
  }) => (
    <div data-testid={`card-${item.id}`}>
      <span>{item.name}</span>
      <button onClick={() => onEdit(item)}>Edit {item.name}</button>
      <button onClick={() => onDeleted(item.id)}>Delete {item.name}</button>
    </div>
  ),
}));

// Import page AFTER mocks are registered
const { default: PantryPage } = await import("../page");

const OLIVE_OIL: PantryItem = {
  id: "aaa",
  name: "Olive Oil",
  brand: null,
  category: "condiments",
  storage_location: "pantry",
  quantity: 1,
  unit: "bottle",
  purchase_date: null,
  expiration_date: null,
  notes: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const PASTA: PantryItem = { ...OLIVE_OIL, id: "ccc", name: "Pasta", category: "grains" };
const MILK: PantryItem = {
  ...OLIVE_OIL,
  id: "bbb",
  name: "Whole Milk",
  category: "dairy",
  storage_location: "fridge",
};

function mockFetch(items: PantryItem[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve(items),
      })
    )
  );
}

beforeEach(() => vi.unstubAllGlobals());
afterEach(() => vi.restoreAllMocks());

describe("PantryPage", () => {
  it("fetches pantry items on mount with the pantry location", async () => {
    mockFetch([]);
    render(<PantryPage />);
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("location=pantry"),
        expect.anything()
      )
    );
  });

  it("renders item cards for fetched items", async () => {
    mockFetch([OLIVE_OIL]);
    render(<PantryPage />);
    await waitFor(() => expect(screen.getByText("Olive Oil")).toBeInTheDocument());
  });

  it("shows empty state when the pantry has no items", async () => {
    mockFetch([]);
    render(<PantryPage />);
    await waitFor(() => expect(screen.getByText("Your pantry is empty")).toBeInTheDocument());
  });

  it("switches to fridge tab and refetches with fridge location", async () => {
    mockFetch([]);
    render(<PantryPage />);
    await waitFor(() => screen.getByText("Your pantry is empty"));

    mockFetch([MILK]);
    fireEvent.click(screen.getByRole("button", { name: /Fridge/ }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("location=fridge"),
        expect.anything()
      )
    );
    await waitFor(() => expect(screen.getByText("Whole Milk")).toBeInTheDocument());
  });

  it("switches to freezer tab and fetches with freezer location", async () => {
    mockFetch([]);
    render(<PantryPage />);
    await waitFor(() => screen.getByText(/empty/));

    mockFetch([]);
    fireEvent.click(screen.getByRole("button", { name: /Freezer/ }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("location=freezer"),
        expect.anything()
      )
    );
  });

  it("shows empty state message specific to the active tab", async () => {
    mockFetch([]);
    render(<PantryPage />);
    await waitFor(() => screen.getByText(/empty/));

    mockFetch([]);
    fireEvent.click(screen.getByRole("button", { name: /Fridge/ }));
    await waitFor(() => expect(screen.getByText("Your fridge is empty")).toBeInTheDocument());
  });

  it("opens the form modal when Add item is clicked", async () => {
    mockFetch([]);
    render(<PantryPage />);
    await waitFor(() => screen.getByText(/empty/));

    fireEvent.click(screen.getByRole("button", { name: /\+ Add item/ }));
    expect(screen.getByTestId("pantry-form")).toBeInTheDocument();
  });

  it("passes the active tab as defaultLocation to the form", async () => {
    mockFetch([]);
    render(<PantryPage />);
    await waitFor(() => screen.getByText(/empty/));

    mockFetch([]);
    fireEvent.click(screen.getByRole("button", { name: /Fridge/ }));
    await waitFor(() => screen.getByText("Your fridge is empty"));

    fireEvent.click(screen.getByRole("button", { name: /\+ Add item/ }));
    expect(screen.getByTestId("pantry-form")).toHaveAttribute("data-location", "fridge");
  });

  it("adds the saved item to the list and closes the form", async () => {
    mockFetch([]);
    render(<PantryPage />);
    await waitFor(() => screen.getByText(/empty/));

    fireEvent.click(screen.getByRole("button", { name: /\+ Add item/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(screen.getByText("Olive Oil")).toBeInTheDocument());
    expect(screen.queryByTestId("pantry-form")).not.toBeInTheDocument();
  });

  it("removes an item from the list when deleted", async () => {
    mockFetch([OLIVE_OIL]);
    render(<PantryPage />);
    await waitFor(() => screen.getByText("Olive Oil"));

    fireEvent.click(screen.getByRole("button", { name: "Delete Olive Oil" }));
    expect(screen.queryByText("Olive Oil")).not.toBeInTheDocument();
  });

  it("shows category filter pills when items span multiple categories", async () => {
    mockFetch([OLIVE_OIL, PASTA]);
    render(<PantryPage />);
    await waitFor(() => screen.getByText("Olive Oil"));

    expect(screen.getByRole("button", { name: "All" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Condiments" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Grains" })).toBeInTheDocument();
  });

  it("does not show category pills when all items share one category", async () => {
    mockFetch([OLIVE_OIL]);
    render(<PantryPage />);
    await waitFor(() => screen.getByText("Olive Oil"));

    expect(screen.queryByRole("button", { name: "All" })).not.toBeInTheDocument();
  });

  it("hides items that don't match the selected category filter", async () => {
    mockFetch([OLIVE_OIL, PASTA]);
    render(<PantryPage />);
    await waitFor(() => screen.getByText("Pasta"));

    fireEvent.click(screen.getByRole("button", { name: "Condiments" }));
    expect(screen.getByText("Olive Oil")).toBeInTheDocument();
    expect(screen.queryByText("Pasta")).not.toBeInTheDocument();
  });

  it("restores all items when All filter is clicked", async () => {
    mockFetch([OLIVE_OIL, PASTA]);
    render(<PantryPage />);
    await waitFor(() => screen.getByText("Pasta"));

    fireEvent.click(screen.getByRole("button", { name: "Condiments" }));
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByText("Olive Oil")).toBeInTheDocument();
    expect(screen.getByText("Pasta")).toBeInTheDocument();
  });

  it("closes the form when the close button inside it is clicked", async () => {
    mockFetch([]);
    render(<PantryPage />);
    await waitFor(() => screen.getByText(/empty/));

    fireEvent.click(screen.getByRole("button", { name: /\+ Add item/ }));
    expect(screen.getByTestId("pantry-form")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByTestId("pantry-form")).not.toBeInTheDocument();
  });

  it("resets category filter when switching tabs", async () => {
    mockFetch([OLIVE_OIL, PASTA]);
    render(<PantryPage />);
    await waitFor(() => screen.getByText("Pasta"));

    fireEvent.click(screen.getByRole("button", { name: "Condiments" }));
    expect(screen.queryByText("Pasta")).not.toBeInTheDocument();

    // Switching tabs resets the filter to "All"
    mockFetch([MILK]);
    fireEvent.click(screen.getByRole("button", { name: /Fridge/ }));
    await waitFor(() => screen.getByText("Whole Milk"));

    // Back to pantry — filter should be cleared
    mockFetch([OLIVE_OIL, PASTA]);
    fireEvent.click(screen.getByRole("button", { name: /Pantry/ }));
    await waitFor(() => screen.getByText("Pasta"));
    expect(screen.getByText("Olive Oil")).toBeInTheDocument();
  });
});
