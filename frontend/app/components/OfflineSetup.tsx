"use client";
import { useEffect, useState } from "react";

export default function OfflineSetup() {
  const [status, setStatus] = useState("Preparing offline launch…");
  useEffect(() => {
    let active = true;
    let preparing = false;
    let ready = false;
    if (!("serviceWorker" in navigator)) {
      Promise.resolve().then(() => setStatus("This browser cannot install the offline app shell."));
      return;
    }
    if (process.env.NODE_ENV !== "production") {
      Promise.resolve().then(() => setStatus("Offline launch is available in the production build."));
      return;
    }
    async function prepare() {
      if (preparing || ready || document.visibilityState === "hidden") return;
      preparing = true;
      let deadline: ReturnType<typeof setTimeout> | undefined;
      try {
        // ready alone never rejects when installation fails. Bound the whole
        // attempt, including registration, and retry when connectivity returns.
        await Promise.race([
          navigator.serviceWorker.register("/sw.js", {scope:"/", updateViaCache:"none"})
            .then(() => navigator.serviceWorker.ready),
          new Promise<never>((_, reject) => {
            deadline = setTimeout(() => reject(new Error("Offline setup timed out")), 15000);
          }),
        ]);
        ready = true;
        if (active) setStatus("Ready to open offline");
        // A Home Screen install is one of WebKit's persistence heuristics.
        await navigator.storage?.persist?.().catch(() => false);
      } catch {
        if (active) setStatus("Offline launch isn't ready. Connect to the VPN; setup will retry automatically.");
      } finally {
        if (deadline) clearTimeout(deadline);
        preparing = false;
      }
    }
    void prepare();
    const retry = setInterval(prepare, 30000);
    window.addEventListener("online", prepare);
    window.addEventListener("focus", prepare);
    document.addEventListener("visibilitychange", prepare);
    return () => {
      active = false;
      clearInterval(retry);
      window.removeEventListener("online", prepare);
      window.removeEventListener("focus", prepare);
      document.removeEventListener("visibilitychange", prepare);
    };
  }, []);
  return <p className="text-xs text-stone-500" role="status">{status}</p>;
}
