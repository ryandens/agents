"use client";

import { useAuth } from "../components/AuthProvider";
import { BACKEND, CATEGORY_LABELS, PantryItem } from "./types";

interface Props {
  item: PantryItem;
  onEdit: (item: PantryItem) => void;
  onDeleted: (id: string) => void;
}

type ExpiryStatus = "expired" | "soon" | "ok" | "none";

function expiryStatus(dateStr: string | null): ExpiryStatus {
  if (!dateStr) return "none";
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const exp = new Date(dateStr + "T00:00:00");
  const diff = Math.floor((exp.getTime() - today.getTime()) / 86_400_000);
  if (diff < 0) return "expired";
  if (diff <= 3) return "soon";
  return "ok";
}

const EXPIRY_BADGE: Record<ExpiryStatus, string> = {
  expired: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  soon: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  ok: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  none: "bg-stone-100 text-stone-500 dark:bg-stone-800 dark:text-stone-400",
};

function formatDate(dateStr: string): string {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function expiryLabel(dateStr: string | null, status: ExpiryStatus): string {
  if (!dateStr) return "No expiry";
  const base = `Exp ${formatDate(dateStr)}`;
  if (status === "expired") return `${base} · expired`;
  if (status === "soon") return `${base} · soon`;
  return base;
}

export default function PantryItemCard({ item, onEdit, onDeleted }: Props) {
  const { token } = useAuth();
  const status = expiryStatus(item.expiration_date);

  async function handleDelete() {
    if (!confirm(`Delete "${item.name}"?`)) return;
    await fetch(`${BACKEND}/api/pantry/${item.id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    onDeleted(item.id);
  }

  return (
    <div className="group bg-white dark:bg-stone-900 rounded-xl border border-stone-200 dark:border-stone-700 p-4 flex flex-col gap-2 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-stone-900 dark:text-stone-50 truncate">
            {item.name}
          </p>
          {item.brand && (
            <p className="text-xs text-stone-400 dark:text-stone-500 truncate">{item.brand}</p>
          )}
        </div>
        <div className="flex gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={() => onEdit(item)}
            className="w-6 h-6 rounded flex items-center justify-center text-stone-400 hover:text-stone-700 dark:hover:text-stone-200 hover:bg-stone-100 dark:hover:bg-stone-800 transition-colors text-xs"
            title="Edit"
          >
            ✎
          </button>
          <button
            onClick={handleDelete}
            className="w-6 h-6 rounded flex items-center justify-center text-stone-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors text-xs"
            title="Delete"
          >
            ✕
          </button>
        </div>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="px-2 py-0.5 rounded-full text-xs bg-stone-100 dark:bg-stone-800 text-stone-600 dark:text-stone-400">
          {CATEGORY_LABELS[item.category]}
        </span>
        <span className="text-xs font-medium text-stone-700 dark:text-stone-300">
          {item.quantity % 1 === 0 ? item.quantity : item.quantity.toFixed(2)} {item.unit}
        </span>
      </div>

      <span
        className={`self-start px-2 py-0.5 rounded-full text-xs font-medium ${EXPIRY_BADGE[status]}`}
      >
        {expiryLabel(item.expiration_date, status)}
      </span>

      {item.notes && (
        <p className="text-xs text-stone-400 dark:text-stone-500 line-clamp-2">{item.notes}</p>
      )}
    </div>
  );
}
