import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./AuthProvider";

function Profile() { return <p>Local account: {useAuth().user.sub}</p>; }
beforeEach(() => {localStorage.clear(); window.history.replaceState({},"","/fitness/");});
afterEach(() => vi.unstubAllGlobals());
const cached = {sub:"original",email:"demo@example.test",name:"Demo",picture:""};
it("waits for the current session before using the cached profile",async () => {
  localStorage.setItem("fitness-offline-identity",JSON.stringify(cached));
  let reject!: (reason: Error) => void;
  vi.stubGlobal("fetch",vi.fn(() => new Promise((_, fail) => {reject=fail;})));
  render(<AuthProvider><Profile/></AuthProvider>);
  expect(screen.getByText("Loading…")).toBeInTheDocument();
  expect(screen.queryByText("Local account: original")).not.toBeInTheDocument();
  reject(new TypeError("network unavailable"));
  expect(await screen.findByText("Local account: original")).toBeInTheDocument();
});
it("requires sign-in when the server rejects the session",async () => {
  localStorage.setItem("fitness-offline-identity",JSON.stringify(cached));
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue({ok:false,status:401}));
  render(<AuthProvider><Profile/></AuthProvider>);
  expect(await screen.findByText("Sign in with Google")).toBeInTheDocument();
  expect(screen.queryByText("Local account: original")).not.toBeInTheDocument();
});
it("uses the recovery profile on a server error",async () => {
  localStorage.setItem("fitness-offline-identity",JSON.stringify(cached));
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue({ok:false,status:503}));
  render(<AuthProvider><Profile/></AuthProvider>);
  expect(await screen.findByText("Local account: original")).toBeInTheDocument();
});
it("switches partitions when another account signs in",async () => {
  localStorage.setItem("fitness-offline-identity",JSON.stringify(cached));
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue({ok:true,json:async () => ({...cached,sub:"other"})}));
  render(<AuthProvider><Profile/></AuthProvider>);
  await waitFor(() => expect(screen.getByText("Local account: other")).toBeInTheDocument());
});
it("does not unlock other pages using the cached profile",async () => {
  window.history.replaceState({},"","/pantry/");
  localStorage.setItem("fitness-offline-identity",JSON.stringify(cached));
  vi.stubGlobal("fetch",vi.fn().mockRejectedValue(new TypeError("offline")));
  render(<AuthProvider><Profile/></AuthProvider>);
  expect(await screen.findByText("Sign in with Google")).toBeInTheDocument();
});
