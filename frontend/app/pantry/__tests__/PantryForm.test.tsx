import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../components/AuthProvider", () => ({
  useAuth: () => ({ token: "test-token" }),
}));

import PantryForm from "../PantryForm";
import type { PantryItem } from "../types";

const SAVED: PantryItem = {
  id: "item-999",
  name: "Olive Oil",
  brand: "California Olive Ranch",
  category: "condiments",
  storage_location: "pantry",
  quantity: 1,
  unit: "bottle",
  purchase_date: null,
  expiration_date: "2026-12-01",
  notes: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function mockFetch(body: unknown, ok = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok,
        status: ok ? 200 : 422,
        json: () => Promise.resolve(body),
      })
    )
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("PantryForm", () => {
  it("renders all form fields", () => {
    render(<PantryForm onSaved={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByLabelText(/Name/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Brand/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Location/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Category/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Quantity/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Unit/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Purchase date/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Expiration date/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Notes/)).toBeInTheDocument();
  });

  it("shows 'Add item' title for new items", () => {
    render(<PantryForm onSaved={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Add item" })).toBeInTheDocument();
  });

  it("shows 'Edit item' title when an existing item is provided", () => {
    render(<PantryForm item={SAVED} onSaved={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Edit item" })).toBeInTheDocument();
  });

  it("defaults Location to the defaultLocation prop", () => {
    render(<PantryForm defaultLocation="fridge" onSaved={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByLabelText(/Location/)).toHaveValue("fridge");
  });

  it("defaults Location to pantry when no defaultLocation given", () => {
    render(<PantryForm onSaved={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByLabelText(/Location/)).toHaveValue("pantry");
  });

  it("pre-fills all fields when editing an existing item", () => {
    render(<PantryForm item={SAVED} onSaved={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByLabelText(/Name/)).toHaveValue("Olive Oil");
    expect(screen.getByLabelText(/Brand/)).toHaveValue("California Olive Ranch");
    expect(screen.getByLabelText(/Location/)).toHaveValue("pantry");
    expect(screen.getByLabelText(/Category/)).toHaveValue("condiments");
    expect(screen.getByLabelText(/Quantity/)).toHaveValue(1);
    expect(screen.getByLabelText(/Unit/)).toHaveValue("bottle");
    expect(screen.getByLabelText(/Expiration date/)).toHaveValue("2026-12-01");
  });

  it("POSTs to /api/pantry and calls onSaved for new items", async () => {
    mockFetch(SAVED);
    const onSaved = vi.fn();
    const user = userEvent.setup();
    render(<PantryForm onSaved={onSaved} onClose={vi.fn()} />);

    await user.type(screen.getByLabelText(/Name/), "Olive Oil");
    fireEvent.click(screen.getByRole("button", { name: /Add item/ }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/pantry"),
        expect.objectContaining({ method: "POST" })
      )
    );
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(SAVED));
  });

  it("PATCHes to /api/pantry/{id} and calls onSaved for existing items", async () => {
    mockFetch(SAVED);
    const onSaved = vi.fn();
    render(<PantryForm item={SAVED} onSaved={onSaved} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /Save changes/ }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining(`/api/pantry/${SAVED.id}`),
        expect.objectContaining({ method: "PATCH" })
      )
    );
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(SAVED));
  });

  it("shows an error message when the API returns a failure", async () => {
    mockFetch({ detail: "Validation failed" }, false);
    render(<PantryForm onSaved={vi.fn()} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /Add item/ }));

    await waitFor(() => expect(screen.getByText("Validation failed")).toBeInTheDocument());
  });

  it("calls onClose when Cancel is clicked", () => {
    const onClose = vi.fn();
    render(<PantryForm onSaved={vi.fn()} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onClose when the ✕ close button is clicked", () => {
    const onClose = vi.fn();
    render(<PantryForm onSaved={vi.fn()} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onClose when Escape is pressed", () => {
    const onClose = vi.fn();
    render(<PantryForm onSaved={vi.fn()} onClose={onClose} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });
});
