"use client";

import { useCallback, useEffect, useState } from "react";
import GoogleAuth from "../components/google-auth";
import { AuthUser, BACKEND, OAUTH_ENABLED, fetchWithAuth, getAuthToken } from "../lib/auth";
import PantryForm from "./PantryForm";
import PantryItemCard from "./PantryItemCard";
import { Category, CATEGORY_LABELS, PantryItem, StorageLocation } from "./types";

const TABS: { key: StorageLocation; label: string; icon: string }[] = [
  { key: "pantry", label: "Pantry", icon: "🫙" },
  { key: "fridge", label: "Fridge", icon: "🧊" },
  { key: "freezer", label: "Freezer", icon: "❄️" },
];

export default function PantryPage() {
  const [authRequired, setAuthRequired] = useState(OAUTH_ENABLED);
  const [user, setUser] = useState<AuthUser | null>(OAUTH_ENABLED ? null : { sub: "local", email: "local", name: "Local", picture: null });
  const [items, setItems] = useState<PantryItem[]>([]);
  const [loading, setLoading] = useState(!authRequired || Boolean(getAuthToken()));
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<StorageLocation>("pantry");
  const [categoryFilter, setCategoryFilter] = useState<Category | "all">("all");
  const [formOpen, setFormOpen] = useState(false);
  const [editItem, setEditItem] = useState<PantryItem | undefined>(undefined);
  const [reloadToken, setReloadToken] = useState(0);

  const handleAuthenticated = useCallback((nextUser: AuthUser) => {
    setAuthRequired(true);
    setUser(nextUser);
    setLoading(true);
    setReloadToken((prev) => prev + 1);
  }, []);

  useEffect(() => {
    if (authRequired && !getAuthToken()) return;

    let cancelled = false;
    async function loadItems() {
      try {
        const res = await fetchWithAuth(`${BACKEND}/api/pantry?location=${activeTab}`);
        if (res.status === 401) {
          setAuthRequired(true);
          setUser(null);
          throw new Error("Please sign in again");
        }
        if (!res.ok) throw new Error(`Failed to load (${res.status})`);

        if (!cancelled) {
          setItems(await res.json());
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load items");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadItems();
    return () => {
      cancelled = true;
    };
  }, [activeTab, reloadToken, authRequired]);

  if (authRequired && (!user || !getAuthToken())) {
    return (
      <div className="flex h-full items-center justify-center p-6 bg-stone-50 dark:bg-stone-950">
        <GoogleAuth onAuthenticated={handleAuthenticated} />
      </div>
    );
  }

  function handleTabChange(tab: StorageLocation) {
    setLoading(true);
    setActiveTab(tab);
    setCategoryFilter("all");
  }

  function handleRetry() {
    setLoading(true);
    setReloadToken((prev) => prev + 1);
  }

  function handleSaved(saved: PantryItem) {
    if (saved.storage_location !== activeTab) {
      setItems((prev) => prev.filter((i) => i.id !== saved.id));
    } else {
      setItems((prev) => {
        const exists = prev.find((i) => i.id === saved.id);
        return exists ? prev.map((i) => (i.id === saved.id ? saved : i)) : [...prev, saved];
      });
    }
    setFormOpen(false);
    setEditItem(undefined);
  }

  function openAdd() {
    setEditItem(undefined);
    setFormOpen(true);
  }

  function openEdit(item: PantryItem) {
    setEditItem(item);
    setFormOpen(true);
  }

  function handleDeleted(id: string) {
    setItems((prev) => prev.filter((i) => i.id !== id));
  }

  const categories = Array.from(new Set(items.map((i) => i.category))) as Category[];
  const filtered = categoryFilter === "all" ? items : items.filter((i) => i.category === categoryFilter);

  const sorted = [...filtered].sort((a, b) => {
    if (!a.expiration_date && !b.expiration_date) return a.name.localeCompare(b.name);
    if (!a.expiration_date) return 1;
    if (!b.expiration_date) return -1;
    return a.expiration_date.localeCompare(b.expiration_date);
  });

  return <div className="flex flex-col h-full bg-stone-50 dark:bg-stone-950">{/* existing UI */}
      <header className="shrink-0 px-6 py-4 bg-white dark:bg-stone-900 border-b border-stone-200 dark:border-stone-800">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold text-stone-900 dark:text-stone-50">Pantry</h1>
          <button onClick={openAdd} className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white transition-colors"><span className="text-base leading-none">+</span> Add item</button>
        </div>
        <div className="flex gap-1 mt-3">{TABS.map((tab) => <button key={tab.key} onClick={() => handleTabChange(tab.key)} className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg font-medium transition-colors ${activeTab === tab.key ? "bg-emerald-600 text-white" : "text-stone-600 dark:text-stone-400 hover:bg-stone-100 dark:hover:bg-stone-800"}`}><span>{tab.icon}</span>{tab.label}</button>)}</div>
      </header>
      {categories.length > 1 && <div className="shrink-0 px-6 py-2 bg-white dark:bg-stone-900 border-b border-stone-200 dark:border-stone-800 flex gap-1.5 overflow-x-auto"><button onClick={() => setCategoryFilter("all")} className={`shrink-0 px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${categoryFilter === "all" ? "bg-stone-900 dark:bg-stone-100 text-white dark:text-stone-900" : "bg-stone-100 dark:bg-stone-800 text-stone-600 dark:text-stone-400 hover:bg-stone-200 dark:hover:bg-stone-700"}`}>All</button>{categories.map((c) => <button key={c} onClick={() => setCategoryFilter(c)} className={`shrink-0 px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${categoryFilter === c ? "bg-stone-900 dark:bg-stone-100 text-white dark:text-stone-900" : "bg-stone-100 dark:bg-stone-800 text-stone-600 dark:text-stone-400 hover:bg-stone-200 dark:hover:bg-stone-700"}`}>{CATEGORY_LABELS[c]}</button>)}</div>}
      <div className="flex-1 overflow-y-auto px-6 py-4">{loading ? <div className="flex items-center justify-center h-32 text-stone-400 text-sm">Loading…</div> : error ? <div className="flex flex-col items-center justify-center h-32 gap-2"><p className="text-sm text-red-500">{error}</p><button onClick={handleRetry} className="text-xs text-emerald-600 hover:underline">Retry</button></div> : sorted.length === 0 ? <div className="flex flex-col items-center justify-center h-32 gap-3 text-center"><p className="text-stone-400 text-sm">{categoryFilter !== "all" ? `No ${CATEGORY_LABELS[categoryFilter as Category]} items in your ${activeTab}` : `Your ${activeTab} is empty`}</p><button onClick={openAdd} className="text-sm text-emerald-600 hover:underline font-medium">Add your first item</button></div> : <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">{sorted.map((item) => <PantryItemCard key={item.id} item={item} onEdit={openEdit} onDeleted={handleDeleted} />)}</div>}</div>
      {formOpen && <PantryForm item={editItem} defaultLocation={activeTab} onSaved={handleSaved} onClose={() => { setFormOpen(false); setEditItem(undefined); }} />}
    </div>;
}
