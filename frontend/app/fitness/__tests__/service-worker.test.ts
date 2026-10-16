// @vitest-environment node
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { expect, it, vi } from "vitest";

function worker() {
  const listeners: Record<string,(event:unknown)=>void> = {};
  const cache = {addAll:vi.fn().mockResolvedValue(undefined),match:vi.fn().mockResolvedValue(new Response("offline shell"))};
  const fetch = vi.fn().mockRejectedValue(new Error("offline"));
  const caches = {open:vi.fn().mockResolvedValue(cache),keys:async () => [],delete:vi.fn()};
  const code = readFileSync(new URL("../../../public/sw.js",import.meta.url),"utf8")
    .replace("const PRECACHE = [];",'const PRECACHE = ["/fitness/", "/_next/static/chunk.js"];');
  runInNewContext(code,{self:{addEventListener:(name:string,fn:(event:unknown)=>void)=>{listeners[name]=fn;},location:{origin:"https://test.invalid"},clients:{claim:vi.fn()}},caches,fetch,URL,Response,AbortSignal});
  return {listeners,cache,fetch};
}
it("preloads the complete build manifest before installation succeeds",async () => {
  const w = worker();
  let done:Promise<void> | undefined;
  w.listeners.install({waitUntil:(p:Promise<void>)=>{done=p;}});
  await done;
  expect(w.cache.addAll).toHaveBeenCalledWith(["/fitness/","/_next/static/chunk.js"]);
});
it("falls back to the cached Fitness shell after a failed request",async () => {
  const w = worker();
  let result:Promise<Response> | undefined;
  w.listeners.fetch({request:{url:"https://test.invalid/fitness/",method:"GET",mode:"navigate"},respondWith:(p:Promise<Response>)=>{result=p;}});
  expect(await (await result)?.text()).toBe("offline shell");
  expect(w.fetch).toHaveBeenCalledTimes(1);
});
it("does not intercept authenticated API requests",() => {
  const w = worker();
  const respondWith = vi.fn();
  w.listeners.fetch({request:{url:"https://test.invalid/api/auth/me",method:"GET"},respondWith});
  expect(respondWith).not.toHaveBeenCalled();
});
it("recovers old home-screen root shortcuts into Fitness offline",async () => {
  const w = worker();
  let result:Promise<Response> | undefined;
  w.listeners.fetch({request:{url:"https://test.invalid/",method:"GET",mode:"navigate"},respondWith:(p:Promise<Response>)=>{result=p;}});
  expect((await result)?.headers.get("location")).toBe("https://test.invalid/fitness/");
});

it("prefers the current server page over the cached shell",async () => {
  const w = worker();
  w.fetch.mockResolvedValue(new Response("current server shell"));
  let result:Promise<Response> | undefined;
  w.listeners.fetch({request:{url:"https://test.invalid/fitness/",method:"GET",mode:"navigate"},respondWith:(p:Promise<Response>)=>{result=p;}});
  expect(await (await result)?.text()).toBe("current server shell");
  expect(w.cache.match).not.toHaveBeenCalled();
});
it("falls back on server errors without hiding client errors",async () => {
  const w = worker();
  let result:Promise<Response> | undefined;
  const event = {request:{url:"https://test.invalid/fitness/",method:"GET",mode:"navigate"},respondWith:(p:Promise<Response>)=>{result=p;}};
  w.fetch.mockResolvedValue(new Response("unavailable",{status:503}));
  w.listeners.fetch(event);
  expect(await (await result)?.text()).toBe("offline shell");
  w.fetch.mockResolvedValue(new Response("not found",{status:404}));
  w.listeners.fetch(event);
  expect((await result)?.status).toBe(404);
});
