"use client";

import { useEffect, useState } from "react";
import { useAuth } from "../components/AuthProvider";
import {
  CATEGORY_LABELS,
  Category,
  PantryItem,
  PantryItemCreate,
  StorageLocation,
  UNIT_GROUPS,
  Unit,
} from "./types";

interface Props {
  item?: PantryItem;
  defaultLocation?: StorageLocation;
  onSaved: (item: PantryItem) => void;
  onClose: () => void;
}

const EMPTY: PantryItemCreate = {
  name: "",
  brand: null,
  category: "other",
  storage_location: "pantry",
  quantity: 1,
  unit: "count",
  purchase_date: null,
  expiration_date: null,
  notes: null,
};

export default function PantryForm({ item, defaultLocation, onSaved, onClose }: Props) {
  const [form, setForm] = useState<PantryItemCreate>(
    item
      ? {
          name: item.name,
          brand: item.brand,
          category: item.category,
          storage_location: item.storage_location,
          quantity: item.quantity,
          unit: item.unit,
          purchase_date: item.purchase_date,
          expiration_date: item.expiration_date,
          notes: item.notes,
        }
      : { ...EMPTY, storage_location: defaultLocation ?? "pantry" }
  );
  const { token } = useAuth();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function set<K extends keyof PantryItemCreate>(key: K, value: PantryItemCreate[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSubmit(e: React.FormEvent | React.MouseEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const url = item ? `/api/pantry/${item.id}` : "/api/pantry";
      const method = item ? "PATCH" : "POST";
      const res = await fetch(url, {
        method,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail?.detail ?? `Request failed (${res.status})`);
      }
      const saved: PantryItem = await res.json();
      onSaved(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-full max-w-lg bg-white dark:bg-stone-900 rounded-2xl shadow-xl flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between px-6 py-4 border-b border-stone-200 dark:border-stone-700 shrink-0">
          <h2 className="text-base font-semibold text-stone-900 dark:text-stone-50">
            {item ? "Edit item" : "Add item"}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="w-7 h-7 rounded-full flex items-center justify-center text-stone-400 hover:bg-stone-100 dark:hover:bg-stone-800 transition-colors"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="overflow-y-auto flex-1 px-6 py-4 space-y-4">
          {/* Name + Brand */}
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2 sm:col-span-1">
              <label
                htmlFor="pf-name"
                className="block text-xs font-medium text-stone-600 dark:text-stone-400 mb-1"
              >
                Name <span className="text-red-500">*</span>
              </label>
              <input
                id="pf-name"
                required
                type="text"
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                placeholder="e.g. Whole milk"
                className="w-full text-sm rounded-lg border border-stone-200 dark:border-stone-700 bg-stone-50 dark:bg-stone-800 px-3 py-2 text-stone-900 dark:text-stone-100 placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
            <div className="col-span-2 sm:col-span-1">
              <label
                htmlFor="pf-brand"
                className="block text-xs font-medium text-stone-600 dark:text-stone-400 mb-1"
              >
                Brand
              </label>
              <input
                id="pf-brand"
                type="text"
                value={form.brand ?? ""}
                onChange={(e) => set("brand", e.target.value || null)}
                placeholder="e.g. Organic Valley"
                className="w-full text-sm rounded-lg border border-stone-200 dark:border-stone-700 bg-stone-50 dark:bg-stone-800 px-3 py-2 text-stone-900 dark:text-stone-100 placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
          </div>

          {/* Location + Category */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="pf-location"
                className="block text-xs font-medium text-stone-600 dark:text-stone-400 mb-1"
              >
                Location <span className="text-red-500">*</span>
              </label>
              <select
                id="pf-location"
                value={form.storage_location}
                onChange={(e) => set("storage_location", e.target.value as StorageLocation)}
                className="w-full text-sm rounded-lg border border-stone-200 dark:border-stone-700 bg-stone-50 dark:bg-stone-800 px-3 py-2 text-stone-900 dark:text-stone-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="pantry">Pantry</option>
                <option value="fridge">Fridge</option>
                <option value="freezer">Freezer</option>
              </select>
            </div>
            <div>
              <label
                htmlFor="pf-category"
                className="block text-xs font-medium text-stone-600 dark:text-stone-400 mb-1"
              >
                Category <span className="text-red-500">*</span>
              </label>
              <select
                id="pf-category"
                value={form.category}
                onChange={(e) => set("category", e.target.value as Category)}
                className="w-full text-sm rounded-lg border border-stone-200 dark:border-stone-700 bg-stone-50 dark:bg-stone-800 px-3 py-2 text-stone-900 dark:text-stone-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                {(Object.keys(CATEGORY_LABELS) as Category[]).map((c) => (
                  <option key={c} value={c}>
                    {CATEGORY_LABELS[c]}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Quantity + Unit */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="pf-quantity"
                className="block text-xs font-medium text-stone-600 dark:text-stone-400 mb-1"
              >
                Quantity <span className="text-red-500">*</span>
              </label>
              <input
                id="pf-quantity"
                required
                type="number"
                min="0"
                step="any"
                value={form.quantity}
                onChange={(e) => set("quantity", parseFloat(e.target.value) || 0)}
                className="w-full text-sm rounded-lg border border-stone-200 dark:border-stone-700 bg-stone-50 dark:bg-stone-800 px-3 py-2 text-stone-900 dark:text-stone-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
            <div>
              <label
                htmlFor="pf-unit"
                className="block text-xs font-medium text-stone-600 dark:text-stone-400 mb-1"
              >
                Unit <span className="text-red-500">*</span>
              </label>
              <select
                id="pf-unit"
                value={form.unit}
                onChange={(e) => set("unit", e.target.value as Unit)}
                className="w-full text-sm rounded-lg border border-stone-200 dark:border-stone-700 bg-stone-50 dark:bg-stone-800 px-3 py-2 text-stone-900 dark:text-stone-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                {UNIT_GROUPS.map((group) => (
                  <optgroup key={group.label} label={group.label}>
                    {group.units.map((u) => (
                      <option key={u} value={u}>
                        {u}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
          </div>

          {/* Dates */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="pf-purchase-date"
                className="block text-xs font-medium text-stone-600 dark:text-stone-400 mb-1"
              >
                Purchase date
              </label>
              <input
                id="pf-purchase-date"
                type="date"
                value={form.purchase_date ?? ""}
                onChange={(e) => set("purchase_date", e.target.value || null)}
                className="w-full text-sm rounded-lg border border-stone-200 dark:border-stone-700 bg-stone-50 dark:bg-stone-800 px-3 py-2 text-stone-900 dark:text-stone-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
            <div>
              <label
                htmlFor="pf-expiration-date"
                className="block text-xs font-medium text-stone-600 dark:text-stone-400 mb-1"
              >
                Expiration date
              </label>
              <input
                id="pf-expiration-date"
                type="date"
                value={form.expiration_date ?? ""}
                onChange={(e) => set("expiration_date", e.target.value || null)}
                className="w-full text-sm rounded-lg border border-stone-200 dark:border-stone-700 bg-stone-50 dark:bg-stone-800 px-3 py-2 text-stone-900 dark:text-stone-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
          </div>

          {/* Notes */}
          <div>
            <label
              htmlFor="pf-notes"
              className="block text-xs font-medium text-stone-600 dark:text-stone-400 mb-1"
            >
              Notes
            </label>
            <textarea
              id="pf-notes"
              rows={2}
              value={form.notes ?? ""}
              onChange={(e) => set("notes", e.target.value || null)}
              placeholder="Optional notes…"
              className="w-full text-sm rounded-lg border border-stone-200 dark:border-stone-700 bg-stone-50 dark:bg-stone-800 px-3 py-2 text-stone-900 dark:text-stone-100 placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-emerald-500 resize-none"
            />
          </div>

          {error && (
            <p className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2">
              {error}
            </p>
          )}
        </form>

        <div className="px-6 py-4 border-t border-stone-200 dark:border-stone-700 flex justify-end gap-2 shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg border border-stone-200 dark:border-stone-700 text-stone-700 dark:text-stone-300 hover:bg-stone-50 dark:hover:bg-stone-800 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={saving}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white transition-colors"
          >
            {saving ? "Saving…" : item ? "Save changes" : "Add item"}
          </button>
        </div>
      </div>
    </div>
  );
}
