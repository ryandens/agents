import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../components/AuthProvider", () => ({
  useAuth: () => ({ token: "test-token" }),
}));

import PantryItemCard from "../PantryItemCard";
import type { PantryItem } from "../types";

const BASE: PantryItem = {
  id: "abc-123",
  name: "Olive Oil",
  brand: "California Olive Ranch",
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

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function withDate(date: string) {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(date));
}

describe("PantryItemCard", () => {
  it("renders name and brand", () => {
    render(<PantryItemCard item={BASE} onEdit={vi.fn()} onDeleted={vi.fn()} />);
    expect(screen.getByText("Olive Oil")).toBeInTheDocument();
    expect(screen.getByText("California Olive Ranch")).toBeInTheDocument();
  });

  it("renders quantity and unit for whole numbers", () => {
    render(<PantryItemCard item={BASE} onEdit={vi.fn()} onDeleted={vi.fn()} />);
    expect(screen.getByText("1 bottle")).toBeInTheDocument();
  });

  it("renders quantity with two decimal places for fractional amounts", () => {
    render(
      <PantryItemCard item={{ ...BASE, quantity: 0.5 }} onEdit={vi.fn()} onDeleted={vi.fn()} />
    );
    expect(screen.getByText("0.50 bottle")).toBeInTheDocument();
  });

  it("renders the category label", () => {
    render(<PantryItemCard item={BASE} onEdit={vi.fn()} onDeleted={vi.fn()} />);
    expect(screen.getByText("Condiments")).toBeInTheDocument();
  });

  it("shows No expiry badge when expiration_date is null", () => {
    render(<PantryItemCard item={BASE} onEdit={vi.fn()} onDeleted={vi.fn()} />);
    expect(screen.getByText("No expiry")).toBeInTheDocument();
  });

  it("shows green badge for expiration more than 3 days away", () => {
    withDate("2026-04-27");
    render(
      <PantryItemCard
        item={{ ...BASE, expiration_date: "2026-12-01" }}
        onEdit={vi.fn()}
        onDeleted={vi.fn()}
      />
    );
    const badge = screen.getByText(/^Exp /);
    expect(badge.className).toContain("emerald");
    expect(badge.textContent).not.toContain("soon");
    expect(badge.textContent).not.toContain("expired");
  });

  it("shows amber 'soon' badge for expiration within 3 days", () => {
    withDate("2026-04-27");
    render(
      <PantryItemCard
        item={{ ...BASE, expiration_date: "2026-04-29" }}
        onEdit={vi.fn()}
        onDeleted={vi.fn()}
      />
    );
    const badge = screen.getByText(/soon/);
    expect(badge.className).toContain("amber");
  });

  it("shows amber 'soon' badge for expiration today", () => {
    withDate("2026-04-27");
    render(
      <PantryItemCard
        item={{ ...BASE, expiration_date: "2026-04-27" }}
        onEdit={vi.fn()}
        onDeleted={vi.fn()}
      />
    );
    expect(screen.getByText(/soon/)).toBeInTheDocument();
  });

  it("shows red 'expired' badge for past expiration", () => {
    withDate("2026-04-27");
    render(
      <PantryItemCard
        item={{ ...BASE, expiration_date: "2026-01-01" }}
        onEdit={vi.fn()}
        onDeleted={vi.fn()}
      />
    );
    const badge = screen.getByText(/expired/);
    expect(badge.className).toContain("red");
  });

  it("calls onEdit with the item when edit button is clicked", () => {
    const onEdit = vi.fn();
    render(<PantryItemCard item={BASE} onEdit={onEdit} onDeleted={vi.fn()} />);
    fireEvent.click(screen.getByTitle("Edit"));
    expect(onEdit).toHaveBeenCalledWith(BASE);
  });

  it("calls fetch DELETE and onDeleted when delete is confirmed", async () => {
    // Real timers needed so Promise resolution isn't blocked
    vi.useRealTimers();
    vi.stubGlobal("confirm", vi.fn(() => true));
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true })));
    const onDeleted = vi.fn();

    render(<PantryItemCard item={BASE} onEdit={vi.fn()} onDeleted={onDeleted} />);
    fireEvent.click(screen.getByTitle("Delete"));

    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("abc-123"));
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("abc-123"), { method: "DELETE" });
  });

  it("does not call onDeleted when delete is cancelled", () => {
    vi.stubGlobal("confirm", vi.fn(() => false));
    const onDeleted = vi.fn();

    render(<PantryItemCard item={BASE} onEdit={vi.fn()} onDeleted={onDeleted} />);
    fireEvent.click(screen.getByTitle("Delete"));

    expect(onDeleted).not.toHaveBeenCalled();
  });

  it("renders notes when present", () => {
    render(
      <PantryItemCard
        item={{ ...BASE, notes: "Cooking use only" }}
        onEdit={vi.fn()}
        onDeleted={vi.fn()}
      />
    );
    expect(screen.getByText("Cooking use only")).toBeInTheDocument();
  });

  it("omits brand element when brand is null", () => {
    render(<PantryItemCard item={{ ...BASE, brand: null }} onEdit={vi.fn()} onDeleted={vi.fn()} />);
    expect(screen.queryByText("California Olive Ranch")).not.toBeInTheDocument();
  });
});
