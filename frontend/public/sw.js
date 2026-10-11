/* Build replaces this manifest with the complete exported app shell. */
const PRECACHE = [];
const CACHE = "fitness-shell-development";

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    if (!PRECACHE.length) throw new Error("Offline shell requires a production build.");
    const cache = await caches.open(CACHE);
    try { await cache.addAll(PRECACHE); }
    catch (error) { await caches.delete(CACHE); throw error; }
    // Do not skipWaiting: existing pages keep their matching JS until closed.
  })());
});
self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith("fitness-shell-") && key !== CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || event.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  if (event.request.mode === "navigate") {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE);
      if (url.pathname.replace(/\/$/, "") === "/fitness") {
        const shell = await cache.match("/fitness/");
        if (shell) return shell;
      }
      try {
        const response = await fetch(event.request, {signal:AbortSignal.timeout(4000)});
        if (response.ok) return response;
      } catch { /* Existing home-screen shortcuts may still start at /. */ }
      return Response.redirect(new URL("/fitness/", self.location.origin).href);
    })());
    return;
  }
  // Only cache build-produced public assets. Never cache authenticated API data,
  // auth responses, or arbitrary runtime HTML/RSC under the same cache key.
  if (PRECACHE.includes(url.pathname)) {
    event.respondWith(caches.open(CACHE).then(async cache => (await cache.match(url.pathname)) ?? fetch(event.request)));
  }
});
