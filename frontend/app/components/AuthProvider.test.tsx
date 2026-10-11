import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./AuthProvider";

function Profile() { return <p>Local account: {useAuth().user.sub}</p>; }
beforeEach(() => {localStorage.clear(); window.history.replaceState({},"","/fitness/");});
afterEach(() => vi.unstubAllGlobals());
const cached = {sub:"original",email:"demo@example.test",name:"Demo",picture:""};
it("opens cached Fitness without waiting for the VPN",async () => {
  localStorage.setItem("fitness-offline-identity",JSON.stringify(cached));
  vi.stubGlobal("fetch",vi.fn(() => new Promise(() => {})));
  render(<AuthProvider><Profile/></AuthProvider>);
  expect(await screen.findByText("Local account: original")).toBeInTheDocument();
});
it("keeps local Fitness accessible when the session expires",async () => {
  localStorage.setItem("fitness-offline-identity",JSON.stringify(cached));
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue({ok:false,status:401}));
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
